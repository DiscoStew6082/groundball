"""Deterministic stat-query answer assembly."""

from __future__ import annotations

import os
import re
from datetime import date
from typing import Any

from baseball_rag.db import execute_stat_query
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.provenance import SourceRecord, StructuredAnswer, compact_data_manifest
from baseball_rag.routing.query_router import StatQueryCase, TimePeriod, TimePeriodType


def answer_stat_query(decision: StatQueryCase) -> StructuredAnswer:
    """Answer a routed deterministic stat query with provenance-ready SQL."""
    stat = decision.stat
    if _is_ambiguous_current_century_decade(decision.time_period, decision.raw_question):
        return StructuredAnswer(
            answer=(
                f"The decade in '{decision.raw_question}' is ambiguous. "
                "Use a full decade like 1920s or 2020s."
            ),
            intent=decision.intent,
            sources=[_coverage_source()],
            unsupported=True,
            unsupported_reason="ambiguous",
            review_reason="ambiguous",
        )

    time_period = _resolve_time_period(decision.time_period, decision.raw_question)

    if decision.player_name:
        if time_period is not None and time_period[0] != time_period[1]:
            return StructuredAnswer(
                answer=(
                    f"Player-specific {stat} lookups need one season, not "
                    f"{time_period[0]}-{time_period[1]}."
                ),
                intent=decision.intent,
                sources=[_coverage_source()],
                unsupported=True,
                unsupported_reason="ambiguous",
                review_reason="ambiguous",
            )
        resolved_year = time_period[0] if time_period is not None else None
        return _answer_player_stat(stat, decision, resolved_year=resolved_year)
    if time_period is not None:
        start_year, end_year = time_period
        return _answer_leaderboard(
            stat,
            decision,
            start_year=start_year,
            end_year=end_year,
        )
    return _answer_career_leaderboard(stat, decision)


def _answer_player_stat(
    stat: str,
    decision: Any,
    *,
    resolved_year: int | None = None,
) -> StructuredAnswer:
    if _is_partial_player_name(decision.player_name):
        return StructuredAnswer(
            answer=(
                f"'{decision.player_name}' is ambiguous for a player-specific {stat} lookup. "
                "Ask with a fuller player name."
            ),
            intent=decision.intent,
            sources=[_coverage_source()],
            unsupported=True,
            unsupported_reason="ambiguous",
            review_reason="ambiguous",
        )

    year = resolved_year if resolved_year is not None else decision.year
    if year is not None:
        unsupported = _unsupported_for_year_range(
            stat,
            decision.intent,
            year,
            year,
        )
        if unsupported is not None:
            return unsupported

    query_result = execute_stat_query(
        stat,
        player_name=decision.player_name,
        year=year,
        position=decision.position,
        conn=get_duckdb(),
    )
    if not query_result.rows:
        qualifier = f" in {year}" if year else ""
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
    unsupported = _unsupported_for_year_range(stat, decision.intent, start_year, end_year)
    if unsupported is not None:
        return unsupported

    query_result = execute_stat_query(
        stat,
        start_year=start_year,
        end_year=end_year,
        position=decision.position,
    )
    rows = query_result.rows
    if not rows:
        return StructuredAnswer(
            answer=(
                f"No {stat} results found for {start_year}-{end_year} "
                "in the local Lahman-derived data."
            ),
            intent=decision.intent,
            sources=[_source_from_result(query_result)],
            warnings=[
                "No fallback leaderboard was returned because the question specified a year."
            ],
            unsupported=True,
            unsupported_reason="no_data",
        )

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
        return StructuredAnswer(
            answer=(
                f"The requested {stat} range {start_year}-{end_year} is reversed. "
                "Ask with the earlier year first."
            ),
            intent=intent,
            sources=[_coverage_source()],
            unsupported=True,
            unsupported_reason="ambiguous",
            review_reason="ambiguous",
        )

    if (
        isinstance(min_year, int)
        and isinstance(max_year, int)
        and (start_year < min_year or end_year > max_year)
    ):
        return StructuredAnswer(
            answer=(
                f"The local structured stat data covers {min_year}-{max_year}; "
                f"the requested {stat} range was {start_year}-{end_year}."
            ),
            intent=intent,
            sources=[_coverage_source()],
            unsupported=True,
            unsupported_reason="no_data",
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
