"""Deterministic stat-query answer assembly."""

from __future__ import annotations

from baseball_rag.db.answer_assembly import answer_stat_result
from baseball_rag.db.queries import StatQueryPlan, StatQueryResult, execute_stat_query_plan
from baseball_rag.db.stat_registry import get_stat
from baseball_rag.outcomes import ambiguous_outcome
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.query_scope import QueryScope, coverage_source, resolve_query_scope
from baseball_rag.routing.query_router import StatQueryCase


def answer_stat_query(decision: StatQueryCase) -> StructuredAnswer:
    """Answer a routed deterministic stat query with provenance-ready SQL."""
    planned = plan_stat_query(decision)
    if isinstance(planned, StructuredAnswer):
        return planned
    query_result = execute_stat_query_plan(planned)
    return answer_stat_query_result(planned, query_result)


def plan_stat_query(decision: StatQueryCase) -> StatQueryPlan | StructuredAnswer:
    """Convert a routed stat case into a validated deterministic query plan."""
    stat_def = get_stat(decision.stat)
    stat = stat_def.canonical

    if decision.player_name:
        if _is_partial_player_name(decision.player_name):
            return ambiguous_outcome(
                answer=(
                    f"'{decision.player_name}' is ambiguous for a player-specific {stat} lookup. "
                    "Ask with a fuller player name."
                ),
                intent=decision.intent,
                sources=[coverage_source()],
            )
        scope = resolve_query_scope(
            decision.time_period,
            raw_question=decision.raw_question,
            stat=stat,
            intent=decision.intent,
            validate_coverage=False,
        )
        if isinstance(scope, StructuredAnswer):
            return scope
        if isinstance(scope, QueryScope) and not scope.is_single_season:
            return ambiguous_outcome(
                answer=(
                    f"Player-specific {stat} lookups need one season, not "
                    f"{scope.start_year}-{scope.end_year}."
                ),
                intent=decision.intent,
                sources=[coverage_source()],
            )
        scope = resolve_query_scope(
            decision.time_period,
            raw_question=decision.raw_question,
            stat=stat,
            intent=decision.intent,
        )
        if isinstance(scope, StructuredAnswer):
            return scope
        year = scope.start_year if isinstance(scope, QueryScope) else None
        return StatQueryPlan(
            stat=stat,
            table=stat_def.table,
            kind="player",
            intent=decision.intent,
            position=decision.position,
            player_name=decision.player_name,
            year=year,
        )
    scope = resolve_query_scope(
        decision.time_period,
        raw_question=decision.raw_question,
        stat=stat,
        intent=decision.intent,
    )
    if isinstance(scope, StructuredAnswer):
        return scope
    if isinstance(scope, QueryScope):
        return StatQueryPlan(
            stat=stat,
            table=stat_def.table,
            kind="leaderboard",
            intent=decision.intent,
            position=decision.position,
            start_year=scope.start_year,
            end_year=scope.end_year,
        )
    return StatQueryPlan(
        stat=stat,
        table=stat_def.table,
        kind="career",
        intent=decision.intent,
        position=decision.position,
    )


def answer_stat_query_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    """Build the public answer and provenance from an executed stat result."""
    return answer_stat_result(plan, query_result)


def _is_partial_player_name(player_name: str | None) -> bool:
    if player_name is None:
        return False
    parts = [p for p in player_name.strip().split() if not _is_suffix(p)]
    return len(parts) == 1


def _is_suffix(value: str) -> bool:
    return value.lower().rstrip(".") in {"jr", "sr", "ii", "iii", "iv"}
