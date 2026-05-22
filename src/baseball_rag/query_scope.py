"""Answerable time-scope resolution for routed baseball questions."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from baseball_rag.outcomes import ambiguous_outcome, no_data_outcome
from baseball_rag.provenance import SourceRecord, StructuredAnswer, compact_data_manifest
from baseball_rag.routing.query_router import TimePeriod, TimePeriodType


@dataclass(frozen=True)
class QueryScope:
    """Concrete inclusive year range resolved from routed time facts."""

    start_year: int
    end_year: int

    @property
    def is_single_season(self) -> bool:
        return self.start_year == self.end_year


def resolve_query_scope(
    time_period: TimePeriod | None,
    *,
    raw_question: str,
    stat: str,
    intent: str,
    coverage: dict[str, Any] | None = None,
    current_year: int | None = None,
    validate_coverage: bool = True,
) -> QueryScope | StructuredAnswer | None:
    """Resolve routed time facts into an answerable scope or unsupported answer."""
    if time_period is None:
        return None
    current = _current_year() if current_year is None else current_year
    if _is_ambiguous_current_century_decade(time_period, raw_question, current):
        return ambiguous_outcome(
            answer=(
                f"The decade in '{raw_question}' is ambiguous. "
                "Use a full decade like 1920s or 2020s."
            ),
            intent=intent,
            sources=[coverage_source()],
        )

    scope = _resolve_time_period(time_period, raw_question, current)
    if scope is None:
        return None

    if validate_coverage:
        unsupported = _unsupported_for_scope(
            stat=stat,
            intent=intent,
            scope=scope,
            coverage=coverage,
        )
        if unsupported is not None:
            return unsupported
    return scope


def structured_stat_year_coverage() -> dict[str, Any]:
    """Return manifest coverage for local structured stat tables."""
    return compact_data_manifest().get("coverage", {}).get("structured_stat_years", {})


def coverage_source() -> SourceRecord:
    """Return provenance for query-scope coverage decisions."""
    return SourceRecord(
        type="system",
        label="Structured stat year coverage",
        detail="Coverage comes from data/manifest.json for local DuckDB-backed stats.",
        data_manifest=compact_data_manifest(),
    )


def _unsupported_for_scope(
    *,
    stat: str,
    intent: str,
    scope: QueryScope,
    coverage: dict[str, Any] | None,
) -> StructuredAnswer | None:
    if scope.start_year > scope.end_year:
        return ambiguous_outcome(
            answer=(
                f"The requested {stat} range {scope.start_year}-{scope.end_year} is reversed. "
                "Ask with the earlier year first."
            ),
            intent=intent,
            sources=[coverage_source()],
        )

    active_coverage = structured_stat_year_coverage() if coverage is None else coverage
    min_year = active_coverage.get("min")
    max_year = active_coverage.get("max")
    if (
        isinstance(min_year, int)
        and isinstance(max_year, int)
        and (scope.start_year < min_year or scope.end_year > max_year)
    ):
        return no_data_outcome(
            answer=(
                f"The local structured stat data covers {min_year}-{max_year}; "
                f"the requested {stat} range was {scope.start_year}-{scope.end_year}."
            ),
            intent=intent,
            sources=[coverage_source()],
        )
    return None


def _resolve_time_period(
    time_period: TimePeriod,
    raw_question: str,
    current_year: int,
) -> QueryScope | None:
    if time_period.type == TimePeriodType.DECADE and isinstance(time_period.value, int):
        if time_period.value >= 1000:
            start_year = time_period.value
        else:
            start_year = _explicit_decade_start(raw_question, time_period.value) or (
                1900 + time_period.value
            )
        return QueryScope(start_year, start_year + 9)
    if (
        time_period.type == TimePeriodType.RANGE
        and isinstance(time_period.value, list)
        and len(time_period.value) >= 2
    ):
        return QueryScope(int(time_period.value[0]), int(time_period.value[-1]))
    if time_period.type == TimePeriodType.SINGLE and isinstance(time_period.value, int):
        return QueryScope(time_period.value, time_period.value)
    if time_period.type == TimePeriodType.RELATIVE and isinstance(time_period.value, dict):
        return _resolve_relative_time_period(time_period.value, current_year)
    return None


def _resolve_relative_time_period(value: dict[str, Any], current_year: int) -> QueryScope | None:
    direction = value.get("direction")
    unit = value.get("unit")
    try:
        count = int(value.get("count", 1))
    except (TypeError, ValueError):
        return None
    if count < 1:
        return None

    if direction == "past" and unit in {"year", "season"}:
        end_year = current_year - 1
        start_year = end_year if count == 1 else current_year - count
        return QueryScope(start_year, end_year)
    if direction == "future" and unit in {"year", "season"}:
        start_year = current_year + 1
        end_year = start_year if count == 1 else current_year + count
        return QueryScope(start_year, end_year)
    return None


def _is_ambiguous_current_century_decade(
    time_period: TimePeriod,
    raw_question: str,
    current_year: int,
) -> bool:
    if time_period.type != TimePeriodType.DECADE or not isinstance(time_period.value, int):
        return False
    if time_period.value >= 1000 or _explicit_decade_start(raw_question, time_period.value):
        return False
    current_decade = (current_year % 100) // 10 * 10
    return 0 <= time_period.value <= current_decade


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
