"""Download utilities for NeuML/baseballdata CSVs."""

import argparse
import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import requests

DATA_FILES = ["Batting.csv", "Fielding.csv", "People.csv", "Pitching.csv"]
BASE_URL = "https://huggingface.co/datasets/NeuML/baseballdata/resolve/main"
# Project root: go up 4 levels — download.py -> db/ -> baseball_rag/ -> src/ -> repo/
PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = PROJECT_ROOT / "data"
MANIFEST_PATH = DATA_DIR / "manifest.json"


def download_csv(filename: str, db_dir: Path) -> Path:
    """Download a single CSV from the NeuML/baseballdata HuggingFace repo.

    Args:
        filename: Name of the CSV file (e.g. 'Batting.csv').
        db_dir: Directory to save the file in.

    Returns:
        Path to the downloaded file.

    Raises:
        RuntimeError: If the HTTP response is not 200.
    """
    url = f"{BASE_URL}/{filename}"
    dest = db_dir / filename

    response = requests.get(url, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to download {url}: HTTP {response.status_code}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)

    return dest


def download_all(db_dir: Path | None = None) -> list[Path]:
    """Download all four NeuML/baseballdata CSVs.

    Args:
        db_dir: Target directory. Defaults to project data/ dir.

    Returns:
        List of paths to the downloaded files.
    """
    if db_dir is None:
        db_dir = DATA_DIR

    paths = [download_csv(fname, Path(db_dir)) for fname in DATA_FILES]
    write_manifest(Path(db_dir), paths=paths)
    return paths


def write_manifest(db_dir: Path | None = None, *, paths: list[Path] | None = None) -> Path:
    """Write data/manifest.json from local CSV files."""
    if db_dir is None:
        db_dir = DATA_DIR
    db_dir = Path(db_dir)
    if paths is None:
        paths = [db_dir / fname for fname in DATA_FILES]

    generated_at = datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds")
    files = [_file_manifest(path) for path in paths]
    year_mins = [
        item["year_coverage"]["min"]
        for item in files
        if isinstance(item.get("year_coverage"), dict)
    ]
    year_maxes = [
        item["year_coverage"]["max"]
        for item in files
        if isinstance(item.get("year_coverage"), dict)
    ]

    manifest = {
        "dataset": {
            "name": "NeuML/baseballdata",
            "description": (
                "Copy of the Lahman Baseball Database used for local DuckDB-backed "
                "baseball statistics."
            ),
            "source_url": "https://huggingface.co/datasets/NeuML/baseballdata",
            "base_download_url": BASE_URL,
            "upstream": "Lahman Baseball Database",
            "release_id": "neuml-baseballdata:lahman-2025:2026-01-11",
            "upstream_release": "Version 2025, released 2026-01-02",
            "hugging_face_last_updated": "2026-01-11",
            "license": "CC BY-SA 3.0",
            "license_url": "https://creativecommons.org/licenses/by-sa/3.0/",
            "license_notes": (
                "Hugging Face metadata identifies the dataset license as cc-by-sa-3.0. "
                "Preserve attribution to Lahman Baseball Database / NeuML and share "
                "adaptations under compatible terms."
            ),
        },
        "download": {
            "downloaded_at": generated_at,
            "download_tool": "python -m baseball_rag.db.download",
            "notes": "Manifest generated from local CSV files.",
        },
        "coverage": {
            "structured_stat_years": {
                "min": min(year_mins) if year_mins else None,
                "max": max(year_maxes) if year_maxes else None,
            },
            "notes": (
                "Year coverage is computed from Batting.csv, Fielding.csv, and "
                "Pitching.csv yearID columns. People.csv has no yearID column."
            ),
        },
        "files": files,
    }

    manifest_path = db_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _file_manifest(path: Path) -> dict:
    table = path.stem.lower()
    row_count, year_coverage = _csv_metadata(path)
    return {
        "path": f"data/{path.name}",
        "source_url": f"{BASE_URL}/{path.name}",
        "table": table,
        "rows": row_count,
        "year_coverage": year_coverage,
        "sha256": _sha256(path),
    }


def _csv_metadata(path: Path) -> tuple[int, dict[str, int] | None]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
    conn = duckdb.connect()
    try:
        row_count_result = conn.execute(f"SELECT count(*) FROM read_csv_auto('{path}')").fetchone()
        if row_count_result is None:
            raise RuntimeError(f"Could not count rows in {path}")
        row_count = row_count_result[0]
        if "yearID" not in header:
            return int(row_count), None
        year_result = conn.execute(
            f"SELECT min(yearID), max(yearID) FROM read_csv_auto('{path}')"
        ).fetchone()
        if year_result is None:
            raise RuntimeError(f"Could not compute year coverage for {path}")
        min_year, max_year = year_result
        return int(row_count), {"min": int(min_year), "max": int(max_year)}
    finally:
        conn.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Download baseball CSVs and write manifest.")
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Regenerate data/manifest.json from existing CSV files without downloading.",
    )
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args()

    if args.manifest_only:
        path = write_manifest(args.data_dir)
        print(f"Wrote {path}")
    else:
        paths = download_all(args.data_dir)
        print(f"Downloaded {len(paths)} CSV files to {args.data_dir}")
        print(f"Wrote {args.data_dir / 'manifest.json'}")


if __name__ == "__main__":
    main()
