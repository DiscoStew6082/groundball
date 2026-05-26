"""Shared answer service used by CLI and API."""

from __future__ import annotations

import logging
from typing import Any

from baseball_rag import biography_contract, player_biography
from baseball_rag.answer_mode import AnswerMode, validate_answer_mode
from baseball_rag.conversation import resolve_followup
from baseball_rag.db.answer_assembly import answer_grounded_database_result
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.general_explanation import GeneralExplanationPolicy
from baseball_rag.llm_narration_guard import apply_llm_flavored_narration
from baseball_rag.player_biography import (
    PlayerBiographyCaseAnswerer,
    duckdb_source,
    verify_player_stat_claims_consensus,
)
from baseball_rag.provenance import SourceRecord, StructuredAnswer
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
        request_biography=biography_contract.request_biography_json,
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
    from baseball_rag.db.grounded_database_runtime import query
    from baseball_rag.generation.llm import make_request

    conn = get_duckdb()
    query_result = query(
        decision.raw_question,
        conn,
        year=_grounded_database_single_season_year(decision),
        request_fn=make_request,
    )
    return answer_grounded_database_result(
        raw_question=decision.raw_question,
        intent=decision.intent,
        query_result=query_result,
    )


def _grounded_database_single_season_year(
    decision: GroundedDatabaseQuestionCase,
) -> int | None:
    if decision.time_period is None:
        return None

    from baseball_rag.query_scope import resolve_query_scope_outcome

    outcome = resolve_query_scope_outcome(
        decision.time_period,
        raw_question=decision.raw_question,
        stat="grounded database question",
        intent=decision.intent,
        validate_coverage=False,
    )
    if outcome.scope is not None and outcome.scope.is_single_season:
        return outcome.scope.start_year
    return None


def _answer_general(question: str, decision: GeneralExplanationCase) -> StructuredAnswer:
    from baseball_rag.generation.llm import make_request

    return GeneralExplanationPolicy(make_request=make_request).answer(decision)


def _apply_llm_flavor(question: str, result: StructuredAnswer) -> None:
    apply_llm_flavored_narration(question, result)
