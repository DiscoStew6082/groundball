"""Shared grounded answer service used by CLI and API."""

from __future__ import annotations

import logging
from typing import Any, Callable

from baseball_rag.db import (
    get_career_stat_leaders,
    get_player_stat,
    get_stat_leaders_range,
    init_db,
)
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.provenance import SourceRecord, StructuredAnswer, compact_data_manifest
from baseball_rag.retrieval.chroma_store import RetrievedChunk, get_chunks_by_ids, retrieve
from baseball_rag.retrieval.static_vocab import (
    query_asks_for_explanation,
    stat_definition_doc_ids_for_query,
)
from baseball_rag.retrieval.strategies import RetrievalStrategy, get_strategy
from baseball_rag.routing import route
from baseball_rag.routing.query_router import TimePeriod, TimePeriodType

logger = logging.getLogger(__name__)
PromptBuilder = Callable[[str, list[RetrievedChunk]], tuple[str, str] | str]


def answer(
    question: str,
    *,
    retrieval_strategy: str | RetrievalStrategy | None = None,
) -> StructuredAnswer:
    """Answer a question with explicit grounding metadata."""
    init_db()
    decision = route(question)

    if decision.intent == "stat_query":
        return _answer_stat_query(question, decision)
    if decision.intent == "player_biography":
        return _answer_player_biography(question, decision, retrieval_strategy=retrieval_strategy)
    if decision.intent == "freeform_query":
        return _answer_freeform(question, decision)
    return _answer_general(question, decision, retrieval_strategy=retrieval_strategy)


def render_text(result: StructuredAnswer) -> str:
    """Render a structured answer for terminal/chat use."""
    lines = [result.answer]
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _answer_stat_query(question: str, decision: Any) -> StructuredAnswer:
    stat = decision.stat or "HR"
    tp = _resolve_time_period(decision.time_period)

    if decision.player_name:
        conn = get_duckdb()
        result = get_player_stat(conn, decision.player_name, stat, year=decision.year)
        if not result:
            qualifier = f" in {decision.year}" if decision.year else ""
            return StructuredAnswer(
                answer=(
                    f"No {stat} result found for {decision.player_name}{qualifier} "
                    "in the local Lahman-derived batting data."
                ),
                intent=decision.intent,
                sources=[_duckdb_source("Player stat lookup", tables=["batting", "people"])],
                warnings=[
                    "No fallback leaderboard was returned because the question named a player."
                ],
                unsupported=True,
            )

        team_str = f" ({result['team']})" if result["team"] else ""
        return StructuredAnswer(
            answer=f"{result['name']}{team_str} ({result['year']}): {result['stat_value']} {stat}",
            intent=decision.intent,
            sources=[
                _duckdb_source(
                    "Player stat lookup",
                    tables=["batting", "people"],
                    rows=[result],
                )
            ],
        )

    if tp is not None:
        start_year, end_year = tp
        rows = get_stat_leaders_range(stat, start_year, end_year)
        lines = [f"Top {stat} leaders ({start_year}-{end_year}):"]
        for i, row in enumerate(rows[:10], 1):
            lines.append(f"  {i}. {row['name']}: {row['stat_value']} {stat}")
        return StructuredAnswer(
            answer="\n".join(lines),
            intent=decision.intent,
            sources=[
                _duckdb_source(
                    f"{stat} leaderboard for {start_year}-{end_year}",
                    tables=["batting", "people"],
                    rows=rows,
                )
            ],
        )

    rows = get_career_stat_leaders(stat)
    lines = [f"All-time career {stat} leaders:"]
    for i, row in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {row['name']}: {row['stat_value']} {stat}")
    return StructuredAnswer(
        answer="\n".join(lines),
        intent=decision.intent,
        sources=[
            _duckdb_source(
                f"Career {stat} leaderboard",
                tables=["batting", "people"],
                rows=rows,
            )
        ],
    )


def _answer_player_biography(
    question: str,
    decision: Any,
    *,
    retrieval_strategy: str | RetrievalStrategy | None = None,
) -> StructuredAnswer:
    player_name = decision.player_name or question
    resolved_player_id: str | None = None
    if decision.player_name:
        from baseball_rag.corpus.player_bios import resolve_player_by_name

        resolution = resolve_player_by_name(decision.player_name, get_duckdb())
        if resolution.ambiguous:
            choices = ", ".join(
                f"{c.full_name} ({c.debut or '?'}-{c.final_game or '?'})"
                for c in resolution.candidates[:5]
            )
            return StructuredAnswer(
                answer=(
                    f"'{decision.player_name}' is ambiguous in the local player registry. "
                    f"Try a fuller name. Possible matches: {choices}."
                ),
                intent=decision.intent,
                warnings=["No biography was generated because the player name was ambiguous."],
                unsupported=True,
            )
        resolved_player_id = resolution.player_id

    try:
        strategy = _resolve_retrieval_strategy(retrieval_strategy, default="hybrid_player_bio")
        chunks = strategy.retrieve(
            decision.raw_question,
            top_k=3,
            player_name=player_name,
            player_id=resolved_player_id,
        )
    except Exception as e:  # noqa: BLE001 - Chroma errors vary by installed version
        failure = _chroma_failure_answer(e, intent=decision.intent)
        if failure is not None:
            return failure
        logger.exception("ChromaDB retrieval failed for player biography query %r", question)
        raise

    if not chunks:
        return StructuredAnswer(
            answer=(
                f"No player biography found for '{decision.player_name or question}'. "
                "The player may not be in the corpus or the corpus may need re-indexing."
            ),
            intent=decision.intent,
            warnings=["No LLM fallback was used because no grounding context was retrieved."],
            unsupported=True,
        )

    from baseball_rag.generation.prompt import build_player_bio_prompt

    return _answer_with_grounded_chunks(
        question=decision.raw_question,
        intent=decision.intent,
        chunks=chunks,
        prompt_builder=build_player_bio_prompt,
    )


def _answer_freeform(question: str, decision: Any) -> StructuredAnswer:
    from baseball_rag.db.freeform import format_result, query

    conn = get_duckdb()
    query_result = query(decision.raw_question, conn)
    source = SourceRecord(
        type="duckdb",
        label=query_result.source_label,
        detail=query_result.source_detail,
        sql=query_result.sql,
        columns=query_result.columns,
        rows=_rows_to_dicts(query_result.columns, query_result.rows[:100]),
        data_manifest=compact_data_manifest(),
    )

    if query_result.row_count == 0:
        return StructuredAnswer(
            answer=(
                f"No results found for '{decision.raw_question}'.\n"
                "Try rephrasing with a specific team, player, stat, or year."
            ),
            intent=decision.intent,
            sources=[source],
            unsupported=True,
        )

    warnings = []
    if query_result.truncated:
        warnings.append("Results were truncated at the configured row limit.")
    return StructuredAnswer(
        answer=format_result(query_result, decision.raw_question),
        intent=decision.intent,
        sources=[source],
        warnings=warnings,
    )


def _answer_general(
    question: str,
    decision: Any,
    *,
    retrieval_strategy: str | RetrievalStrategy | None = None,
) -> StructuredAnswer:
    try:
        strategy = _resolve_retrieval_strategy(retrieval_strategy, default="semantic_chroma")
        chunks = _retrieve_static_explanation_chunks(question)
        if not chunks:
            chunks = strategy.retrieve(question, top_k=3)
    except Exception as e:  # noqa: BLE001 - Chroma errors vary by installed version
        failure = _chroma_failure_answer(e, intent=decision.intent)
        if failure is not None:
            return failure
        logger.exception("ChromaDB retrieval failed for query %r", question)
        raise

    if not chunks:
        return StructuredAnswer(
            answer=(
                "No relevant grounded documents were found for that query. "
                "Try asking about an indexed stat definition, indexed player biography, "
                "or a database-backed statistic."
            ),
            intent=decision.intent,
            warnings=["No LLM fallback was used because no grounding context was retrieved."],
            unsupported=True,
        )

    from baseball_rag.generation.prompt import build_explanation_prompt

    return _answer_with_grounded_chunks(
        question=question,
        intent=decision.intent,
        chunks=chunks,
        prompt_builder=build_explanation_prompt,
    )


def _answer_with_grounded_chunks(
    *,
    question: str,
    intent: str,
    chunks: list[RetrievedChunk],
    prompt_builder: PromptBuilder,
) -> StructuredAnswer:
    prompt = prompt_builder(question, chunks)
    sources = [_chroma_source(chunk) for chunk in chunks]
    try:
        from baseball_rag.generation.llm import make_request

        response = make_request(prompt, max_tokens=1500)
        return StructuredAnswer(answer=response.content, intent=intent, sources=sources)
    except ConnectionError:
        lines = ["(LM Studio not running - showing relevant documents instead):\n"]
        for chunk in chunks[:3]:
            lines.append(f"[{chunk.title}]\n{chunk.text}\n")
        return StructuredAnswer(
            answer="\n".join(lines),
            intent=intent,
            sources=sources,
            warnings=["LM Studio was unavailable, so retrieved context was shown directly."],
        )


def _resolve_time_period(tp: TimePeriod | None) -> tuple[int, int] | None:
    if tp is None:
        return None
    if tp.type == TimePeriodType.DECADE and isinstance(tp.value, int):
        start_year = 1900 + tp.value
        return start_year, start_year + 9
    if tp.type == TimePeriodType.RANGE and isinstance(tp.value, list) and len(tp.value) >= 2:
        return int(tp.value[0]), int(tp.value[-1])
    if tp.type == TimePeriodType.SINGLE and isinstance(tp.value, int):
        return tp.value, tp.value
    return None


def _duckdb_source(
    label: str,
    *,
    tables: list[str],
    rows: list[dict[str, Any]] | None = None,
) -> SourceRecord:
    return SourceRecord(
        type="duckdb",
        label=label,
        detail=f"Tables: {', '.join(tables)}. Dataset: local Hugging Face NeuML/baseballdata CSVs.",
        rows=rows or [],
        data_manifest=compact_data_manifest(),
    )


def _chroma_source(chunk: RetrievedChunk) -> SourceRecord:
    manifest = compact_data_manifest() if chunk.doc_kind == "generated_player_profile" else None
    return SourceRecord(
        type="chroma",
        label=chunk.title,
        detail=chunk.source,
        rows=[{"text": chunk.text}],
        score=chunk.score,
        data_manifest=manifest,
    )


def _rows_to_dicts(columns: list[str], rows: list[tuple]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


def _is_recoverable_chroma_index_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "dimension" in message or "embedding" in message


def _chroma_failure_answer(exc: Exception, *, intent: str) -> StructuredAnswer | None:
    if "NotFoundError" in type(exc).__name__ or "not found" in str(exc).lower():
        return StructuredAnswer(
            answer="No corpus indexed yet - run: uv run python -m baseball_rag.corpus.ingest",
            intent=intent,
            warnings=["Chroma collection was not available."],
            unsupported=True,
        )
    if _is_recoverable_chroma_index_error(exc):
        return StructuredAnswer(
            answer=(
                "The indexed corpus could not be queried. Rebuild it with: "
                "uv run python -m baseball_rag.corpus.ingest"
            ),
            intent=intent,
            warnings=[str(exc)],
            unsupported=True,
        )
    return None


def _resolve_retrieval_strategy(
    strategy: str | RetrievalStrategy | None,
    *,
    default: str,
) -> RetrievalStrategy:
    if strategy is None:
        return get_strategy(default, retrieve_fn=retrieve)
    if isinstance(strategy, str):
        return get_strategy(strategy, retrieve_fn=retrieve)
    return strategy


def _retrieve_static_explanation_chunks(question: str) -> list[RetrievedChunk]:
    if not query_asks_for_explanation(question):
        return []

    doc_ids = stat_definition_doc_ids_for_query(question)
    if doc_ids:
        chunks = get_chunks_by_ids(doc_ids)
        if chunks:
            return chunks
    return retrieve(question, top_k=3, where={"category": "stat_definition"})
