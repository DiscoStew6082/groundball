"""Shared grounded answer service used by CLI and API."""

from __future__ import annotations

import logging
from typing import Any, Callable

from baseball_rag.db import (
    init_db,
)
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.provenance import (
    SourceRecord,
    StructuredAnswer,
    UnsupportedReason,
    compact_data_manifest,
)
from baseball_rag.retrieval.chroma_store import RetrievedChunk
from baseball_rag.retrieval.decision import RetrievalRequest, retrieve_grounded_chunks
from baseball_rag.retrieval.strategies import RetrievalStrategy
from baseball_rag.routing import route
from baseball_rag.stat_query import answer_stat_query

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
        return answer_stat_query(decision)
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
                unsupported_reason="ambiguous",
                review_reason="ambiguous",
            )
        resolved_player_id = resolution.player_id

    try:
        chunks = retrieve_grounded_chunks(
            RetrievalRequest(
                question=decision.raw_question,
                intent=decision.intent,
                top_k=3,
                retrieval_strategy=retrieval_strategy,
                player_name=player_name,
                player_id=resolved_player_id,
            )
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
            unsupported_reason="missing_corpus",
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
    query_result = query(decision.raw_question, conn, year=getattr(decision, "year", None))
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
        reason = _freeform_unsupported_reason(query_result)
        return StructuredAnswer(
            answer=(
                f"No results found for '{decision.raw_question}'.\n"
                "Try rephrasing with a specific team, player, stat, or year."
            ),
            intent=decision.intent,
            sources=[source],
            unsupported=True,
            unsupported_reason=reason,
            review_reason="ambiguous" if reason == "ambiguous" else "unsupported",
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
        chunks = retrieve_grounded_chunks(
            RetrievalRequest(
                question=question,
                intent=decision.intent,
                top_k=3,
                retrieval_strategy=retrieval_strategy,
            )
        )
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
            unsupported_reason="missing_corpus",
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


def _duckdb_source(
    label: str,
    *,
    tables: list[str],
    rows: list[dict[str, Any]] | None = None,
    sql: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        type="duckdb",
        label=label,
        detail=f"Tables: {', '.join(tables)}. Dataset: local Hugging Face NeuML/baseballdata CSVs.",
        sql=sql,
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


def _freeform_unsupported_reason(query_result: Any) -> UnsupportedReason:
    reason = query_result.unsupported_reason
    if reason == "ambiguous":
        return "ambiguous"
    if reason == "unsupported":
        return "unsupported"
    if "unsupported_reason" not in query_result.columns:
        return "no_data"
    return "unsupported"


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
            unsupported_reason="missing_corpus",
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
            unsupported_reason="retrieval_failed",
        )
    return None
