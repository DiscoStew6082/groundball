"""Canonical release identity for packaged query data."""

from __future__ import annotations

import hashlib
import json


def semantic_manifest_sha256(manifest: dict[str, object]) -> str:
    """Hash release-bearing data identity while excluding acquisition metadata."""
    dataset = manifest.get("dataset")
    files = manifest.get("files")
    if not isinstance(dataset, dict) or not isinstance(files, list):
        raise ValueError("Data manifest must contain dataset and files records.")
    semantic_files = []
    for item in files:
        if not isinstance(item, dict):
            raise ValueError("Data manifest file records must be objects.")
        semantic_files.append(
            {
                "path": item.get("path"),
                "table": item.get("table"),
                "rows": item.get("rows"),
                "year_coverage": item.get("year_coverage"),
                "sha256": item.get("sha256"),
            }
        )
    payload = {
        "release_id": dataset.get("release_id"),
        "files": sorted(semantic_files, key=lambda item: str(item["table"])),
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
