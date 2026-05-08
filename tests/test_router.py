"""Tests for query routing."""

from baseball_rag.routing import route


class TestRouter:
    def test_classify_stat_query(self):
        """'most RBIs in 1962' → stat=RBI, year=1962."""
        result = route("who had the most RBIs in 1962")
        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        assert result.year == 1962

    def test_year_variants_four_digit(self):
        """Four-digit years parse correctly."""
        result = route("most home runs 1977")
        assert result.year == 1977

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
        assert result.year == 1968

    def test_fielding_position_detection_maps_specific_outfield_to_dataset_granularity(self):
        """Specific outfield phrases map to the Lahman fielding POS value."""
        result = route("center field putouts leaders in 1983")

        assert result.intent == "stat_query"
        assert result.stat == "PO"
        assert result.position == "OF"

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

    def test_range_1960_to_1980(self):
        """'between 1960-1980' → type=range, value=[1960, 1980]."""
        result = route("who had most RBIs between 1960-1980")
        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        assert result.time_period is not None
        assert result.time_period.type.value == "range"
        assert result.time_period.value == [1960, 1980]

    def test_year_backward_compat(self):
        """Single-year queries still expose .year for backward compat."""
        result = route("who led MLB in RBIs in 2022")
        assert result.year == 2022
        assert result.stat == "RBI"

    def test_time_period_single_no_year_ambiguity(self):
        """A decade query returns None from the .year property (not ambiguous)."""
        result = route("most HRs in the seventies")
        # .year is a backward-compat shim that only works for single-year queries
        assert result.year is None
        assert result.time_period is not None

    def test_full_name_player_bio_routes_deterministically(self):
        """Simple full-name biography questions should not depend on LLM routing."""
        result = route("who was Babe Ruth")

        assert result.intent == "player_biography"
        assert result.player_name == "Babe Ruth"

    def test_tell_me_about_full_name_routes_deterministically(self):
        result = route("tell me about Matt Olson")

        assert result.intent == "player_biography"
        assert result.player_name == "Matt Olson"

    def test_stat_definition_routes_as_general_explanation(self):
        result = route("what is OPS")

        assert result.intent == "general_explanation"
        assert result.stat == "OPS"
