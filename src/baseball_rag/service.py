"""Shared answer service used by CLI and API."""

from __future__ import annotations

import json
import logging
from typing import Any

from baseball_rag import player_biography
from baseball_rag.answer_mode import AnswerMode, validate_answer_mode
from baseball_rag.conversation import resolve_followup
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.general_explanation import GeneralExplanationPolicy
from baseball_rag.outcomes import unsupported_outcome
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
from baseball_rag.routing import (
    GeneralExplanationCase,
    GroundedDatabaseQuestionCase,
    PlayerBiographyCase,
    route,
)
from baseball_rag.stat_query import answer_stat_query

logger = logging.getLogger(__name__)


def answer(
    question: str,
    *,
    conversation: list[dict[str, Any]] | None = None,
    answer_mode: str = "stats_only",
) -> StructuredAnswer:
    """Answer a question with explicit provenance metadata."""
    validated_answer_mode: AnswerMode = validate_answer_mode(answer_mode)
    dispatcher = RequestAnswerDispatcher(
        resolve_followup=resolve_followup,
        route_question=route,
        handlers=AnswerHandlers(
            stat_query=answer_stat_query,
            player_biography=_answer_player_biography,
            grounded_database_question=_answer_grounded_database_question,
            general_explanation=_answer_general,
        ),
    )
    result = dispatcher.answer(question, conversation=conversation)
    if validated_answer_mode == "llm_flavored":
        _apply_llm_flavor(question, result)
    result.metadata["answer_mode"] = validated_answer_mode
    return result


def render_text(result: StructuredAnswer) -> str:
    """Render a structured answer for terminal/chat use."""
    lines = [result.answer]
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _answer_player_biography(question: str, decision: PlayerBiographyCase) -> StructuredAnswer:
    from baseball_rag.generation.llm import make_request

    return PlayerBiographyCaseAnswerer(
        conn_factory=get_duckdb,
        make_request=make_request,
        verify_claims_consensus=verify_player_stat_claims_consensus,
        extract_claims=player_biography.extract_supplied_stat_claims,
        request_biography=player_biography.request_biography_json,
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


def _answer_grounded_database_question(
    _question: str,
    decision: GroundedDatabaseQuestionCase,
) -> StructuredAnswer:
    from baseball_rag.db.grounded_database_runtime import format_result, query
    from baseball_rag.generation.llm import make_request

    conn = get_duckdb()
    query_result = query(
        decision.raw_question,
        conn,
        year=_grounded_database_single_season_year(decision),
        request_fn=make_request,
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
        reason = _grounded_database_unsupported_reason(query_result)
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
    formatted_answer = format_result(query_result, decision.raw_question)
    return StructuredAnswer(
        answer=formatted_answer,
        intent=decision.intent,
        sources=[source],
        warnings=warnings,
    )


def _grounded_database_single_season_year(
    decision: GroundedDatabaseQuestionCase,
) -> int | None:
    if decision.time_period is None:
        return None

    from baseball_rag.query_scope import QueryScope, resolve_query_scope

    scope = resolve_query_scope(
        decision.time_period,
        raw_question=decision.raw_question,
        stat="grounded database question",
        intent=decision.intent,
        validate_coverage=False,
    )
    if isinstance(scope, QueryScope) and scope.is_single_season:
        return scope.start_year
    return None


def _answer_general(question: str, decision: GeneralExplanationCase) -> StructuredAnswer:
    from baseball_rag.generation.llm import make_request

    return GeneralExplanationPolicy(make_request=make_request).answer(decision)


def _answer_local_stat_definition(question: str) -> StructuredAnswer | None:
    return GeneralExplanationPolicy()._answer_local_stat_definition(question)


def _markdown_body(text: str) -> str:
    from baseball_rag.general_explanation import _markdown_body as markdown_body

    return markdown_body(text)


def _apply_llm_flavor(question: str, result: StructuredAnswer) -> None:
    if result.unsupported:
        return
    if result.intent not in {"stat_query", "grounded_database_question"}:
        return
    source = _primary_duckdb_source(result)
    if source is None:
        return
    prompt_question = str(result.metadata.get("context_question") or question)
    result.answer = _llm_flavored_grounded_database_answer(
        question=prompt_question,
        formatted_answer=result.answer,
        source=source,
    )


def _primary_duckdb_source(result: StructuredAnswer) -> SourceRecord | None:
    for source in result.sources:
        if source.type == "duckdb":
            return source
    return None


def _llm_flavored_grounded_database_answer(
    *,
    question: str,
    formatted_answer: str,
    source: SourceRecord,
) -> str:
    from baseball_rag.generation.llm import LLMError, make_request

    try:
        response = make_request(
            _grounded_database_flavor_prompt(
                question=question,
                formatted_answer=formatted_answer,
                source=source,
            ),
            max_tokens=700,
            temperature=0.2,
        )
    except LLMError:
        return (
            f"{formatted_answer}\n\n"
            "Note: LLM unavailable, so this response is the verified DuckDB stats only."
        )
    return response.content.strip()


def _grounded_database_flavor_prompt(
    *,
    question: str,
    formatted_answer: str,
    source: SourceRecord,
) -> tuple[str, str]:
    system_prompt = (
        "Answer the baseball question using only the verified DuckDB stats provided. "
        "Do not add outside numbers. If you mention a number, it must come from the "
        "verified stats."
    )
    context = {
        "question": question,
        "formatted_stats": formatted_answer,
        "duckdb_source": {
            "label": source.label,
            "detail": source.detail,
            "sql": source.sql,
            "columns": source.columns,
            "rows": source.rows,
        },
    }
    user_prompt = (
        "Use this grounded database result to answer in natural language:\n"
        f"{json.dumps(context, indent=2, default=str)}"
    )
    return system_prompt, user_prompt


def _rows_to_dicts(columns: list[str], rows: list[tuple]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


def _grounded_database_unsupported_reason(query_result: Any) -> UnsupportedReason:
    reason = query_result.unsupported_reason
    if reason == "ambiguous":
        return "ambiguous"
    if reason == "unsupported":
        return "unsupported"
    if "unsupported_reason" not in query_result.columns:
        return "no_data"
    return "unsupported"
