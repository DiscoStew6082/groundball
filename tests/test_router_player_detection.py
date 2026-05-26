"""Tests for Bug 2a: player name detection in query routing.

These tests verify that when a user asks about a specific player's stats,
the router extracts the player name from the query.
"""

from baseball_rag.routing import route
from baseball_rag.routing.query_router import TimePeriodType


def _assert_single_year(result, year):
    assert result.time_period is not None
    assert result.time_period.type == TimePeriodType.SINGLE
    assert result.time_period.value == year


class TestPlayerDetection:
    """Bug 2a: Router should detect and extract player names from queries."""

    def test_route_time_player_lookup_does_not_read_people_csv_directly(
        self,
        monkeypatch,
    ):
        """Route-time player mentions should use the shared Lahman identity authority."""
        import builtins

        real_open = builtins.open

        def fail_people_csv_open(file, *args, **kwargs):
            if str(file).endswith("People.csv"):
                raise AssertionError("query_router should not read People.csv directly")
            return real_open(file, *args, **kwargs)

        monkeypatch.setattr(builtins, "open", fail_people_csv_open)

        result = route("What was Ted Williams batting average in 1941")

        assert result.intent == "stat_query"
        assert result.stat == "AVG"
        _assert_single_year(result, 1941)
        assert result.player_name == "Ted Williams"

    def test_detect_player_name_from_stat_query(self):
        """'how many home runs did Babe Ruth hit' should extract player='Babe Ruth'.

        The router currently does NOT extract player names - it only extracts
        stat, year, and position (outfield). This test FAILS until Bug 2a is fixed.
        """
        result = route("how many home runs did Babe Ruth hit")
        assert result.intent == "stat_query"
        assert result.stat == "HR"
        # BUG: player should be extracted but isn't
        assert hasattr(result, "player_name"), "Route case has no 'player_name' attribute"
        assert result.player_name is not None, "Player name was not extracted from query"

    def test_detect_player_name_mike_trout(self):
        """'what are Mike Trout's career home runs' should extract player='Mike Trout'."""
        result = route("What are Mike Trout's career home runs")
        # BUG: player extraction missing
        assert hasattr(result, "player_name"), "Route case has no 'player' attribute"
        assert result.player_name is not None
        assert "trout" in result.player_name.lower()

    def test_detect_player_name_with_year(self):
        """'how many RBIs did Barry Bonds have in 2001' should extract player and year."""
        result = route("How many RBIs did Barry Bonds have in 2001")
        assert result.stat == "RBI"
        _assert_single_year(result, 2001)
        # BUG: player extraction missing
        assert hasattr(result, "player_name"), "Route case has no 'player' attribute"
        assert result.player_name is not None

    def test_compact_player_stat_query_routes_without_llm(self, monkeypatch):
        """'Matt Olson RBI in 2023' should stay deterministic in CI."""

        def unavailable_llm(*_args, **_kwargs):
            raise ConnectionError("LM Studio unavailable")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", unavailable_llm)

        result = route("Matt Olson RBI in 2023")

        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        _assert_single_year(result, 2023)
        assert result.player_name == "Matt Olson"

    def test_lowercase_compact_player_stat_query_resolves_known_lahman_name_without_llm(
        self,
        monkeypatch,
    ):
        """Compact player stat phrasing should use Lahman lookup before the LLM."""

        def fail_llm(*_args, **_kwargs):
            raise AssertionError("LLM router should not be called")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

        result = route("matt olson rbi in 2023")

        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        _assert_single_year(result, 2023)
        assert result.player_name == "Matt Olson"

    def test_detect_player_name_preserves_existing_behavior(self):
        """Player detection should NOT break existing stat query classification."""
        # These already work - ensure they still do
        result = route("who had the most RBIs in 1962")
        assert result.intent == "stat_query"
        assert result.stat == "RBI"
        _assert_single_year(result, 1962)
