"""Deterministic stat-query answer assembly."""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from baseball_rag.db.queries import StatQueryPlan, StatQueryResult, execute_stat_query_plan
from baseball_rag.db.stat_registry import get_stat
from baseball_rag.outcomes import ambiguous_outcome, no_data_outcome
from baseball_rag.provenance import SourceRecord, StructuredAnswer, compact_data_manifest
from baseball_rag.routing.query_router import StatQueryCase, TimePeriod, TimePeriodType


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
    if _is_ambiguous_current_century_decade(decision.time_period, decision.raw_question):
        return ambiguous_outcome(
            answer=(
                f"The decade in '{decision.raw_question}' is ambiguous. "
                "Use a full decade like 1920s or 2020s."
            ),
            intent=decision.intent,
            sources=[_coverage_source()],
        )

    time_period = _resolve_time_period(decision.time_period, decision.raw_question)

    if decision.player_name:
        if _is_partial_player_name(decision.player_name):
            return ambiguous_outcome(
                answer=(
                    f"'{decision.player_name}' is ambiguous for a player-specific {stat} lookup. "
                    "Ask with a fuller player name."
                ),
                intent=decision.intent,
                sources=[_coverage_source()],
            )
        if time_period is not None and time_period[0] != time_period[1]:
            return ambiguous_outcome(
                answer=(
                    f"Player-specific {stat} lookups need one season, not "
                    f"{time_period[0]}-{time_period[1]}."
                ),
                intent=decision.intent,
                sources=[_coverage_source()],
            )
        year = time_period[0] if time_period is not None else None
        unsupported = _unsupported_for_single_year(stat, decision.intent, year)
        if unsupported is not None:
            return unsupported
        return StatQueryPlan(
            stat=stat,
            table=stat_def.table,
            kind="player",
            intent=decision.intent,
            position=decision.position,
            player_name=decision.player_name,
            year=year,
        )
    if time_period is not None:
        start_year, end_year = time_period
        unsupported = _unsupported_for_year_range(stat, decision.intent, start_year, end_year)
        if unsupported is not None:
            return unsupported
        return StatQueryPlan(
            stat=stat,
            table=stat_def.table,
            kind="leaderboard",
            intent=decision.intent,
            position=decision.position,
            start_year=start_year,
            end_year=end_year,
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
    if plan.kind == "player":
        return _answer_player_stat_result(plan, query_result)
    if plan.kind == "leaderboard":
        return _answer_leaderboard_result(plan, query_result)
    return _answer_career_leaderboard_result(plan, query_result)


def _answer_player_stat_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    if not query_result.rows:
        qualifier = f" in {plan.year}" if plan.year else ""
        return no_data_outcome(
            answer=(
                f"No {plan.stat} result found for {plan.player_name}{qualifier} "
                f"in the local Lahman-derived {plan.table} data."
            ),
            intent=plan.intent,
            sources=[_source_from_result(query_result)],
            warnings=["No fallback leaderboard was returned because the question named a player."],
        )

    result = query_result.rows[0]
    team_str = f" ({result['team']})" if result["team"] else ""
    return StructuredAnswer(
        answer=f"{result['name']}{team_str} ({result['year']}): {result['stat_value']} {plan.stat}",
        intent=plan.intent,
        sources=[_source_from_result(query_result)],
    )


def _answer_leaderboard_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    rows = query_result.rows
    if not rows:
        return no_data_outcome(
            answer=(
                f"No {plan.stat} results found for {plan.start_year}-{plan.end_year} "
                "in the local Lahman-derived data."
            ),
            intent=plan.intent,
            sources=[_source_from_result(query_result)],
            warnings=[
                "No fallback leaderboard was returned because the question specified a year."
            ],
        )

    lines = [f"Top {plan.stat} leaders ({plan.start_year}-{plan.end_year}):"]
    for i, row in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {row['name']}: {row['stat_value']} {plan.stat}")
    return StructuredAnswer(
        answer="\n".join(lines),
        intent=plan.intent,
        sources=[_source_from_result(query_result)],
    )


def _answer_career_leaderboard_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    rows = query_result.rows
    lines = [f"All-time career {plan.stat} leaders:"]
    for i, row in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {row['name']}: {row['stat_value']} {plan.stat}")
    return StructuredAnswer(
        answer="\n".join(lines),
        intent=plan.intent,
        sources=[_source_from_result(query_result)],
    )


def _source_from_result(query_result: Any) -> SourceRecord:
    return SourceRecord(
        type="duckdb",
        label=query_result.label,
        detail=(
            f"Tables: {', '.join(query_result.tables)}. "
            "Dataset: local Hugging Face NeuML/baseballdata CSVs."
        ),
        sql=query_result.executed_sql,
        rows=query_result.rows,
        data_manifest=compact_data_manifest(),
    )


def _resolve_time_period(
    tp: TimePeriod | None,
    raw_question: str = "",
) -> tuple[int, int] | None:
    if tp is None:
        return None
    if tp.type == TimePeriodType.DECADE and isinstance(tp.value, int):
        if tp.value >= 1000:
            start_year = tp.value
        else:
            start_year = _explicit_decade_start(raw_question, tp.value) or (1900 + tp.value)
        return start_year, start_year + 9
    if tp.type == TimePeriodType.RANGE and isinstance(tp.value, list) and len(tp.value) >= 2:
        return int(tp.value[0]), int(tp.value[-1])
    if tp.type == TimePeriodType.SINGLE and isinstance(tp.value, int):
        return tp.value, tp.value
    if tp.type == TimePeriodType.RELATIVE and isinstance(tp.value, dict):
        return _resolve_relative_time_period(tp.value)
    return None


def _resolve_relative_time_period(value: dict[str, Any]) -> tuple[int, int] | None:
    direction = value.get("direction")
    unit = value.get("unit")
    try:
        count = int(value.get("count", 1))
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None

    current_year = _current_year()
    if direction == "past" and unit in {"year", "season"}:
        end_year = current_year - 1
        start_year = end_year if count == 1 else current_year - count
        return start_year, end_year
    if direction == "future" and unit in {"year", "season"}:
        start_year = current_year + 1
        end_year = start_year if count == 1 else current_year + count
        return start_year, end_year
    return None


def _is_ambiguous_current_century_decade(tp: TimePeriod | None, raw_question: str) -> bool:
    if tp is None or tp.type != TimePeriodType.DECADE or not isinstance(tp.value, int):
        return False
    if tp.value >= 1000 or _explicit_decade_start(raw_question, tp.value) is not None:
        return False
    current_decade = (_current_year() % 100) // 10 * 10
    return 0 <= tp.value <= current_decade


def _explicit_decade_start(raw_question: str, value: int) -> int | None:
    match = re.search(r"\b((?:18|19|20)\d0)s\b", raw_question, re.IGNORECASE)
    if match is None:
        return None
    start_year = int(match.group(1))
    return start_year if start_year % 100 == value else None


def _current_year() -> int:
    configured = os.environ.get("BASEBALL_RAG_CURRENT_YEAR")
    if configured is not None:
        try:
            return int(configured)
        except ValueError:
            pass
    return date.today().year


def _is_partial_player_name(player_name: str | None) -> bool:
    if player_name is None:
        return False
    parts = [p for p in player_name.strip().split() if not _is_suffix(p)]
    return len(parts) == 1


def _is_suffix(value: str) -> bool:
    return value.lower().rstrip(".") in {"jr", "sr", "ii", "iii", "iv"}


def _unsupported_for_single_year(
    stat: str,
    intent: str,
    year: int | None,
) -> StructuredAnswer | None:
    if year is None:
        return None
    return _unsupported_for_year_range(stat, intent, year, year)


def _unsupported_for_year_range(
    stat: str,
    intent: str,
    start_year: int,
    end_year: int,
) -> StructuredAnswer | None:
    coverage = _structured_stat_year_coverage()
    min_year = coverage.get("min")
    max_year = coverage.get("max")

    if start_year > end_year:
        return ambiguous_outcome(
            answer=(
                f"The requested {stat} range {start_year}-{end_year} is reversed. "
                "Ask with the earlier year first."
            ),
            intent=intent,
            sources=[_coverage_source()],
        )

    if (
        isinstance(min_year, int)
        and isinstance(max_year, int)
        and (start_year < min_year or end_year > max_year)
    ):
        return no_data_outcome(
            answer=(
                f"The local structured stat data covers {min_year}-{max_year}; "
                f"the requested {stat} range was {start_year}-{end_year}."
            ),
            intent=intent,
            sources=[_coverage_source()],
        )

    return None


def _structured_stat_year_coverage() -> dict[str, Any]:
    return compact_data_manifest().get("coverage", {}).get("structured_stat_years", {})


def _coverage_source() -> SourceRecord:
    return SourceRecord(
        type="system",
        label="Structured stat year coverage",
        detail="Coverage comes from data/manifest.json for local DuckDB-backed stats.",
        data_manifest=compact_data_manifest(),
    )
