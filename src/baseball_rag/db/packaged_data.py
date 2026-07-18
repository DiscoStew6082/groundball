"""Build-time integrity checks for immutable packaged data files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


def verify_manifest_file(manifest_path: Path, data_path: Path) -> None:
    """Raise when a packaged CSV differs from its manifest row count or digest."""
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [item for item in manifest["files"] if Path(item["path"]).name == data_path.name]
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one manifest entry for {data_path.name}, found {len(matches)}."
        )

    expected = matches[0]
    actual_sha256 = _sha256(data_path)
    if actual_sha256 != expected["sha256"]:
        raise ValueError(
            f"SHA-256 mismatch for {data_path}: expected {expected['sha256']}, got {actual_sha256}."
        )

    actual_rows = _csv_row_count(data_path)
    if actual_rows != expected["rows"]:
        raise ValueError(
            f"Row-count mismatch for {data_path}: expected {expected['rows']}, got {actual_rows}."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _csv_row_count(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as source:
        rows = csv.reader(source)
        next(rows, None)
        return sum(1 for _ in rows)


def main(argv: list[str] | None = None) -> int:
    """Verify one packaged CSV from the command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("data", type=Path)
    args = parser.parse_args(argv)
    verify_manifest_file(args.manifest, args.data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
