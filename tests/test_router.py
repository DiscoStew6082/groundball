"""Tests for query routing."""

import pytest

from baseball_rag.generation.llm import LLMResponse, LLMTimeoutError
from baseball_rag.routing import (
    GroundedDatabaseQuestionCase,
    PlayerBiographyCase,
    StatQueryCase,
    route,
)
from baseball_rag.routing.query_router import TimePeriodType


def test_route_facts_are_available_from_stable_contract_module():
    """Downstream callers can import route facts without the router implementation."""
    from baseball_rag.routing import (
        GeneralExplanationCase as ContractGeneralExplanationCase,
    )
    from baseball_rag.routing import (
        RoutedCase,
        TimePeriod,
        routed_case,
    )
    from baseball_rag.routing import (
        TimePeriodType as ContractTimePeriodType,
    )

    period = TimePeriod(type=ContractTimePeriodType.SINGLE, value=1962)
    routed = routed_case(
        intent="general_explanation",
        raw_question="what is OPS",
        stat="OPS",
        time_period=period,
    )

    assert isinstance(routed, ContractGeneralExplanationCase)
    assert routed.raw_question == "what is OPS"
    assert routed.stat == "OPS"
    assert isinstance(routed, RoutedCase)


def test_claim_verification_route_precedes_stat_and_grounded_routes():
    """Supplied DuckDB claim verification remains a biography route even with stat words."""
    result = route("Can DuckDB verify this claim? Babe Ruth hit 60 HR in 1927 and led everyone.")

    assert isinstance(result, PlayerBiographyCase)
    assert result.intent == "player_biography"
    assert result.player_name == "Babe Ruth"


def _assert_single_year(result, year):
    assert result.time_period is not None
    assert result.time_period.type == TimePeriodType.SINGLE
    assert result.time_period.value == year


def _fake_llm_route(monkeypatch, content):
    def llm_response(*_args, **_kwargs):
        return LLMResponse(content=content, model="test", done=True)

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", llm_response)


class TestRouter:
    def test_classify_stat_query(self):
        """'most RBIs in 1962' → stat=RBI, year=1962."""
        result = route("who had the most RBIs in 1962")
        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        _assert_single_year(result, 1962)

    def test_year_variants_four_digit(self):
        """Four-digit years parse correctly."""
        result = route("most home runs 1977")
        _assert_single_year(result, 1977)

    def test_year_variants_spelled_nineteen_twenty_five(self):
        """Spoken four-digit years parse as single-season filters."""
        result = route("How many homers did Babe Ruth have in nineteen twenty-five?")

        assert result.intent == "stat_query"
        assert result.stat == "HR"
        assert result.player_name == "Babe Ruth"
        _assert_single_year(result, 1925)

    def test_year_variants_spelled_year_with_digit_unit(self):
        """Spoken years can end with a typed digit."""
        result = route("who had the most hits in Nineteen fifty 6")

        assert result.intent == "stat_query"
        assert result.stat == "H"
        _assert_single_year(result, 1956)

    def test_year_variants_spelled_century_with_digit_pair(self):
        """Spoken years can use typed digits after the century word."""
        result = route("who had the most hits in Nineteen 4 7")

        assert result.intent == "stat_query"
        assert result.stat == "H"
        _assert_single_year(result, 1947)

    def test_year_variants_spelled_century_with_zero_digit_pair(self):
        """Digit-pair spoken years preserve zero as a decade digit."""
        result = route("who had the most hits in Nineteen 0 7")

        assert result.intent == "stat_query"
        assert result.stat == "H"
        _assert_single_year(result, 1907)

    def test_incomplete_digit_pair_is_not_a_spoken_year(self):
        """A lone digit after a century word is too ambiguous to infer a season."""
        result = route("who had the most hits in Nineteen 4")

        assert result.intent == "stat_query"
        assert result.stat == "H"
        assert result.time_period is None

    def test_unknown_year_not_required(self):
        """Stat query without a year still routes correctly."""
        result = route("career home run leaders")
        assert result.intent == "stat_query"
        assert result.stat == "HR"

    def test_era_stat_detection(self):
        """'best ERA 1968' parses as stat=ERA, year=1968."""
        result = route("who had the best ERA in 1968")
        assert result.intent == "stat_query"
        assert result.stat == "ERA"
        _assert_single_year(result, 1968)

    def test_player_stat_subject_without_possessive_routes_to_stat_query(self):
        result = route("What was Ted Williams batting average in 1941")

        assert isinstance(result, StatQueryCase)
        assert result.intent == "stat_query"
        assert result.stat == "AVG"
        assert result.player_name == "Ted Williams"
        _assert_single_year(result, 1941)

    def test_player_stat_subject_allows_surnames_that_overlap_league_terms(self):
        result = route("what was Brandon League era in 2011")

        assert isinstance(result, StatQueryCase)
        assert result.intent == "stat_query"
        assert result.stat == "ERA"
        assert result.player_name == "Brandon League"
        _assert_single_year(result, 2011)

    def test_player_stat_subject_matches_unaccented_user_input(self):
        result = route("What was Ronald Acuna batting average in 2019")

        assert isinstance(result, StatQueryCase)
        assert result.intent == "stat_query"
        assert result.stat == "AVG"
        assert result.player_name == "Ronald Acuna"
        _assert_single_year(result, 2019)

    def test_possessive_league_stat_subject_is_not_player_stat_query(self):
        result = route("what was National League's batting average in 1941")

        assert not (isinstance(result, StatQueryCase) and result.player_name == "National League")

    def test_team_stat_subject_without_possessive_is_not_player_stat_query(self):
        team_questions = [
            ("what was New York Yankees batting average in 1998", "New York Yankees"),
            ("what was Houston Astros batting average in 2017", "Houston Astros"),
            ("what was Cleveland Indians batting average in 1995", "Cleveland Indians"),
            ("what was Seattle Pilots batting average in 1969", "Seattle Pilots"),
            ("what was Boston Bees batting average in 1936", "Boston Bees"),
            ("what was Brooklyn Robins batting average in 1920", "Brooklyn Robins"),
            ("what was National League batting average in 1941", "National League"),
            ("what was Players League batting average in 1890", "Players League"),
        ]

        for question, subject in team_questions:
            result = route(question)
            assert not (isinstance(result, StatQueryCase) and result.player_name == subject)

    def test_fielding_position_detection_maps_specific_outfield_to_dataset_granularity(self):
        """Specific outfield phrases map to the Lahman fielding POS value."""
        result = route("center field putouts leaders in 1983")

        assert result.intent == "stat_query"
        assert result.stat == "PO"
        assert result.position == "OF"

    def test_fielding_position_detection_maps_corner_outfield_to_dataset_granularity(self):
        result = route("left field putouts leaders in 1983")

        assert result.intent == "stat_query"
        assert result.stat == "PO"
        assert result.position == "OF"

    def test_fielding_position_detection_preserves_infield_position(self):
        result = route("shortstop putouts leaders in 1983")

        assert result.intent == "stat_query"
        assert result.stat == "PO"
        assert result.position == "SS"

    def test_original_question_preserved(self):
        """raw_question always contains original text."""
        q = "who led MLB in RBI in 1957"
        result = route(q)
        assert result.raw_question == q

    # ------------------------------------------------------------------
    # TimePeriod tests — decade / range / relative extraction
    # ------------------------------------------------------------------

    def test_decade_seventies(self):
        """'seventies' → time_period type=decade, value=70."""
        result = route("who hit the most homers in the seventies")
        assert result.intent == "stat_query"
        assert result.stat == "HR"
        assert result.time_period is not None
        assert result.time_period.type.value == "decade"
        assert result.time_period.value == 70

    def test_decade_1980s(self):
        """'80s' → type=decade, value=80."""
        result = route("most RBIs in the 80s")
        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        assert result.time_period is not None
        assert result.time_period.type.value == "decade"
        assert result.time_period.value == 80

    def test_explicit_decade_preserves_century(self):
        result = route("most HRs in the 1920s")

        assert result.intent == "stat_query"
        assert result.stat == "HR"
        assert result.time_period is not None
        assert result.time_period.type.value == "decade"
        assert result.time_period.value == 1920

    def test_range_1960_to_1980(self):
        """'between 1960-1980' → type=range, value=[1960, 1980]."""
        result = route("who had most RBIs between 1960-1980")
        assert isinstance(result, StatQueryCase)
        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        assert result.time_period is not None
        assert result.time_period.type.value == "range"
        assert result.time_period.value == [1960, 1980]

    def test_single_year_time_period(self):
        """Single-year queries expose their season through time_period."""
        result = route("who led MLB in RBIs in 2022")
        _assert_single_year(result, 2022)
        assert result.stat == "RBI"

    def test_decade_time_period_is_not_single_year(self):
        """A decade query keeps its decade scope instead of a single-season shortcut."""
        result = route("most HRs in the seventies")
        assert result.time_period is not None
        assert result.time_period.type == TimePeriodType.DECADE

    def test_full_name_player_bio_routes_deterministically(self):
        """Simple full-name biography questions should not depend on LLM routing."""
        result = route("who was Babe Ruth")

        assert isinstance(result, PlayerBiographyCase)
        assert result.intent == "player_biography"
        assert result.player_name == "Babe Ruth"

    def test_lowercase_full_name_player_bio_routes_deterministically(self, monkeypatch):
        """Lowercase biography questions should not wait on LLM routing."""

        def fail_llm(*_args, **_kwargs):
            raise AssertionError("LLM router should not be called")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

        result = route("who was tom seaver")

        assert isinstance(result, PlayerBiographyCase)
        assert result.intent == "player_biography"
        assert result.player_name == "Tom Seaver"

    def test_tell_me_about_full_name_routes_deterministically(self):
        result = route("tell me about Matt Olson")

        assert isinstance(result, PlayerBiographyCase)
        assert result.intent == "player_biography"
        assert result.player_name == "Matt Olson"

    def test_deterministic_database_pattern_returns_grounded_database_question_case(self):
        result = route("who won the Triple Crown and which years")

        assert isinstance(result, GroundedDatabaseQuestionCase)
        assert result.intent == "grounded_database_question"
        assert result.raw_question == "who won the Triple Crown and which years"

    def test_ambiguous_500_club_routes_to_grounded_database_question_case(self):
        result = route("who is in the 500 club")

        assert isinstance(result, GroundedDatabaseQuestionCase)
        assert result.intent == "grounded_database_question"
        assert result.raw_question == "who is in the 500 club"

    def test_generic_lowercase_bio_question_does_not_route_as_named_player(self):
        result = route("who was the best hitter")

        assert result.intent != "player_biography"
        assert not hasattr(result, "player_name")

    def test_empty_llm_routing_response_uses_heuristic_route(self, monkeypatch):
        """Blank LLM routing output should not abort the whole request."""

        def empty_llm_response(*_args, **_kwargs):
            raise ValueError("LM Studio returned an empty response.")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", empty_llm_response)

        result = route("tell me something interesting about baseball")

        assert result.intent == "general_explanation"
        assert result.stat is None

    def test_malformed_llm_routing_json_uses_heuristic_route(self, monkeypatch):
        """Routing JSON with the wrong shape should not abort the whole request."""

        _fake_llm_route(monkeypatch, '["not", "a", "route"]')

        result = route("tell me something interesting about baseball")

        assert result.intent == "general_explanation"
        assert result.stat is None

    @pytest.mark.parametrize(
        ("time_period_json", "expected_type", "expected_value"),
        (
            ('{"type":"single","value":2022}', TimePeriodType.SINGLE, 2022),
            ('{"type":"range","value":[1960,1980]}', TimePeriodType.RANGE, [1960, 1980]),
            ('{"type":"decade","value":70}', TimePeriodType.DECADE, 70),
            (
                '{"type":"relative","value":{"direction":"past","unit":"year","count":1}}',
                TimePeriodType.RELATIVE,
                {"direction": "past", "unit": "year", "count": 1},
            ),
        ),
    )
    def test_llm_routing_payload_preserves_time_period_conversion(
        self,
        monkeypatch,
        time_period_json,
        expected_type,
        expected_value,
    ):
        """Valid LLM route payloads should expose typed route facts."""

        _fake_llm_route(
            monkeypatch,
            (
                '{"intent":"stat_query","stat":"RBI",'
                f'"time_period":{time_period_json},'
                '"position":null,"player_name":"Hank Aaron"}'
            ),
        )

        result = route("compare this player across the middle years")

        assert isinstance(result, StatQueryCase)
        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        assert result.player_name == "Hank Aaron"
        assert result.time_period is not None
        assert result.time_period.type == expected_type
        assert result.time_period.value == expected_value

    def test_malformed_llm_routing_time_period_uses_heuristic_route(self, monkeypatch):
        """Malformed nested route fields should not abort the whole request."""

        def malformed_llm_response(*_args, **_kwargs):
            return LLMResponse(
                content=(
                    '{"intent":"stat_query","stat":"RBI","time_period":"career",'
                    '"position":null,"player_name":null}'
                ),
                model="test",
                done=True,
            )

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", malformed_llm_response)

        result = route("tell me something interesting about baseball")

        assert result.intent == "general_explanation"
        assert result.stat is None

    def test_malformed_llm_routing_stat_uses_heuristic_route(self, monkeypatch):
        """Malformed stat fields should not abort the whole request."""

        def malformed_llm_response(*_args, **_kwargs):
            return LLMResponse(
                content=(
                    '{"intent":"stat_query","stat":123,"time_period":null,'
                    '"position":null,"player_name":null}'
                ),
                model="test",
                done=True,
            )

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", malformed_llm_response)

        result = route("tell me something interesting about baseball")

        assert result.intent == "general_explanation"
        assert result.stat is None

    def test_malformed_llm_routing_position_uses_heuristic_route(self, monkeypatch):
        """Malformed position fields should not leak into routed cases."""

        def malformed_llm_response(*_args, **_kwargs):
            return LLMResponse(
                content=(
                    '{"intent":"stat_query","stat":"PO","time_period":null,'
                    '"position":["SS"],"player_name":null}'
                ),
                model="test",
                done=True,
            )

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", malformed_llm_response)

        result = route("tell me something interesting about baseball")

        assert result.intent == "general_explanation"
        assert result.stat is None

    def test_malformed_llm_routing_player_name_uses_heuristic_route(self, monkeypatch):
        """Malformed player name fields should not leak into routed cases."""

        def malformed_llm_response(*_args, **_kwargs):
            return LLMResponse(
                content=(
                    '{"intent":"player_biography","stat":null,"time_period":null,'
                    '"position":null,"player_name":{"first":"Babe","last":"Ruth"}}'
                ),
                model="test",
                done=True,
            )

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", malformed_llm_response)

        result = route("tell me something interesting about baseball")

        assert result.intent == "general_explanation"
        assert result.stat is None

    def test_llm_routing_timeout_uses_heuristic_route(self, monkeypatch):
        """Router LM timeouts should not abort the whole request."""

        def timed_out_llm_response(*_args, **_kwargs):
            raise LLMTimeoutError("slow router")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", timed_out_llm_response)

        result = route("tell me something interesting about baseball")

        assert result.intent == "general_explanation"
        assert result.stat is None

    def test_stat_definition_routes_as_general_explanation(self):
        result = route("what is OPS")

        assert result.intent == "general_explanation"
        assert result.stat == "OPS"
