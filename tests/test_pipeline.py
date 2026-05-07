"""End-to-end pipeline integration test — Phase 7.3."""

from unittest.mock import patch

import pytest

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


class TestCliExceptionHandling:
    def test_retrieve_exception_propagates_from_cli_answer(self):
        """RuntimeError during ChromaDB retrieve propagates instead of returning silent fallback."""

        def fake_retrieve(query, top_k=3, persist_dir=None, where=None):
            raise RuntimeError("ChromaDB read-only volume")

        with patch("baseball_rag.retrieval.decision.retrieve", fake_retrieve):
            # General query goes through the RAG path (retrieve + generate)
            with pytest.raises(RuntimeError, match="read-only"):
                answer("who was babe ruth")

    def test_retrieve_not_found_returns_friendly_message(self):
        """ChromaDB NotFoundError returns helpful 'run ingest' message."""

        class FakeNotFoundError(Exception):
            pass

        def fake_retrieve(query, top_k=3, persist_dir=None, where=None):
            raise FakeNotFoundError("collection not found")

        with patch("baseball_rag.retrieval.decision.retrieve", fake_retrieve):
            result = answer("who was babe ruth")
            assert "ingest" in result
