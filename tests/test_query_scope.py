from baseball_rag.provenance import StructuredAnswer
from baseball_rag.query_scope import QueryScope, resolve_query_scope, resolve_query_scope_outcome
from baseball_rag.routing import TimePeriod, TimePeriodType


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


def test_scope_outcome_names_answerable_and_no_scope_states():
    answerable = resolve_query_scope_outcome(
        TimePeriod(type=TimePeriodType.SINGLE, value=1962),
        raw_question="who had the most RBIs in 1962",
        stat="RBI",
        intent="stat_query",
        coverage={"min": 1871, "max": 2025},
    )
    no_scope = resolve_query_scope_outcome(
        None,
        raw_question="career home run leaders",
        stat="HR",
        intent="stat_query",
        coverage={"min": 1871, "max": 2025},
    )

    assert answerable.is_answerable
    assert answerable.scope == QueryScope(1962, 1962)
    assert answerable.answer is None
    assert no_scope.is_no_scope
    assert no_scope.scope is None
    assert no_scope.answer is None


def test_scope_outcome_enforces_single_season_without_double_pass():
    result = resolve_query_scope_outcome(
        TimePeriod(type=TimePeriodType.RANGE, value=[1961, 1962]),
        raw_question="how many HRs did Mickey Mantle have from 1961 to 1962",
        stat="HR",
        intent="stat_query",
        coverage={"min": 1871, "max": 2025},
        require_single_season=True,
        single_season_subject="Player-specific HR lookups",
    )

    assert result.is_unsupported
    assert result.answer is not None
    assert result.answer.unsupported_reason == "ambiguous"
    assert "Player-specific HR lookups need one season, not 1961-1962" in result.answer.answer


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


def test_relative_year_scope_uses_groundball_current_year_env(monkeypatch):
    monkeypatch.setenv("GROUNDBALL_CURRENT_YEAR", "1937")

    result = resolve_query_scope_outcome(
        TimePeriod(
            type=TimePeriodType.RELATIVE,
            value={"direction": "past", "unit": "year", "count": 1},
        ),
        raw_question="who played for the Braves last year",
        stat="G",
        intent="grounded_database_question",
        coverage={"min": 1871, "max": 2025},
    )

    assert result.scope == QueryScope(1936, 1936)


def test_relative_year_scope_keeps_baseball_rag_current_year_env_alias(monkeypatch):
    monkeypatch.setenv("BASEBALL_RAG_CURRENT_YEAR", "1937")

    result = resolve_query_scope_outcome(
        TimePeriod(
            type=TimePeriodType.RELATIVE,
            value={"direction": "past", "unit": "year", "count": 1},
        ),
        raw_question="who played for the Braves last year",
        stat="G",
        intent="grounded_database_question",
        coverage={"min": 1871, "max": 2025},
    )

    assert result.scope == QueryScope(1936, 1936)
