"""Unit tests for batting range leaderboard plans using real DB data as ground truth."""

from baseball_rag.db.queries import StatQueryPlan, execute_stat_query_plan


def _batting_range_rows(stat: str, start_year: int, end_year: int) -> list[dict]:
    return execute_stat_query_plan(
        StatQueryPlan(
            stat=stat,
            table="batting",
            kind="leaderboard",
            intent="stat_query",
            start_year=start_year,
            end_year=end_year,
        )
    ).rows


class TestGetStatLeadersRange:
    """Tests verify the range aggregator returns correct players from the DB.

    Ground-truth values are derived from the actual Lahman-format CSV data
    loaded at test time, not mocked. These tests validate that SQL aggregation,
    JOIN logic, and ordering work correctly across a year range.
    """

    def test_seventies_hr_leader_is_stargell_296(self):
        """Willie Stargell leads the 1970s with 296 HR."""
        result = _batting_range_rows("HR", 1970, 1979)
        assert len(result) == 10
        assert result[0]["name"] == "Stargell, Willie"
        assert result[0]["stat_value"] == 296

    def test_seventies_top5_known(self):
        """Top 5 HR hitters in the seventies match known DB values."""
        result = _batting_range_rows("HR", 1970, 1979)
        top5_names = [p["name"] for p in result[:5]]
        assert top5_names == [
            "Stargell, Willie",
            "Jackson, Reggie",
            "Bench, Johnny",
            "Bonds, Bobby",
            "May, Lee",
        ]

    def test_eightys_rbi_leader_is_valid(self):
        """1980s RBI leaderboard returns 10 results and the #1 has a valid name."""
        result = _batting_range_rows("RBI", 1980, 1989)
        assert len(result) == 10
        assert ", " in result[0]["name"]  # formatted as "Last, First"
        assert isinstance(result[0]["stat_value"], int)

    def test_single_year_is_not_a_range(self):
        """A single year (2010-2010) should still return results."""
        result = _batting_range_rows("HR", 2010, 2010)
        assert len(result) == 10

    def test_returns_top_10_or_fewer(self):
        """Every range query returns at most 10 players; early eras may have fewer."""
        for stat in ["HR", "RBI", "H"]:
            result = _batting_range_rows(stat, 2000, 2010)
            assert len(result) <= 10
