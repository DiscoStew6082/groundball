"""Diagnostics for checked-in corpus material."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from baseball_rag.corpus import get_hof_bios, get_stat_defs
from baseball_rag.corpus.lifecycle import (
    GENERATED_PLAYER_PROFILES_SECTION,
    MANIFEST_NAME,
    STATIC_DOCUMENTS_SECTION,
    manifest_section_count,
)
from baseball_rag.db.duckdb_schema import DATA_DIR


def corpus_diagnostics(corpus_dir: Path | None = None) -> dict[str, Any]:
    """Return tolerant diagnostics for checked-in corpus files and old manifests."""
    resolved_dir = Path(corpus_dir) if corpus_dir is not None else DATA_DIR
    manifest = _manifest_diagnostics(resolved_dir / MANIFEST_NAME)

    return {
        "corpus_dir": str(resolved_dir),
        "corpus_files": {
            "stat_definition_count": len(get_stat_defs()),
            "hof_bio_count": len(get_hof_bios()),
            "stat_definitions": [p.stem for p in get_stat_defs()],
            "hof_bios": [p.stem for p in get_hof_bios()],
        },
        "manifest": manifest,
        "runtime": {
            "index_required": False,
            "stat_explanations": "local_markdown_then_llm_fallback",
            "player_biographies": "llm_generated_duckdb_verified",
        },
    }


def diagnostics_json(corpus_dir: Path | None = None) -> str:
    """Return diagnostics as stable, pretty JSON."""
    return json.dumps(corpus_diagnostics(corpus_dir), indent=2, sort_keys=True)


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

    static_count = manifest_section_count(manifest, STATIC_DOCUMENTS_SECTION)
    generated_count = manifest_section_count(manifest, GENERATED_PLAYER_PROFILES_SECTION)
    diagnostics["generated_at"] = manifest.get("generated_at")
    diagnostics["static_document_count"] = static_count
    diagnostics["generated_player_profile_count"] = generated_count
    diagnostics["document_count"] = static_count + generated_count
    return diagnostics
