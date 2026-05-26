"""Deterministic stat-query answer assembly."""

from __future__ import annotations

from dataclasses import dataclass

from baseball_rag.db.answer_assembly import answer_stat_result
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.player_identity import resolve_player_by_name
from baseball_rag.db.queries import StatQueryPlan, StatQueryResult, execute_stat_query_plan
from baseball_rag.db.stat_registry import get_stat
from baseball_rag.outcomes import ambiguous_outcome, no_data_outcome
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.query_scope import QueryScope, coverage_source, resolve_query_scope_outcome
from baseball_rag.routing.query_router import StatQueryCase


@dataclass(frozen=True)
class StatQueryPlanningOutcome:
    """Explicit result of deterministic stat-query planning."""

    plan: StatQueryPlan | None = None
    answer: StructuredAnswer | None = None

    def __post_init__(self) -> None:
        if (self.plan is None) == (self.answer is None):
            raise ValueError("stat query planning outcome requires exactly one plan or answer")


def answer_stat_query(decision: StatQueryCase) -> StructuredAnswer:
    """Answer a routed deterministic stat query with provenance-ready SQL."""
    planned = plan_stat_query(decision)
    if planned.answer is not None:
        return planned.answer
    assert planned.plan is not None
    query_result = execute_stat_query_plan(planned.plan)
    return answer_stat_query_result(planned.plan, query_result)


def plan_stat_query(decision: StatQueryCase) -> StatQueryPlanningOutcome:
    """Convert a routed stat case into a validated deterministic query plan."""
    stat_def = get_stat(decision.stat)
    stat = stat_def.canonical

    if decision.player_name:
        conn = get_duckdb()
        player_resolution = resolve_player_by_name(decision.player_name, conn)
        if player_resolution.ambiguous or _is_partial_player_name(decision.player_name):
            return StatQueryPlanningOutcome(
                answer=ambiguous_outcome(
                    answer=(
                        f"'{decision.player_name}' is ambiguous for a player-specific {stat} "
                        "lookup. Ask with a fuller player name."
                    ),
                    intent=decision.intent,
                    sources=[coverage_source()],
                ),
            )
        if _has_explicit_suffix(decision.player_name) and player_resolution.player_id is None:
            return StatQueryPlanningOutcome(
                answer=no_data_outcome(
                    answer=(
                        f"No player named '{decision.player_name}' was found in the "
                        "local DuckDB player registry."
                    ),
                    intent=decision.intent,
                    sources=[coverage_source()],
                    warnings=[
                        "No stat lookup was run because the explicit player suffix did not resolve."
                    ],
                )
            )
        scope_outcome = resolve_query_scope_outcome(
            decision.time_period,
            raw_question=decision.raw_question,
            stat=stat,
            intent=decision.intent,
            require_single_season=True,
            single_season_subject=f"Player-specific {stat} lookups",
        )
        if scope_outcome.answer is not None:
            return StatQueryPlanningOutcome(answer=scope_outcome.answer)
        year = scope_outcome.scope.start_year if scope_outcome.scope is not None else None
        return StatQueryPlanningOutcome(
            plan=StatQueryPlan(
                stat=stat,
                table=stat_def.table,
                kind="player",
                intent=decision.intent,
                position=decision.position,
                player_name=decision.player_name,
                player_id=player_resolution.player_id,
                resolved_player_name=(
                    player_resolution.player.full_name
                    if player_resolution.player is not None
                    else None
                ),
                year=year,
            ),
        )
    scope_outcome = resolve_query_scope_outcome(
        decision.time_period,
        raw_question=decision.raw_question,
        stat=stat,
        intent=decision.intent,
    )
    if scope_outcome.answer is not None:
        return StatQueryPlanningOutcome(answer=scope_outcome.answer)
    if isinstance(scope_outcome.scope, QueryScope):
        return StatQueryPlanningOutcome(
            plan=StatQueryPlan(
                stat=stat,
                table=stat_def.table,
                kind="leaderboard",
                intent=decision.intent,
                position=decision.position,
                start_year=scope_outcome.scope.start_year,
                end_year=scope_outcome.scope.end_year,
            )
        )
    return StatQueryPlanningOutcome(
        plan=StatQueryPlan(
            stat=stat,
            table=stat_def.table,
            kind="career",
            intent=decision.intent,
            position=decision.position,
        )
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


def _has_explicit_suffix(player_name: str | None) -> bool:
    if player_name is None:
        return False
    parts = player_name.strip().split()
    return bool(parts and _is_suffix(parts[-1]))


def _is_suffix(value: str) -> bool:
    return value.lower().rstrip(".") in {"jr", "sr", "ii", "iii", "iv"}
