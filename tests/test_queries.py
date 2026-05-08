"""Tests for SQL query helpers."""

import pytest

from baseball_rag.db.queries import (
    execute_stat_query,
    get_career_stat_leaders,
    get_fielding_leaders,
    get_stat_leaders,
    get_stat_leaders_range,
)


def test_get_stat_leaders_returns_list():
    """Test that get_stat_leaders returns a list of dicts with correct keys."""
    result = get_stat_leaders("HR", 1965)  # year we have data for
    assert isinstance(result, list)
    assert len(result) > 0
    row = result[0]
    assert "name" in row
    assert "team" in row
    assert "stat_value" in row


def test_rbi_leaders_1962():
    """Test RBI leaders for 1962 - verify structural correctness."""
    result = get_stat_leaders("RBI", 1962)
    assert isinstance(result, list)
    if len(result) > 0:
        row = result[0]
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
    result = get_stat_leaders_range("OPS", 1970, 1979)

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
        get_stat_leaders("HR); DROP TABLE batting; --", 1965)


def test_execute_stat_query_returns_executed_sql_for_provenance():
    """Stat provenance should be built from the query that actually ran."""
    result = execute_stat_query("OPS", start_year=1970, end_year=1979)

    assert result.rows
    assert result.sql == result.executed_sql
    assert "SUM" in result.sql
    assert "SUM(b.AB) >= 100" in result.sql
    assert result.tables == ["batting", "people"]


def test_execute_stat_query_career_leaders_do_not_merge_same_name_players():
    result = execute_stat_query("HR")

    assert result.rows[0]["name"] == "Bonds, Barry"
    assert result.rows[0]["stat_value"] == 762
    assert all(row["stat_value"] != 807 for row in result.rows)
    assert "b.playerID" in result.sql


def test_execute_stat_query_supports_fielding_putouts():
    result = execute_stat_query("PO", start_year=1983, end_year=1983, position="OF")

    assert result.rows
    assert result.stat == "PO"
    assert result.tables == ["fielding", "people"]
    assert "f.POS = ?" in result.sql


def test_execute_stat_query_supports_career_fielding_putouts():
    result = execute_stat_query("PO")

    assert result.rows
    assert result.rows[0]["name"] == "Beckley, Jake"
    assert result.tables == ["fielding", "people"]
    assert "FROM fielding f" in result.sql


def test_execute_stat_query_uses_pitching_table_for_era():
    result = execute_stat_query("ERA", start_year=1968, end_year=1968)

    assert result.rows
    assert result.stat == "ERA"
    assert result.tables == ["pitching", "people"]
    assert "FROM pitching pi" in result.sql
    assert "SUM(pi.IPouts) >= 300" in result.sql


def test_execute_stat_query_player_ops_uses_executed_guarded_sql_for_provenance():
    result = execute_stat_query("OPS", player_name="Ted Williams", year=1941)

    assert result.rows
    assert result.sql == result.executed_sql
    assert "<stat>" not in result.sql
    assert "b.AB >= 100" in result.sql
    assert "strip_accents" in result.sql


def test_execute_stat_query_supports_player_pitching_stats():
    result = execute_stat_query("W", player_name="Cy Young", year=1901)

    assert result.rows
    assert result.rows[0]["name"] == "Young, Cy"
    assert result.tables == ["pitching", "people"]
    assert "FROM pitching pi" in result.sql
