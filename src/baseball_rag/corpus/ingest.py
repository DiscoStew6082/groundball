"""Build a ChromaDB vector index from corpus documents."""

import argparse
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import chromadb

from baseball_rag.corpus import get_hof_bios, get_stat_defs
from baseball_rag.corpus.frontmatter import parse_frontmatter
from baseball_rag.corpus.player_bios import build_player_bio
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.retrieval.chroma_store import LMStudioEmbeddingFunction

# Batch size for ChromaDB inserts when indexing players
PLAYER_BATCH_SIZE = 500


@dataclass(frozen=True)
class CorpusDocumentRecord:
    """Prepared Chroma document plus matching manifest entry."""

    text: str
    id: str
    metadata: dict
    manifest_entry: dict


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
        client.delete_collection("baseball_corpus")
    except Exception:
        pass

    collection = client.create_collection(
        name="baseball_corpus",
        embedding_function=LMStudioEmbeddingFunction(),  # type: ignore[arg-type]
        metadata={
            "description": (
                "Baseball stat definitions, Hall of Fame biographies, and player biographies"
            )
        },
    )

    total_docs = 0
    manifest = _new_manifest()

    # Index static corpus docs (stat_defs and hof_bios)
    static_texts = []
    static_ids = []
    static_metas = []

    for path in [*get_stat_defs(), *get_hof_bios()]:
        record = _static_document_record(path)
        static_texts.append(record.text)
        static_ids.append(record.id)
        static_metas.append(record.metadata)
        manifest["static_documents"]["documents"].append(record.manifest_entry)

    if static_texts:
        collection.add(documents=static_texts, ids=static_ids, metadatas=static_metas)  # type: ignore[arg-type]
        total_docs += len(static_texts)

    if not include_players:
        _finalize_manifest_counts(manifest)
        _write_corpus_manifest(persist_dir, manifest)
        print(f"Indexed {total_docs} documents into baseball_corpus at {persist_dir}")
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
            record = _player_profile_record(str(player_id), bio_text)
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

    _finalize_manifest_counts(manifest)
    _write_corpus_manifest(persist_dir, manifest)
    print(f"Indexed {total_docs} documents into baseball_corpus at {persist_dir}")


def _new_manifest() -> dict:
    return {
        "collection_name": "baseball_corpus",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "static_documents": {"count": 0, "documents": []},
        "generated_player_profiles": {"count": 0, "documents": []},
    }


def _finalize_manifest_counts(manifest: dict) -> None:
    manifest["static_documents"]["count"] = len(manifest["static_documents"]["documents"])
    manifest["generated_player_profiles"]["count"] = len(
        manifest["generated_player_profiles"]["documents"]
    )


def _static_document_record(path: Path) -> CorpusDocumentRecord:
    result = parse_frontmatter(path.read_text())
    metadata = result["metadata"]
    manifest_entry = {
        "id": path.stem,
        "source": str(path.name),
        "category": metadata.get("category", ""),
        "title": metadata.get("title", ""),
    }
    return CorpusDocumentRecord(
        text=f"{metadata['title']}\n\n{result['body'].strip()}",
        id=path.stem,
        metadata={
            "source": str(path.name),
            "category": metadata.get("category", ""),
            "title": metadata.get("title", ""),
        },
        manifest_entry=manifest_entry,
    )


def _player_profile_record(player_id: str, bio_text: str) -> CorpusDocumentRecord:
    parsed = parse_frontmatter(bio_text)
    metadata = parsed["metadata"]
    source_tables = metadata.get(
        "source_tables",
        ["people", "batting", "pitching", "fielding"],
    )
    return CorpusDocumentRecord(
        text=bio_text,
        id=f"player:{player_id}",
        metadata={
            "source": f"{player_id}.md",
            "category": "player_biography",
            "title": str(metadata.get("title", player_id)),
            "player_id": str(player_id),
            "doc_kind": "generated_player_profile",
            "source_tables": "people,batting,pitching,fielding",
        },
        manifest_entry={
            "id": f"player:{player_id}",
            "source": f"{player_id}.md",
            "category": "player_biography",
            "title": str(metadata.get("title", player_id)),
            "player_id": str(player_id),
            "doc_kind": "generated_player_profile",
            "source_tables": source_tables,
        },
    )


def _write_corpus_manifest(persist_dir: Path, manifest: dict) -> None:
    persist_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = persist_dir / "corpus_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


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
