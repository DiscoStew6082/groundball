"""Corpus document records, manifest entries, and lifecycle conventions."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from baseball_rag.corpus.frontmatter import parse_frontmatter
from baseball_rag.db.duckdb_schema import DATA_DIR

COLLECTION_NAME = "baseball_corpus"
MANIFEST_NAME = "corpus_manifest.json"
GENERATED_PLAYER_PROFILE = "generated_player_profile"
PLAYER_BIOGRAPHY_CATEGORY = "player_biography"
STAT_DEFINITION_CATEGORY = "stat_definition"
HOF_BIO_CATEGORY = "hof_bio"
STATIC_DOCUMENTS_SECTION = "static_documents"
GENERATED_PLAYER_PROFILES_SECTION = "generated_player_profiles"
METADATA_CATEGORY = "category"
METADATA_DOC_KIND = "doc_kind"
METADATA_PLAYER_ID = "player_id"
METADATA_SOURCE_TABLES = "source_tables"
DEFAULT_PLAYER_SOURCE_TABLES = ["people", "batting", "pitching", "fielding"]


@dataclass(frozen=True)
class CorpusDocumentRecord:
    """Prepared Chroma document plus matching manifest entry."""

    text: str
    id: str
    metadata: dict[str, Any]
    manifest_entry: dict[str, Any]


def resolve_persist_dir(persist_dir: Path | None = None) -> Path:
    """Resolve the corpus persist directory without creating it."""
    if persist_dir is not None:
        return Path(persist_dir)
    env_path = os.environ.get("CHROMA_PERSIST_DIR")
    if env_path:
        return Path(env_path)
    return DATA_DIR


def new_manifest() -> dict[str, Any]:
    """Return an empty corpus lifecycle manifest."""
    return {
        "collection_name": COLLECTION_NAME,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        STATIC_DOCUMENTS_SECTION: {"count": 0, "documents": []},
        GENERATED_PLAYER_PROFILES_SECTION: {"count": 0, "documents": []},
    }


def finalize_manifest_counts(manifest: dict[str, Any]) -> None:
    """Update manifest count fields from document lists."""
    manifest[STATIC_DOCUMENTS_SECTION]["count"] = len(
        manifest[STATIC_DOCUMENTS_SECTION]["documents"]
    )
    manifest[GENERATED_PLAYER_PROFILES_SECTION]["count"] = len(
        manifest[GENERATED_PLAYER_PROFILES_SECTION]["documents"]
    )


def manifest_documents(manifest: dict[str, Any], section: str) -> list[dict[str, Any]]:
    """Return a mutable manifest document list, creating the section if needed."""
    value = manifest.setdefault(section, {"count": 0, "documents": []})
    if not isinstance(value, dict):
        manifest[section] = {"count": 0, "documents": []}
        value = manifest[section]
    documents = value.setdefault("documents", [])
    if not isinstance(documents, list):
        value["documents"] = []
        documents = value["documents"]
    return documents


def metadata_counts_key_missing() -> str:
    """Return the diagnostics bucket for absent metadata values."""
    return "missing"


def metadata_text(metadata: dict[str, Any] | Any, key: str) -> str | None:
    """Return a stripped metadata text value when present."""
    if not isinstance(metadata, dict):
        return None
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def category_filter(category: str) -> dict[str, str]:
    """Return a Chroma metadata filter for one corpus category."""
    return {METADATA_CATEGORY: category}


def player_id_filter(player_id: str) -> dict[str, str]:
    """Return a Chroma metadata filter for one generated player profile."""
    return {METADATA_PLAYER_ID: player_id}


def is_generated_player_profile_doc_kind(doc_kind: str | None) -> bool:
    """Return whether a metadata doc kind is a generated player profile."""
    return doc_kind == GENERATED_PLAYER_PROFILE


def generated_player_profile_frontmatter(player_id: str, title: str) -> list[str]:
    """Return YAML frontmatter lines for a generated player profile."""
    lines = [
        "---",
        f"title: {title}",
        f"{METADATA_PLAYER_ID}: {player_id}",
        f"{METADATA_CATEGORY}: {PLAYER_BIOGRAPHY_CATEGORY}",
        f"{METADATA_DOC_KIND}: {GENERATED_PLAYER_PROFILE}",
        f"{METADATA_SOURCE_TABLES}:",
    ]
    lines.extend(f"  - {table}" for table in DEFAULT_PLAYER_SOURCE_TABLES)
    lines.append("---")
    return lines


def write_corpus_manifest(persist_dir: Path, manifest: dict[str, Any]) -> None:
    """Write the corpus lifecycle manifest into the persist directory."""
    persist_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = persist_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def static_document_record(path: Path) -> CorpusDocumentRecord:
    """Build one validated static corpus record for Chroma and the manifest."""
    result = parse_frontmatter(path.read_text())
    metadata = result["metadata"]
    title = _required_text(metadata, "title", source=str(path))
    category = _required_text(metadata, METADATA_CATEGORY, source=str(path))
    manifest_entry = {
        "id": path.stem,
        "source": str(path.name),
        METADATA_CATEGORY: category,
        "title": title,
    }
    return CorpusDocumentRecord(
        text=f"{title}\n\n{result['body'].strip()}",
        id=path.stem,
        metadata={
            "source": str(path.name),
            METADATA_CATEGORY: category,
            "title": title,
        },
        manifest_entry=manifest_entry,
    )


def player_profile_record(player_id: str, bio_text: str) -> CorpusDocumentRecord:
    """Build one validated generated player profile record."""
    parsed = parse_frontmatter(bio_text)
    metadata = parsed["metadata"]
    title = _required_text(metadata, "title", source=player_id)
    metadata_player_id = _required_text(metadata, METADATA_PLAYER_ID, source=player_id)
    category = _required_text(metadata, METADATA_CATEGORY, source=player_id)
    doc_kind = _required_text(metadata, METADATA_DOC_KIND, source=player_id)
    if metadata_player_id != player_id:
        raise ValueError(
            f"generated player profile {player_id} frontmatter player_id "
            f"{metadata_player_id!r} does not match"
        )
    if category != PLAYER_BIOGRAPHY_CATEGORY:
        raise ValueError(f"generated player profile {player_id} has category {category!r}")
    if doc_kind != GENERATED_PLAYER_PROFILE:
        raise ValueError(f"generated player profile {player_id} has doc_kind {doc_kind!r}")

    source_tables = metadata.get(METADATA_SOURCE_TABLES)
    if not isinstance(source_tables, list) or not all(isinstance(t, str) for t in source_tables):
        raise ValueError(f"generated player profile {player_id} source_tables must be a list")

    return CorpusDocumentRecord(
        text=bio_text,
        id=f"player:{player_id}",
        metadata={
            "source": f"{player_id}.md",
            METADATA_CATEGORY: PLAYER_BIOGRAPHY_CATEGORY,
            "title": title,
            METADATA_PLAYER_ID: player_id,
            METADATA_DOC_KIND: GENERATED_PLAYER_PROFILE,
            METADATA_SOURCE_TABLES: ",".join(source_tables),
        },
        manifest_entry={
            "id": f"player:{player_id}",
            "source": f"{player_id}.md",
            METADATA_CATEGORY: PLAYER_BIOGRAPHY_CATEGORY,
            "title": title,
            METADATA_PLAYER_ID: player_id,
            METADATA_DOC_KIND: GENERATED_PLAYER_PROFILE,
            METADATA_SOURCE_TABLES: source_tables,
        },
    )


def manifest_section_count(manifest: dict[str, Any], key: str) -> int:
    """Return a tolerant document count for one manifest section."""
    section = manifest.get(key)
    if not isinstance(section, dict):
        return 0
    count = section.get("count")
    if isinstance(count, int):
        return count
    documents = section.get("documents")
    return len(documents) if isinstance(documents, list) else 0


def _required_text(metadata: dict[str, Any], key: str, *, source: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{source} missing required frontmatter field {key!r}")
    return value.strip()
