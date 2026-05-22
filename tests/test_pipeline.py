"""End-to-end pipeline integration test — Phase 7.3."""

from baseball_rag.cli import answer


class TestPipeline:
    def test_full_query_pipeline_stat(self):
        """Query 'who had most RBIs in 1962' returns string mentioning RBI or Mantle."""
        result = answer("who had the most RBIs in 1962")
        assert isinstance(result, str)
        # Stat queries return formatted leaderboard
        assert "RBI" in result or "Mantle" in result

    def test_full_query_pipeline_general(self):
        """General query returns a non-empty string."""
        result = answer("who was babe ruth")
        assert isinstance(result, str)
        assert len(result) > 0
