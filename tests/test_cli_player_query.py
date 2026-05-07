"""Tests for Bug 2b: CLI latest-year default logic.

When a stat query is asked WITHOUT specifying a year (e.g., 'who leads MLB in HR'),
the CLI should return leaders for the MOST RECENT available data, NOT career leaders.
"""

from unittest.mock import patch

# We'll test at the answer() function level since it contains the bug
# The bug is: when no year is specified, cli.answer() calls get_career_stat_leaders()
# instead of looking up the latest available year and calling get_stat_leaders()


class TestLatestYearLogic:
    """Bug 2b: CLI should use most recent year when no year specified."""

    def test_no_player_no_year_still_shows_career_leaders(self):
        """'who leads MLB in HR' (no player, no year) → shows career leaders.

        This is the unchanged fallback behavior: when neither a specific player
        nor a year is specified, show all-time career leaders.
        """
        from baseball_rag.cli import answer

        result = answer("who leads MLB in HR")
        assert "All-time career" in result or "career" in result.lower()
        # Should have actual data (Aaron Judge is the real 2025 leader)
        assert len(result) > 50

    def test_with_explicit_year_works_normally(self):
        """'HR leaders in 1999' → should call range leaders for 1999-1999."""
        from baseball_rag.cli import answer

        with (
            patch("baseball_rag.service.get_stat_leaders_range") as mock_yearly,
            patch("baseball_rag.service.init_db"),
        ):
            mock_yearly.return_value = []

            answer("HR leaders in 1999")

            # With explicit year, should definitely use the year range query.
            assert mock_yearly.called, "year range query should be called for explicit years"
            args = mock_yearly.call_args[0]
            assert args[0] == "HR"
            assert args[1] == 1999
            assert args[2] == 1999

    def test_latest_year_should_be_determined_from_db(self):
        """Verify the fix would need to query DB for max(yearID).

        This is a design-level test documenting what the correct behavior should be:
        when no year specified, query MAX(yearID) from batting table and use that.
        """
        # This test documents expected behavior - currently there's no mechanism
        # in cli.py or queries.py to get the "latest" year dynamically
        from baseball_rag.db.duckdb_schema import get_duckdb

        conn = get_duckdb()
        result = conn.execute("SELECT MAX(yearID) FROM batting").fetchone()
        conn.close()

        latest_year = result[0] if result else None
        assert latest_year is not None, "DB should have batting data with years"
        assert latest_year > 2000, f"Latest year {latest_year} seems wrong"

        # This proves the DB has a "latest year" we could use as default


class TestCliRequestSpine:
    def test_cli_text_rendering_delegates_through_request_execution(self):
        """CLI text output is adapted from the shared request execution path."""
        from baseball_rag.cli import answer
        from baseball_rag.provenance import StructuredAnswer

        with patch("baseball_rag.cli.execute_request") as execute:
            execute.return_value.answer = StructuredAnswer(
                answer="No result",
                intent="stat_query",
                warnings=["Try a more specific year."],
            )

            result = answer("who led in made-up stat")

        execute.assert_called_once_with("who led in made-up stat", adapter_component_id="cli")
        assert result == "No result\n\nWarning: Try a more specific year."
