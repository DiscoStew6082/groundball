"""Tests for player bio generator."""

import pytest

from baseball_rag.corpus.frontmatter import parse_frontmatter
from baseball_rag.corpus.lifecycle import (
    DEFAULT_PLAYER_SOURCE_TABLES,
    GENERATED_PLAYER_PROFILE,
    METADATA_CATEGORY,
    METADATA_DOC_KIND,
    METADATA_PLAYER_ID,
    METADATA_SOURCE_TABLES,
    PLAYER_BIOGRAPHY_CATEGORY,
)
from baseball_rag.corpus.player_bios import build_player_bio, resolve_player_by_name
from baseball_rag.db.duckdb_schema import get_duckdb


@pytest.fixture
def conn():
    """Get a DuckDB connection."""
    return get_duckdb()


class TestBuildPlayerBio:
    def test_build_player_bio_returns_string(self, conn):
        """Basic sanity: function returns a string."""
        # Use Dick Littlefield who played for many teams (pitcher)
        result = build_player_bio("littldi01", conn)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_build_player_bio_has_frontmatter(self, conn):
        """Bio should have YAML frontmatter with required fields."""
        result = build_player_bio("littldi01", conn)
        # Check frontmatter
        assert result.startswith("---")
        assert "title:" in result or "player_id:" in result
        assert "category: player_biography" in result

    def test_build_player_bio_has_player_name(self, conn):
        """Bio should contain the player's name."""
        result = build_player_bio("littldi01", conn)
        # Dick Littlefield's full name should appear
        assert "Dick Littlefield" in result or "Littlefield" in result

    def test_build_player_bio_has_career_summary(self, conn):
        """Bio should have a career summary section."""
        result = build_player_bio("littldi01", conn)
        assert "Career Summary" in result or "career" in result.lower()

    def test_build_player_bio_with_position_player(self, conn):
        """Test with George Kell, a position player (3B) who played for multiple teams."""
        # First verify he exists and has multiple teams
        row = conn.execute(
            "SELECT COUNT(DISTINCT teamID) FROM batting WHERE playerID = 'kellge01'"
        ).fetchone()
        assert row[0] > 1, "George Kell should have played for multiple teams"

        result = build_player_bio("kellge01", conn)
        assert isinstance(result, str)
        assert "Career Summary" in result
        # George Kell was a third baseman
        assert "3B" in result or "third" in result.lower() or "Third" in result

    def test_build_player_bio_season_list(self, conn):
        """Bio should list seasons chronologically."""
        result = build_player_bio("littldi01", conn)
        # Should have season-by-season section with years in range 1940-1970
        import re

        years_in_bio = [int(y) for y in re.findall(r"- (\d{4}):", result)]
        assert len(years_in_bio) > 0, (
            f"Should have year references in season list. Got: {result[:200]}"
        )
        # Verify they're roughly in order (allowing for team changes within a year)
        assert years_in_bio == sorted(years_in_bio), (
            f"Years should be chronological: {years_in_bio}"
        )

    def test_generated_bio_frontmatter_contains_provenance_contract(self, conn):
        """Generated player docs should carry enough metadata to trace their source."""
        result = build_player_bio("littldi01", conn)
        metadata = parse_frontmatter(result)["metadata"]

        assert metadata[METADATA_CATEGORY] == PLAYER_BIOGRAPHY_CATEGORY
        assert metadata[METADATA_DOC_KIND] == GENERATED_PLAYER_PROFILE
        assert metadata[METADATA_PLAYER_ID] == "littldi01"
        assert metadata[METADATA_SOURCE_TABLES] == DEFAULT_PLAYER_SOURCE_TABLES

    def test_build_player_bio_uses_pitching_when_batting_missing(self):
        """Pitcher-only records should still produce a generated player profile."""
        import duckdb

        conn = duckdb.connect(database=":memory:")
        conn.execute(
            """
            CREATE TABLE people (
                playerID TEXT, nameFirst TEXT, nameLast TEXT, birthCity TEXT,
                birthState TEXT, bats TEXT, throws TEXT, debut DATE, finalGame DATE
            )
            """
        )
        conn.execute("CREATE TABLE batting (playerID TEXT, yearID INTEGER, teamID TEXT)")
        conn.execute("CREATE TABLE pitching (playerID TEXT, yearID INTEGER, teamID TEXT)")
        conn.execute(
            "CREATE TABLE fielding "
            "(playerID TEXT, yearID INTEGER, teamID TEXT, POS TEXT, G INTEGER)"
        )
        conn.execute(
            """
            INSERT INTO people VALUES
            ('pitch01', 'Pat', 'Pitcher', 'Erie', 'PA', 'R', 'R', '2001-04-01', '2003-09-30')
            """
        )
        conn.execute(
            "INSERT INTO pitching VALUES ('pitch01', 2001, 'NYA'), ('pitch01', 2002, 'NYA')"
        )
        conn.execute("INSERT INTO fielding VALUES ('pitch01', 2001, 'NYA', 'P', 30)")

        result = build_player_bio("pitch01", conn)

        assert "Pat Pitcher" in result
        assert "Primary position:** P" in result
        assert "- 2001:" in result
        assert "- 2002:" in result


class TestResolvePlayerByName:
    def test_resolve_full_name_is_single_candidate(self, conn):
        resolution = resolve_player_by_name("Dick Littlefield", conn)

        assert resolution.player_id == "littldi01"
        assert resolution.ambiguous is False

    def test_resolve_last_name_only_reports_ambiguity(self, conn):
        resolution = resolve_player_by_name("Johnson", conn)

        assert resolution.player_id is None
        assert resolution.ambiguous is True
        assert len(resolution.candidates) > 1
