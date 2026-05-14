"""Shared answer service used by CLI and API."""

from __future__ import annotations

import logging
from typing import Any

from baseball_rag import player_biography as _player_biography
from baseball_rag.conversation import resolve_followup
from baseball_rag.db import init_db
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.outcomes import llm_unavailable_outcome, unsupported_outcome
from baseball_rag.player_biography import (
    PlayerBiographyCaseAnswerer,
    duckdb_source,
    verify_player_stat_claims_consensus,
)
from baseball_rag.provenance import (
    ReviewReason,
    SourceRecord,
    StructuredAnswer,
    UnsupportedReason,
    compact_data_manifest,
)
from baseball_rag.request_dispatch import AnswerHandlers, RequestAnswerDispatcher
from baseball_rag.routing import route
from baseball_rag.stat_query import answer_stat_query

logger = logging.getLogger(__name__)

_build_biography_json_repair_prompt = _player_biography.build_biography_json_repair_prompt
_extract_supplied_stat_claims = _player_biography.extract_supplied_stat_claims
_is_biography_json_contract = _player_biography.is_biography_json_contract
_loads_json_object = _player_biography.loads_json_object
_parse_biography_json = _player_biography.parse_biography_json
_request_biography_json = _player_biography.request_biography_json


def answer(
    question: str,
    *,
    conversation: list[dict[str, Any]] | None = None,
) -> StructuredAnswer:
    """Answer a question with explicit provenance metadata."""
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
    return dispatcher.answer(question, conversation=conversation)


def render_text(result: StructuredAnswer) -> str:
    """Render a structured answer for terminal/chat use."""
    lines = [result.answer]
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _answer_player_biography(question: str, decision: Any) -> StructuredAnswer:
    try:
        from baseball_rag.generation.llm import make_request
    except ImportError:  # pragma: no cover
        make_request = None
    return PlayerBiographyCaseAnswerer(
        conn_factory=get_duckdb,
        make_request=make_request,
        verify_claims_consensus=verify_player_stat_claims_consensus,
        extract_claims=_extract_supplied_stat_claims,
        request_biography=_request_biography_json,
    ).answer(question, decision)


def _duckdb_source(
    label: str,
    *,
    tables: list[str],
    rows: list[dict[str, Any]] | None = None,
    sql: str | None = None,
    detail: str | None = None,
    data_manifest: dict[str, Any] | None = None,
) -> SourceRecord:
    return duckdb_source(
        label,
        tables=tables,
        rows=rows,
        sql=sql,
        detail=detail,
        data_manifest=data_manifest,
    )


def _answer_freeform(question: str, decision: Any) -> StructuredAnswer:
    from baseball_rag.db.freeform import format_result, query

    conn = get_duckdb()
    query_result = query(
        decision.raw_question,
        conn,
        year=_freeform_single_season_year(decision),
    )
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


def _freeform_single_season_year(decision: Any) -> int | None:
    time_period = getattr(decision, "time_period", None)
    if time_period is None:
        return getattr(decision, "year", None)

    from baseball_rag.query_scope import QueryScope, resolve_query_scope

    scope = resolve_query_scope(
        time_period,
        raw_question=getattr(decision, "raw_question", ""),
        stat="freeform",
        intent=getattr(decision, "intent", "freeform_query"),
        validate_coverage=False,
    )
    if isinstance(scope, QueryScope) and scope.is_single_season:
        return scope.start_year
    return None


def _answer_general(question: str, decision: Any) -> StructuredAnswer:
    from baseball_rag.generation.prompt import build_open_prompt

    try:
        from baseball_rag.generation.llm import LLMError, make_request

        response = make_request(
            build_open_prompt(decision.raw_question or question),
            max_tokens=700,
        )
    except (ConnectionError, TimeoutError, LLMError) as exc:
        return llm_unavailable_outcome(
            answer=(
                "LM Studio was unavailable, so no open explanation was generated. "
                "General explanation questions require the local LLM."
            ),
            intent=decision.intent,
            warnings=[str(exc)],
        )
    return StructuredAnswer(answer=response.content, intent=decision.intent)


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
