"""Build a ChromaDB vector index from corpus documents."""

import argparse
from pathlib import Path

import chromadb

from baseball_rag.corpus import get_hof_bios, get_stat_defs
from baseball_rag.corpus.lifecycle import (
    COLLECTION_NAME,
    finalize_manifest_counts,
    new_manifest,
    player_profile_record,
    static_document_record,
    write_corpus_manifest,
)
from baseball_rag.corpus.player_bios import build_player_bio
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.retrieval.chroma_store import LMStudioEmbeddingFunction

# Batch size for ChromaDB inserts when indexing players
PLAYER_BATCH_SIZE = 500


def build_index(persist_dir: Path, *, include_players: bool = True) -> None:
    """Ingest all corpus documents into a ChromaDB collection.

    Creates a "baseball_corpus" collection with one chunk per document,
    storing text + source filename as metadata. By default, also indexes player
    bios from DuckDB for ~24k players.
    """
    persist_dir = Path(persist_dir)

    client = chromadb.PersistentClient(path=str(persist_dir))

    # Wipe and rebuild each time for reproducibility
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass

    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=LMStudioEmbeddingFunction(),  # type: ignore[arg-type]
        metadata={
            "description": (
                "Baseball stat definitions, Hall of Fame biographies, and player biographies"
            )
        },
    )

    total_docs = 0
    manifest = new_manifest()

    # Index static corpus docs (stat_defs and hof_bios)
    static_texts = []
    static_ids = []
    static_metas = []

    for path in [*get_stat_defs(), *get_hof_bios()]:
        record = static_document_record(path)
        static_texts.append(record.text)
        static_ids.append(record.id)
        static_metas.append(record.metadata)
        manifest["static_documents"]["documents"].append(record.manifest_entry)

    if static_texts:
        collection.add(documents=static_texts, ids=static_ids, metadatas=static_metas)  # type: ignore[arg-type]
        total_docs += len(static_texts)

    if not include_players:
        finalize_manifest_counts(manifest)
        write_corpus_manifest(persist_dir, manifest)
        print(f"Indexed {total_docs} documents into {COLLECTION_NAME} at {persist_dir}")
        return

    # Index player bios from DuckDB
    conn = get_duckdb()
    player_ids_rows = conn.execute(
        """
        SELECT DISTINCT playerID FROM (
            SELECT playerID FROM batting
            UNION ALL
            SELECT playerID FROM pitching
            UNION ALL
            SELECT playerID FROM fielding
        )
        ORDER BY playerID
        """
    ).fetchall()
    player_ids = [row[0] for row in player_ids_rows]
    print(f"Found {len(player_ids)} distinct players to index")

    # Process in batches
    batch_texts = []
    batch_ids = []
    batch_metas = []

    for idx, player_id in enumerate(player_ids):
        try:
            bio_text = build_player_bio(str(player_id), conn)
            record = player_profile_record(str(player_id), bio_text)
            batch_texts.append(record.text)
            batch_ids.append(record.id)
            batch_metas.append(record.metadata)
            manifest["generated_player_profiles"]["documents"].append(record.manifest_entry)
        except Exception as e:
            raise RuntimeError(f"Failed to build bio for {player_id}: {e}") from e

        # Print progress every 1000 players
        if (idx + 1) % 1000 == 0:
            print(f"  Processed {idx + 1}/{len(player_ids)} players...")

        # Flush batch when full
        if len(batch_texts) >= PLAYER_BATCH_SIZE:
            collection.add(documents=batch_texts, ids=batch_ids, metadatas=batch_metas)  # type: ignore[arg-type]
            total_docs += len(batch_texts)
            batch_texts = []
            batch_ids = []
            batch_metas = []

    # Flush any remaining players
    if batch_texts:
        collection.add(documents=batch_texts, ids=batch_ids, metadatas=batch_metas)  # type: ignore[arg-type]
        total_docs += len(batch_texts)

    finalize_manifest_counts(manifest)
    write_corpus_manifest(persist_dir, manifest)
    print(f"Indexed {total_docs} documents into {COLLECTION_NAME} at {persist_dir}")


_static_document_record = static_document_record
_player_profile_record = player_profile_record


def main(argv: list[str] | None = None) -> int:
    """Build the local Chroma corpus index."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--persist-dir", type=Path, default=Path("data"))
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="Index only checked-in Markdown corpus docs, not generated player bios.",
    )
    args = parser.parse_args(argv)
    build_index(args.persist_dir, include_players=not args.static_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
