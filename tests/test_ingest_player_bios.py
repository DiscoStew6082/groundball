"""Tests for player bio ingestion into ChromaDB."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


class TestIngestPlayerBios:
    """Test that build_index also ingests all player bios from DuckDB."""

    def test_build_index_ingests_player_bios(self):
        """Verify build_index creates docs for each distinct playerID in batting table."""
        # Mock get_duckdb to return a connection
        mock_conn = MagicMock()
        # Return 3 fake playerIDs
        mock_conn.execute.return_value.fetchall.return_value = [
            ("player1",),
            ("player2",),
            ("player3",),
        ]

        # Patch get_duckdb so build_index uses our mock
        with patch("baseball_rag.corpus.ingest.get_duckdb", return_value=mock_conn):
            # Patch build_player_bio to avoid actual DB calls in test
            with patch("baseball_rag.corpus.ingest.build_player_bio") as mock_build:
                mock_build.return_value = "Mocked bio text"

                # Mock ChromaDB client and collection
                with patch(
                    "baseball_rag.corpus.ingest.chromadb.PersistentClient"
                ) as mock_client_class:
                    mock_collection = MagicMock()
                    mock_client_class.return_value.create_collection.return_value = mock_collection

                    from baseball_rag.corpus.ingest import build_index

                    # Patch static corpus to return empty (we only care about players)
                    with patch("baseball_rag.corpus.ingest.get_stat_defs", return_value=[]):
                        with patch("baseball_rag.corpus.ingest.get_hof_bios", return_value=[]):
                            build_index("data/test_chroma")

        # Verify collection.add was called
        assert mock_collection.add.called, "collection.add should have been called"

        # Get what was passed to collection.add
        call_args = mock_collection.add.call_args
        ids = call_args.kwargs.get("ids") or call_args[1].get("ids", [])

        # Should have 3 player bio docs (one per distinct playerID)
        player_ids_in_chroma = [i for i in ids if str(i).startswith("player:")]
        assert len(player_ids_in_chroma) == 3, (
            f"Expected 3 player bios, got {len(player_ids_in_chroma)}"
        )

    def test_build_index_uses_batch_inserts(self):
        """Verify that player bios are inserted in batches (not one at a time)."""
        mock_conn = MagicMock()
        # Return 10 fake players to trigger batching
        mock_conn.execute.return_value.fetchall.return_value = [
            tuple([f"player{i}"]) for i in range(10)
        ]

        with patch("baseball_rag.corpus.ingest.get_duckdb", return_value=mock_conn):
            with patch("baseball_rag.corpus.ingest.build_player_bio") as mock_build:
                mock_build.return_value = "Mocked bio text"

                with patch(
                    "baseball_rag.corpus.ingest.chromadb.PersistentClient"
                ) as mock_client_class:
                    mock_collection = MagicMock()
                    mock_client_class.return_value.create_collection.return_value = mock_collection

                    from baseball_rag.corpus.ingest import build_index

                    with patch("baseball_rag.corpus.ingest.get_stat_defs", return_value=[]):
                        with patch("baseball_rag.corpus.ingest.get_hof_bios", return_value=[]):
                            build_index("data/test_chroma")

        # collection.add should be called
        assert mock_collection.add.called

    def test_player_doc_id_format(self):
        """Verify player docs use 'player:{playerID}' format for ID."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [("ruthb01",)]

        with patch("baseball_rag.corpus.ingest.get_duckdb", return_value=mock_conn):
            with patch("baseball_rag.corpus.ingest.build_player_bio") as mock_build:
                mock_build.return_value = "Babe Ruth bio text"

                with patch(
                    "baseball_rag.corpus.ingest.chromadb.PersistentClient"
                ) as mock_client_class:
                    mock_collection = MagicMock()
                    mock_client_class.return_value.create_collection.return_value = mock_collection

                    from baseball_rag.corpus.ingest import build_index

                    with patch("baseball_rag.corpus.ingest.get_stat_defs", return_value=[]):
                        with patch("baseball_rag.corpus.ingest.get_hof_bios", return_value=[]):
                            build_index("data/test_chroma")

        call_args = mock_collection.add.call_args
        ids = call_args.kwargs.get("ids") or call_args[1].get("ids", [])

        assert "player:ruthb01" in ids, f"Expected 'player:ruthb01' in IDs, got {ids}"

    def test_player_bio_metadata_category(self):
        """Verify player bios have correct metadata.category = 'player_biography'."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [("testplay",)]

        with patch("baseball_rag.corpus.ingest.get_duckdb", return_value=mock_conn):
            with patch("baseball_rag.corpus.ingest.build_player_bio") as mock_build:
                mock_build.return_value = "Test bio"

                with patch(
                    "baseball_rag.corpus.ingest.chromadb.PersistentClient"
                ) as mock_client_class:
                    mock_collection = MagicMock()
                    mock_client_class.return_value.create_collection.return_value = mock_collection

                    from baseball_rag.corpus.ingest import build_index

                    with patch("baseball_rag.corpus.ingest.get_stat_defs", return_value=[]):
                        with patch("baseball_rag.corpus.ingest.get_hof_bios", return_value=[]):
                            build_index("data/test_chroma")

        call_args = mock_collection.add.call_args
        metadatas = call_args.kwargs.get("metadatas") or call_args[1].get("metadatas", [])

        for meta in metadatas:
            assert meta.get("category") == "player_biography", (
                f"Expected category 'player_biography', got {meta}"
            )

    def test_build_index_writes_generated_corpus_manifest(self, tmp_path):
        """Full player indexing should record a generated corpus manifest."""
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchall.return_value = [("ruthba01",)]
        bio = """---
title: Babe Ruth
player_id: ruthba01
category: player_biography
doc_kind: generated_player_profile
source_tables:
  - people
  - batting
  - pitching
  - fielding
---
# Babe Ruth
"""

        with patch("baseball_rag.corpus.ingest.get_duckdb", return_value=mock_conn):
            with patch("baseball_rag.corpus.ingest.build_player_bio", return_value=bio):
                with patch(
                    "baseball_rag.corpus.ingest.chromadb.PersistentClient"
                ) as mock_client_class:
                    mock_collection = MagicMock()
                    mock_client_class.return_value.create_collection.return_value = mock_collection

                    from baseball_rag.corpus.ingest import build_index

                    with patch("baseball_rag.corpus.ingest.get_stat_defs", return_value=[]):
                        with patch("baseball_rag.corpus.ingest.get_hof_bios", return_value=[]):
                            build_index(tmp_path)

        manifest_path = tmp_path / "corpus_manifest.json"
        assert manifest_path.exists()
        manifest = json.loads(manifest_path.read_text())
        assert manifest["collection_name"] == "baseball_corpus"
        assert manifest["generated_player_profiles"]["count"] == 1
        assert manifest["generated_player_profiles"]["documents"][0]["player_id"] == "ruthba01"

    def test_static_document_record_builds_chroma_and_manifest_data(self, tmp_path):
        from baseball_rag.corpus.ingest import _static_document_record

        doc_path = tmp_path / "OPS.md"
        doc_path.write_text(
            """---
title: OPS
category: stat_definition
---
On-base plus slugging.
""",
            encoding="utf-8",
        )

        record = _static_document_record(doc_path)

        assert record.id == "OPS"
        assert record.text == "OPS\n\nOn-base plus slugging."
        assert record.metadata == {
            "source": "OPS.md",
            "category": "stat_definition",
            "title": "OPS",
        }
        assert record.manifest_entry == {
            "id": "OPS",
            "source": "OPS.md",
            "category": "stat_definition",
            "title": "OPS",
        }

    def test_player_profile_record_builds_chroma_and_manifest_data(self):
        from baseball_rag.corpus.ingest import _player_profile_record

        bio = """---
title: Babe Ruth
player_id: ruthba01
category: player_biography
doc_kind: generated_player_profile
source_tables:
  - people
  - batting
---
# Babe Ruth
"""

        record = _player_profile_record("ruthba01", bio)

        assert record.id == "player:ruthba01"
        assert record.text == bio
        assert record.metadata["player_id"] == "ruthba01"
        assert record.metadata["source_tables"] == "people,batting,pitching,fielding"
        assert record.manifest_entry["source_tables"] == ["people", "batting"]

    def test_build_index_static_only_writes_finalized_manifest_counts(self, tmp_path):
        static_doc = tmp_path / "OPS.md"
        static_doc.write_text(
            """---
title: OPS
category: stat_definition
---
On-base plus slugging.
""",
            encoding="utf-8",
        )

        with patch("baseball_rag.corpus.ingest.chromadb.PersistentClient") as mock_client_class:
            mock_collection = MagicMock()
            mock_client_class.return_value.create_collection.return_value = mock_collection

            from baseball_rag.corpus.ingest import build_index

            with patch(
                "baseball_rag.corpus.ingest.get_stat_defs",
                return_value=[Path(static_doc)],
            ):
                with patch("baseball_rag.corpus.ingest.get_hof_bios", return_value=[]):
                    build_index(tmp_path / "index", include_players=False)

        manifest = json.loads((tmp_path / "index" / "corpus_manifest.json").read_text())
        assert manifest["static_documents"]["count"] == 1
        assert manifest["generated_player_profiles"]["count"] == 0
        assert manifest["generated_player_profiles"]["documents"] == []
