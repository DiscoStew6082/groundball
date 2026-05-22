"""Tests for corpus diagnostics."""

import json
import subprocess
import sys

from baseball_rag.corpus import STAT_DEFS_DIR
from baseball_rag.corpus.diagnostics import corpus_diagnostics


def test_corpus_diagnostics_reports_checked_in_corpus_without_manifest_state():
    diagnostics = corpus_diagnostics()

    assert diagnostics["corpus_dir"] == str(STAT_DEFS_DIR.parent)
    assert "manifest" not in diagnostics
    assert diagnostics["corpus_files"]["stat_definition_count"] == 10
    assert diagnostics["corpus_files"]["hof_bio_count"] == 5
    assert diagnostics["runtime"]["index_required"] is False
    assert diagnostics["runtime"]["stat_explanations"] == "local_markdown_then_llm_fallback"


def test_corpus_diagnostics_ignores_retired_manifest_counts(tmp_path):
    manifest = {
        "generated_at": "2026-05-14T00:00:00+00:00",
        "static_documents": {"count": 2, "documents": []},
        "generated_player_profiles": {"documents": [{"id": "player:ruthba01"}]},
    }
    (tmp_path / "corpus_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    diagnostics = corpus_diagnostics()

    assert "manifest" not in diagnostics


def test_corpus_diagnostics_cli_prints_json(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "baseball_rag.corpus",
            "diagnostics",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["corpus_dir"] == str(STAT_DEFS_DIR.parent)
    assert payload["runtime"]["player_biographies"] == "llm_generated_duckdb_verified"


def test_corpus_diagnostics_cli_rejects_retired_persist_dir_option(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "baseball_rag.corpus",
            "diagnostics",
            "--persist-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "--persist-dir" in result.stderr
