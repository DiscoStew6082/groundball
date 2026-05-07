"""Diagnostics for the local baseball corpus index."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

import chromadb

from baseball_rag.corpus import get_hof_bios, get_stat_defs
from baseball_rag.corpus.lifecycle import (
    COLLECTION_NAME,
    MANIFEST_NAME,
    manifest_section_count,
    resolve_persist_dir,
)
from baseball_rag.embedder import DEFAULT_BASE_URL, DEFAULT_EMBEDDING_MODEL


def corpus_diagnostics(persist_dir: Path | None = None) -> dict[str, Any]:
    """Return tolerant diagnostics for the static corpus and Chroma index."""
    resolved_dir = resolve_persist_dir(persist_dir)
    manifest = _manifest_diagnostics(resolved_dir / MANIFEST_NAME)
    collection = _collection_diagnostics(resolved_dir)

    return {
        "persist_dir": str(resolved_dir),
        "corpus_files": {
            "stat_definition_count": len(get_stat_defs()),
            "hof_bio_count": len(get_hof_bios()),
            "stat_definitions": [p.stem for p in get_stat_defs()],
            "hof_bios": [p.stem for p in get_hof_bios()],
        },
        "chroma_collection": collection,
        "manifest": manifest,
        "environment": {
            "CHROMA_PERSIST_DIR": os.environ.get("CHROMA_PERSIST_DIR"),
            "LMSTUDIO_BASE_URL": os.environ.get("LMSTUDIO_BASE_URL"),
            "LMSTUDIO_EMBEDDING_MODEL": os.environ.get("LMSTUDIO_EMBEDDING_MODEL"),
        },
        "model_hints": {
            "embedding_base_url": os.environ.get("LMSTUDIO_BASE_URL", DEFAULT_BASE_URL),
            "embedding_model": os.environ.get("LMSTUDIO_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        },
    }


def diagnostics_json(persist_dir: Path | None = None) -> str:
    """Return diagnostics as stable, pretty JSON."""
    return json.dumps(corpus_diagnostics(persist_dir), indent=2, sort_keys=True)


def _collection_diagnostics(persist_dir: Path) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "name": COLLECTION_NAME,
        "persist_dir_exists": persist_dir.exists(),
        "exists": False,
        "indexed_count": 0,
        "category_counts": {},
        "doc_kind_counts": {},
        "error": None,
    }

    if not persist_dir.exists():
        return diagnostics

    try:
        client = chromadb.PersistentClient(path=str(persist_dir))
        collection = client.get_collection(COLLECTION_NAME)
        indexed_count = collection.count()
        metadatas = _collection_metadatas(collection, indexed_count)
    except Exception as exc:  # noqa: BLE001 - Chroma errors vary by version/state
        diagnostics["error"] = f"{type(exc).__name__}: {exc}"
        return diagnostics

    diagnostics["exists"] = True
    diagnostics["indexed_count"] = indexed_count
    diagnostics["category_counts"] = _metadata_counts(metadatas, "category")
    diagnostics["doc_kind_counts"] = _metadata_counts(metadatas, "doc_kind")
    return diagnostics


def _collection_metadatas(collection: Any, indexed_count: int) -> list[dict[str, Any]]:
    if indexed_count <= 0:
        return []
    try:
        result = collection.get(limit=indexed_count, include=["metadatas"])
    except Exception:
        return []
    return [m for m in result.get("metadatas", []) if isinstance(m, dict)]


def _metadata_counts(metadatas: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts = Counter(str(metadata.get(key) or "missing") for metadata in metadatas)
    return dict(sorted(counts.items()))


def _manifest_diagnostics(path: Path) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "document_count": 0,
        "static_document_count": 0,
        "generated_player_profile_count": 0,
        "error": None,
    }
    if not path.exists():
        return diagnostics

    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - keep diagnostics useful for corrupt files
        diagnostics["error"] = f"{type(exc).__name__}: {exc}"
        return diagnostics

    static_count = manifest_section_count(manifest, "static_documents")
    generated_count = manifest_section_count(manifest, "generated_player_profiles")
    diagnostics["collection_name"] = manifest.get("collection_name")
    diagnostics["generated_at"] = manifest.get("generated_at")
    diagnostics["static_document_count"] = static_count
    diagnostics["generated_player_profile_count"] = generated_count
    diagnostics["document_count"] = static_count + generated_count
    return diagnostics
