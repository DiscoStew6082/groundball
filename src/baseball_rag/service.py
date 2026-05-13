"""Shared grounded answer service used by CLI and API."""

from __future__ import annotations

import logging
from typing import Any, Callable

from baseball_rag.conversation import resolve_followup
from baseball_rag.corpus.lifecycle import is_generated_player_profile_doc_kind
from baseball_rag.db import (
    init_db,
)
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.outcomes import (
    ambiguous_outcome,
    llm_unavailable_outcome,
    missing_corpus_outcome,
    retrieval_failed_outcome,
    unsupported_outcome,
)
from baseball_rag.provenance import (
    ReviewReason,
    SourceRecord,
    StructuredAnswer,
    UnsupportedReason,
    compact_data_manifest,
)
from baseball_rag.request_dispatch import AnswerHandlers, RequestAnswerDispatcher
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
    conversation: list[dict[str, Any]] | None = None,
) -> StructuredAnswer:
    """Answer a question with explicit grounding metadata."""
    dispatcher = RequestAnswerDispatcher(
        initialize=init_db,
        resolve_followup=resolve_followup,
        route_question=route,
        handlers=AnswerHandlers(
            stat_query=answer_stat_query,
            player_biography=_answer_player_biography,
            freeform_query=_answer_freeform,
            general_explanation=_answer_general,
        ),
    )
    return dispatcher.answer(
        question,
        retrieval_strategy=retrieval_strategy,
        conversation=conversation,
    )


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
    resolved_player_id: str | None = None
    if decision.player_name:
        from baseball_rag.corpus.player_bios import resolve_player_by_name

        resolution = resolve_player_by_name(decision.player_name, get_duckdb())
        if resolution.ambiguous:
            choices = ", ".join(
                f"{c.full_name} ({c.debut or '?'}-{c.final_game or '?'})"
                for c in resolution.candidates[:5]
            )
            return ambiguous_outcome(
                answer=(
                    f"'{decision.player_name}' is ambiguous in the local player registry. "
                    f"Try a fuller name. Possible matches: {choices}."
                ),
                intent=decision.intent,
                warnings=["No biography was generated because the player name was ambiguous."],
            )
        resolved_player_id = resolution.player_id

    try:
        chunks = retrieve_grounded_chunks(
            RetrievalRequest.from_routed_case(
                decision,
                top_k=3,
                retrieval_strategy=retrieval_strategy,
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
        return _answer_player_biography_from_llm_memory(
            question=decision.raw_question,
            intent=decision.intent,
            player_name=decision.player_name or question,
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
        review_reason: ReviewReason = "ambiguous" if reason == "ambiguous" else "unsupported"
        return unsupported_outcome(
            answer=(
                f"No results found for '{decision.raw_question}'.\n"
                "Try rephrasing with a specific team, player, stat, or year."
            ),
            intent=decision.intent,
            sources=[source],
            reason=reason,
            review_reason=review_reason,
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
            RetrievalRequest.from_routed_case(
                decision,
                question=question,
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
        return missing_corpus_outcome(
            answer=(
                "No relevant grounded documents were found for that query. "
                "Try asking about an indexed stat definition, indexed player biography, "
                "or a database-backed statistic."
            ),
            intent=decision.intent,
            warnings=["No LLM fallback was used because no grounding context was retrieved."],
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


def _answer_player_biography_from_llm_memory(
    *,
    question: str,
    intent: str,
    player_name: str,
) -> StructuredAnswer:
    """Answer a missing corpus biography from LLM memory with explicit provenance."""
    from baseball_rag.generation.llm import make_request
    from baseball_rag.generation.prompt import build_open_prompt

    try:
        response = make_request(build_open_prompt(question), max_tokens=700)
    except ConnectionError:
        return llm_unavailable_outcome(
            answer=(
                f"No player biography found for '{player_name}' in the local corpus, "
                "and LM Studio was unavailable for an LLM-memory fallback."
            ),
            intent=intent,
            warnings=[
                "No local corpus biography was found, and LM Studio was unavailable.",
            ],
        )

    note = "Note: this answer came from LLM memory, not the local baseball corpus."
    return StructuredAnswer(
        answer=f"{response.content}\n\n{note}",
        intent=intent,
        sources=[
            SourceRecord(
                type="system",
                label="LLM memory",
                detail=(
                    "No local corpus biography was retrieved; the local LLM answered from "
                    "its model memory."
                ),
            )
        ],
        warnings=["No local corpus biography was found; the answer came from LLM memory."],
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
    manifest = (
        compact_data_manifest() if is_generated_player_profile_doc_kind(chunk.doc_kind) else None
    )
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
        return missing_corpus_outcome(
            answer="No corpus indexed yet - run: uv run python -m baseball_rag.corpus.ingest",
            intent=intent,
            warnings=["Chroma collection was not available."],
        )
    if _is_recoverable_chroma_index_error(exc):
        return retrieval_failed_outcome(
            answer=(
                "The indexed corpus could not be queried. Rebuild it with: "
                "uv run python -m baseball_rag.corpus.ingest"
            ),
            intent=intent,
            warning=str(exc),
        )
    return None
