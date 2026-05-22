"""Corpus frontmatter and legacy manifest helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def new_manifest() -> dict[str, Any]:
    """Return an empty legacy corpus manifest."""
    return {
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


def generated_player_profile_frontmatter(player_id: str, title: str) -> list[str]:
    """Return YAML frontmatter lines for a generated player profile document."""
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
    """Write a corpus lifecycle manifest."""
    persist_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = persist_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


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
