"""Deterministic stat-query answer assembly."""

from __future__ import annotations

from typing import Any

from baseball_rag.db import execute_stat_query
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.provenance import SourceRecord, StructuredAnswer, compact_data_manifest
from baseball_rag.routing.query_router import TimePeriod, TimePeriodType


def answer_stat_query(decision: Any) -> StructuredAnswer:
    """Answer a routed deterministic stat query with provenance-ready SQL."""
    stat = decision.stat or "HR"
    time_period = _resolve_time_period(decision.time_period)

    if decision.player_name:
        return _answer_player_stat(stat, decision)
    if time_period is not None:
        start_year, end_year = time_period
        return _answer_leaderboard(
            stat,
            decision,
            start_year=start_year,
            end_year=end_year,
        )
    return _answer_career_leaderboard(stat, decision)


def _answer_player_stat(stat: str, decision: Any) -> StructuredAnswer:
    query_result = execute_stat_query(
        stat,
        player_name=decision.player_name,
        year=decision.year,
        position=decision.position,
        conn=get_duckdb(),
    )
    if not query_result.rows:
        qualifier = f" in {decision.year}" if decision.year else ""
        return StructuredAnswer(
            answer=(
                f"No {stat} result found for {decision.player_name}{qualifier} "
                "in the local Lahman-derived batting data."
            ),
            intent=decision.intent,
            sources=[_source_from_result(query_result)],
            warnings=["No fallback leaderboard was returned because the question named a player."],
            unsupported=True,
            unsupported_reason="no_data",
        )

    result = query_result.rows[0]
    team_str = f" ({result['team']})" if result["team"] else ""
    return StructuredAnswer(
        answer=f"{result['name']}{team_str} ({result['year']}): {result['stat_value']} {stat}",
        intent=decision.intent,
        sources=[_source_from_result(query_result)],
    )


def _answer_leaderboard(
    stat: str,
    decision: Any,
    *,
    start_year: int,
    end_year: int,
) -> StructuredAnswer:
    query_result = execute_stat_query(
        stat,
        start_year=start_year,
        end_year=end_year,
        position=decision.position,
    )
    rows = query_result.rows
    lines = [f"Top {stat} leaders ({start_year}-{end_year}):"]
    for i, row in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {row['name']}: {row['stat_value']} {stat}")
    return StructuredAnswer(
        answer="\n".join(lines),
        intent=decision.intent,
        sources=[_source_from_result(query_result)],
    )


def _answer_career_leaderboard(stat: str, decision: Any) -> StructuredAnswer:
    query_result = execute_stat_query(stat, position=decision.position)
    rows = query_result.rows
    lines = [f"All-time career {stat} leaders:"]
    for i, row in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {row['name']}: {row['stat_value']} {stat}")
    return StructuredAnswer(
        answer="\n".join(lines),
        intent=decision.intent,
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
