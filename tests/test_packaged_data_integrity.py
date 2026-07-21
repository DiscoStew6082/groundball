"""Immutable packaged data integrity checks."""

import hashlib
import json

import pytest

from baseball_rag.db.packaged_data import verify_manifest_file


def test_verify_manifest_file_checks_rows_and_sha256(tmp_path):
    data_path = tmp_path / "projection.csv"
    data_path.write_text("player,events\na,2\nb,3\n", encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": "data/secondary_sources/retrosheet/projection.csv",
                        "rows": 2,
                        "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    verify_manifest_file(manifest_path, data_path)

    data_path.write_text("player,events\na,99\nb,3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256"):
        verify_manifest_file(manifest_path, data_path)
