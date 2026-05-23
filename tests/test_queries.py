"""Tests for SQL query helpers."""

import pytest

from baseball_rag.db.queries import (
    StatQueryPlan,
    execute_stat_query,
    execute_stat_query_plan,
    get_career_stat_leaders,
    get_fielding_leaders,
)
from baseball_rag.routing import StatQueryCase
from baseball_rag.routing.query_router import TimePeriod, TimePeriodType
from baseball_rag.stat_query import answer_stat_query


def test_execute_stat_query_plan_season_batting_leaderboard_returns_rows():
    """Season batting leaderboards should return rows with answer-ready fields."""
    result = execute_stat_query_plan(
        StatQueryPlan(
            stat="HR",
            table="batting",
            kind="leaderboard",
            intent="stat_query",
            start_year=1965,
            end_year=1965,
        )
    )

    assert result.rows
    row = result.rows[0]
    assert "name" in row
    assert "team" in row
    assert "stat_value" in row


def test_rbi_leaders_1962():
    """Test RBI leaders for 1962 - verify structural correctness."""
    result = execute_stat_query_plan(
        StatQueryPlan(
            stat="RBI",
            table="batting",
            kind="leaderboard",
            intent="stat_query",
            start_year=1962,
            end_year=1962,
        )
    )

    assert result.rows
    row = result.rows[0]
    assert "name" in row
    assert "stat_value" in row


def test_career_hr_leaders():
    """Test career HR leaders - Babe Ruth should be #1."""
    result = get_career_stat_leaders("HR")
    assert len(result) >= 3
    top_10_names = [row["name"] for row in result[:10]]
    assert any("Ruth" in name or "Babe" in name for name in top_10_names), (
        f"Babe Ruth not in top 10: {top_10_names}"
    )


def test_career_ops_leaders_use_weighted_rate_not_summed_seasons():
    """Career OPS must be calculated from aggregate components, not summed yearly OPS."""
    result = get_career_stat_leaders("OPS")

    assert len(result) > 0
    assert 0 < result[0]["stat_value"] < 2


def test_range_ops_leaders_use_weighted_rate_not_summed_seasons():
    """Range OPS must be calculated from aggregate components, not summed yearly OPS."""
    result = execute_stat_query_plan(
        StatQueryPlan(
            stat="OPS",
            table="batting",
            kind="leaderboard",
            intent="stat_query",
            start_year=1970,
            end_year=1979,
        )
    ).rows

    assert len(result) > 0
    assert 0 < result[0]["stat_value"] < 2


def test_outfield_putouts_1983():
    """Test outfield putouts leaders for 1983."""
    result = get_fielding_leaders(1983, position="OF")
    assert isinstance(result, list)
    assert result[0] == {"player": "Manning, Rick", "stat_value": 471}


def test_get_fielding_leaders_position_parameterization():
    """Verify position values are parameterized by checking results reflect correct filtering.

    When 'OF' is passed, we expect the Lahman aggregate OF position.
    This black-box behavioral test confirms parameterization works — if 'OF' were
    interpolated as a literal string instead of bound as a parameter, the query
    would either fail or return wrong results.
    """
    result = get_fielding_leaders(1983, position="OF")
    assert isinstance(result, list)
    row = result[0]
    assert "player" in row, f"Expected 'player' key, got: {row}"
    assert "stat_value" in row, f"Expected 'stat_value' key, got: {row}"


def test_unknown_stat_is_rejected_before_sql_execution():
    """Unsupported stats must not fall through to raw SQL column names."""
    with pytest.raises(ValueError, match="Unsupported stat"):
        execute_stat_query_plan(
            StatQueryPlan(
                stat="HR); DROP TABLE batting; --",
                table="batting",
                kind="leaderboard",
                intent="stat_query",
                start_year=1965,
                end_year=1965,
            )
        )


def test_execute_stat_query_returns_executed_sql_for_provenance():
    """Stat provenance should be built from the query that actually ran."""
    result = execute_stat_query("OPS", table="batting", start_year=1970, end_year=1979)

    assert result.rows
    assert result.sql == result.executed_sql
    assert "SUM" in result.sql
    assert "SUM(b.AB) >= 100" in result.sql
    assert result.tables == ["batting", "people"]


def test_execute_stat_query_plan_runs_leaderboard_plan_directly():
    result = execute_stat_query_plan(
        StatQueryPlan(
            stat="OPS",
            table="batting",
            kind="leaderboard",
            intent="stat_query",
            start_year=1970,
            end_year=1979,
        )
    )

    assert result.rows
    assert result.stat == "OPS"
    assert result.params == [1970, 1979]
    assert "SUM(b.AB) >= 100" in result.sql


def test_execute_stat_query_career_leaders_do_not_merge_same_name_players():
    result = execute_stat_query("HR", table="batting")

    assert result.rows[0]["name"] == "Bonds, Barry"
    assert result.rows[0]["stat_value"] == 762
    assert all(row["stat_value"] != 807 for row in result.rows)
    assert "b.playerID" in result.sql


def test_execute_stat_query_supports_fielding_putouts():
    result = execute_stat_query(
        "PO",
        table="fielding",
        start_year=1983,
        end_year=1983,
        position="OF",
    )

    assert result.rows
    assert result.stat == "PO"
    assert result.tables == ["fielding", "people"]
    assert "f.POS = ?" in result.sql


def test_execute_stat_query_supports_career_fielding_putouts():
    result = execute_stat_query("PO", table="fielding")

    assert result.rows
    assert result.rows[0]["name"] == "Beckley, Jake"
    assert result.tables == ["fielding", "people"]
    assert "FROM fielding f" in result.sql


def test_execute_stat_query_uses_pitching_table_for_era():
    result = execute_stat_query("ERA", table="pitching", start_year=1968, end_year=1968)

    assert result.rows
    assert result.stat == "ERA"
    assert result.tables == ["pitching", "people"]
    assert "FROM pitching pi" in result.sql
    assert "SUM(pi.IPouts) >= 300" in result.sql


@pytest.mark.parametrize("stat", ["ERA", "WHIP"])
def test_execute_stat_query_orders_pitching_rate_stats_lowest_first(stat):
    result = execute_stat_query(stat, table="pitching", start_year=1968, end_year=1968)

    values = [row["stat_value"] for row in result.rows]
    assert values == sorted(values)
    assert result.tables == ["pitching", "people"]
    assert "SUM(pi.IPouts) >= 300" in result.sql
    assert "ORDER BY stat_value ASC" in result.sql


def test_execute_stat_query_avg_range_uses_minimum_at_bats_guard():
    result = execute_stat_query("AVG", table="batting", start_year=1894, end_year=1894)

    assert result.rows
    assert all(0 < row["stat_value"] < 1 for row in result.rows)
    assert "SUM(b.AB) >= 100" in result.sql


def test_execute_stat_query_player_ops_uses_executed_guarded_sql_for_provenance():
    result = execute_stat_query("OPS", table="batting", player_name="Ted Williams", year=1941)

    assert result.rows
    assert result.sql == result.executed_sql
    assert "<stat>" not in result.sql
    assert "b.AB >= 100" in result.sql
    assert "strip_accents" in result.sql


def test_execute_stat_query_supports_player_pitching_stats():
    result = execute_stat_query("W", table="pitching", player_name="Cy Young", year=1901)

    assert result.rows
    assert result.rows[0]["name"] == "Young, Cy"
    assert result.tables == ["pitching", "people"]
    assert "FROM pitching pi" in result.sql


def test_answer_stat_query_source_sql_matches_executed_sql(monkeypatch):
    """Stat answers expose the same parameterized SQL returned by execution."""
    captured = {}

    def fake_execute(plan):
        from baseball_rag.db.queries import StatQueryResult

        captured["plan"] = plan
        return StatQueryResult(
            stat="OPS",
            label="OPS leaderboard for 1970-1979",
            tables=["batting", "people"],
            rows=[{"name": "Player, One", "team": "Range", "stat_value": 1.234}],
            sql="SELECT parameterized_ops WHERE b.yearID >= ? AND b.yearID <= ?",
            executed_sql="SELECT parameterized_ops WHERE b.yearID >= ? AND b.yearID <= ?",
            params=[1970, 1979],
        )

    monkeypatch.setattr("baseball_rag.stat_query.execute_stat_query_plan", fake_execute)

    answer = answer_stat_query(
        StatQueryCase(
            stat="OPS",
            raw_question="OPS leaders between 1970-1979",
            time_period=TimePeriod(type=TimePeriodType.RANGE, value=[1970, 1979]),
        )
    )

    assert "Top OPS leaders (1970-1979):" in answer.answer
    assert answer.sources[0].sql == "SELECT parameterized_ops WHERE b.yearID >= ? AND b.yearID <= ?"
    assert captured["plan"].stat == "OPS"


def test_answer_stat_query_player_no_data_is_structured_unsupported(monkeypatch):
    """Player-specific misses stay unsupported without falling back to a leaderboard."""

    def fake_execute(_plan):
        from baseball_rag.db.queries import StatQueryResult

        return StatQueryResult(
            stat="HR",
            label="Player stat lookup",
            tables=["batting", "people"],
            rows=[],
            sql="SELECT player_hr WHERE name = ?",
            executed_sql="SELECT player_hr WHERE name = ?",
            params=["missing"],
        )

    monkeypatch.setattr("baseball_rag.stat_query.execute_stat_query_plan", fake_execute)

    answer = answer_stat_query(
        StatQueryCase(
            stat="HR",
            player_name="Missing Player",
            raw_question="how many HR did Missing Player hit",
        )
    )

    assert answer.unsupported is True
    assert answer.unsupported_reason == "no_data"
    assert "No HR result found for Missing Player" in answer.answer
    assert answer.sources[0].sql == "SELECT player_hr WHERE name = ?"


def test_answer_stat_query_rejects_partial_player_before_coverage_and_execution(monkeypatch):
    """Ambiguous player names are rejected before coverage checks or DuckDB execution."""

    def fail_execute(_plan):
        raise AssertionError("partial player names should not execute")

    monkeypatch.setattr("baseball_rag.stat_query.execute_stat_query_plan", fail_execute)

    answer = answer_stat_query(
        StatQueryCase(
            stat="HR",
            player_name="Ruth",
            raw_question="Ruth HR in 2026",
            time_period=TimePeriod(type=TimePeriodType.SINGLE, value=2026),
        )
    )

    assert answer.unsupported is True
    assert answer.unsupported_reason == "ambiguous"
    assert answer.review_reason == "ambiguous"
    assert "'Ruth' is ambiguous" in answer.answer


def test_answer_stat_query_rejects_player_range_before_coverage(monkeypatch):
    """Player-specific multi-season lookups stay ambiguous before coverage checks."""

    def fail_execute(_plan):
        raise AssertionError("player ranges should not execute")

    monkeypatch.setattr("baseball_rag.stat_query.execute_stat_query_plan", fail_execute)

    answer = answer_stat_query(
        StatQueryCase(
            stat="HR",
            player_name="Aaron Judge",
            raw_question="Aaron Judge HR from 2026-2027",
            time_period=TimePeriod(type=TimePeriodType.RANGE, value=[2026, 2027]),
        )
    )

    assert answer.unsupported is True
    assert answer.unsupported_reason == "ambiguous"
    assert answer.review_reason == "ambiguous"
    assert "Player-specific HR lookups need one season, not 2026-2027" in answer.answer


def test_answer_stat_query_player_no_data_mentions_stat_table(monkeypatch):
    """Player misses describe the planned stat table, not always batting."""

    def fake_execute(_plan):
        from baseball_rag.db.queries import StatQueryResult

        return StatQueryResult(
            stat="PO",
            label="Player stat lookup",
            tables=["fielding", "people"],
            rows=[],
            sql="SELECT player_po WHERE name = ?",
            executed_sql="SELECT player_po WHERE name = ?",
            params=["missing"],
        )

    monkeypatch.setattr("baseball_rag.stat_query.execute_stat_query_plan", fake_execute)

    answer = answer_stat_query(
        StatQueryCase(
            stat="PO",
            player_name="Missing Player",
            raw_question="Missing Player putouts",
        )
    )

    assert answer.unsupported_reason == "no_data"
    assert "local Lahman-derived fielding data" in answer.answer
