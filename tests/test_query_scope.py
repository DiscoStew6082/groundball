from baseball_rag.provenance import StructuredAnswer
from baseball_rag.query_scope import QueryScope, resolve_query_scope
from baseball_rag.routing.query_router import TimePeriod, TimePeriodType


def test_bare_current_century_decade_is_ambiguous_with_configured_current_year():
    result = resolve_query_scope(
        TimePeriod(type=TimePeriodType.DECADE, value=20),
        raw_question="most HRs in the 20s",
        stat="HR",
        intent="stat_query",
        current_year=2026,
    )

    assert result is not None
    assert result.unsupported is True
    assert result.unsupported_reason == "ambiguous"
    assert "Use a full decade like 1920s or 2020s" in result.answer


def test_explicit_historical_decade_resolves_to_year_range():
    result = resolve_query_scope(
        TimePeriod(type=TimePeriodType.DECADE, value=1920),
        raw_question="most HRs in the 1920s",
        stat="HR",
        intent="stat_query",
        coverage={"min": 1871, "max": 2025},
        current_year=2026,
    )

    assert result == QueryScope(1920, 1929)


def test_reversed_ranges_are_ambiguous_before_execution():
    result = resolve_query_scope(
        TimePeriod(type=TimePeriodType.RANGE, value=[1980, 1970]),
        raw_question="who had most RBIs between 1980-1970",
        stat="RBI",
        intent="stat_query",
        coverage={"min": 1871, "max": 2025},
    )

    assert isinstance(result, StructuredAnswer)
    assert result.unsupported_reason == "ambiguous"
    assert "1980-1970" in result.answer


def test_coverage_no_data_uses_manifest_range():
    result = resolve_query_scope(
        TimePeriod(type=TimePeriodType.SINGLE, value=2026),
        raw_question="who had the most HRs in 2026",
        stat="HR",
        intent="stat_query",
        coverage={"min": 1871, "max": 2025},
    )

    assert isinstance(result, StructuredAnswer)
    assert result.unsupported_reason == "no_data"
    assert "1871-2025" in result.answer
