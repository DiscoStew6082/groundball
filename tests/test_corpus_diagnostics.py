"""Tests for corpus diagnostics."""

import json
import subprocess
import sys

from baseball_rag.corpus.diagnostics import corpus_diagnostics


def test_corpus_diagnostics_tolerates_missing_manifest(tmp_path):
    diagnostics = corpus_diagnostics(tmp_path / "missing")

    assert diagnostics["corpus_dir"] == str(tmp_path / "missing")
    assert diagnostics["manifest"]["exists"] is False
    assert diagnostics["corpus_files"]["stat_definition_count"] == 10
    assert diagnostics["corpus_files"]["hof_bio_count"] == 5
    assert diagnostics["runtime"]["index_required"] is False
    assert diagnostics["runtime"]["stat_explanations"] == "llm_open_answer"


def test_corpus_diagnostics_reads_legacy_manifest_counts(tmp_path):
    manifest = {
        "generated_at": "2026-05-14T00:00:00+00:00",
        "static_documents": {"count": 2, "documents": []},
        "generated_player_profiles": {"documents": [{"id": "player:ruthba01"}]},
    }
    (tmp_path / "corpus_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    diagnostics = corpus_diagnostics(tmp_path)

    assert diagnostics["manifest"]["exists"] is True
    assert diagnostics["manifest"]["static_document_count"] == 2
    assert diagnostics["manifest"]["generated_player_profile_count"] == 1
    assert diagnostics["manifest"]["document_count"] == 3


def test_corpus_diagnostics_cli_prints_json(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "baseball_rag.corpus",
            "diagnostics",
            "--persist-dir",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert payload["corpus_dir"] == str(tmp_path)
    assert payload["runtime"]["player_biographies"] == "llm_generated_duckdb_verified"
