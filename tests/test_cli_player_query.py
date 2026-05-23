"""Tests for CLI stat-query rendering around no-year leaderboards.

When a league-wide leaderboard query does not specify a year or range, it uses
the all-time career leaderboard. Explicit years still route to season leaders.
"""

from unittest.mock import patch

# The CLI adapts the shared request execution path into text.


class TestNoYearLeaderboardLogic:
    """CLI should use career leaders when no year is specified."""

    def test_no_player_no_year_still_shows_career_leaders(self):
        """'who leads MLB in HR' (no player, no year) → shows career leaders.

        When neither a specific player nor a year is specified, show all-time
        career leaders.
        """
        from baseball_rag.cli import answer

        result = answer("who leads MLB in HR")
        assert "All-time career" in result or "career" in result.lower()
        assert len(result) > 50

    def test_with_explicit_year_works_normally(self):
        """'HR leaders in 1999' -> should execute a 1999-1999 leaderboard plan."""
        from baseball_rag.cli import answer
        from baseball_rag.db.queries import StatQueryResult

        with patch("baseball_rag.stat_query.execute_stat_query_plan") as mock_query:
            mock_query.return_value = StatQueryResult(
                stat="HR",
                label="HR leaderboard for 1999-1999",
                tables=["batting", "people"],
                rows=[],
                sql="SELECT ?",
                executed_sql="SELECT ?",
                params=[1999, 1999],
            )

            answer("HR leaders in 1999")

        mock_query.assert_called_once()
        plan = mock_query.call_args.args[0]
        assert plan.stat == "HR"
        assert plan.table == "batting"
        assert plan.kind == "leaderboard"
        assert plan.start_year == 1999
        assert plan.end_year == 1999
        assert plan.position is None


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
