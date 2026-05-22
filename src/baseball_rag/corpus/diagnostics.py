"""Diagnostics for checked-in corpus material."""

import json
from typing import Any

from baseball_rag.corpus import HOF_DIR, STAT_DEFS_DIR, get_hof_bios, get_stat_defs


def corpus_diagnostics() -> dict[str, Any]:
    """Return diagnostics for checked-in corpus files."""

    return {
        "corpus_dir": str(STAT_DEFS_DIR.parent),
        "corpus_files": {
            "stat_definition_count": len(get_stat_defs()),
            "hof_bio_count": len(get_hof_bios()),
            "stat_definitions_dir": str(STAT_DEFS_DIR),
            "hof_dir": str(HOF_DIR),
            "stat_definitions": [p.stem for p in get_stat_defs()],
            "hof_bios": [p.stem for p in get_hof_bios()],
        },
        "runtime": {
            "index_required": False,
            "stat_explanations": "local_markdown_then_llm_fallback",
            "player_biographies": "llm_generated_duckdb_verified",
        },
    }


def diagnostics_json() -> str:
    """Return diagnostics as stable, pretty JSON."""
    return json.dumps(corpus_diagnostics(), indent=2, sort_keys=True)
