import pytest

from baseball_rag.corpus.player_bios import resolve_player_by_name
from baseball_rag.db.duckdb_schema import get_duckdb


@pytest.fixture
def conn():
    """Get a DuckDB connection."""
    return get_duckdb()


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
