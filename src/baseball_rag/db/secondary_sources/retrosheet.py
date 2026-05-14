"""Download and describe Retrosheet CSV secondary-source data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol, TypedDict
from zoneinfo import ZoneInfo

import requests

from baseball_rag.db.duckdb_schema import DATA_DIR

RETROSHEET_DOWNLOAD_BASE_URL = "https://www.retrosheet.org/downloads"
RETROSHEET_ATTRIBUTION = (
    "The information used here was obtained free of charge from and is copyrighted "
    "by Retrosheet. Interested parties may contact Retrosheet at 20 Sunset Rd., "
    "Newark, DE 19711."
)
RETROSHEET_DATA_DIR = DATA_DIR / "secondary_sources" / "retrosheet"
MANIFEST_FILENAME = "manifest.json"


class _HttpResponse(Protocol):
    status_code: int

    def iter_content(self, chunk_size: int) -> Iterable[bytes]: ...


HttpGet = Callable[[str, int], _HttpResponse]


class YearCoverage(TypedDict):
    min: int | None
    max: int | None


class RetrosheetFileManifest(TypedDict):
    archive: str
    path: str
    source_url: str
    table: str
    kind: str
    rows: int
    year_coverage: YearCoverage
    sha256: str
    archive_sha256: str


@dataclass(frozen=True)
class RetrosheetArchive:
    archive_name: str
    csv_name: str
    table_name: str
    stat_table: bool

    @property
    def source_url(self) -> str:
        return f"{RETROSHEET_DOWNLOAD_BASE_URL}/{self.archive_name}"


ARCHIVES: tuple[RetrosheetArchive, ...] = (
    RetrosheetArchive("batting.zip", "batting.csv", "retrosheet_batting", True),
    RetrosheetArchive("pitching.zip", "pitching.csv", "retrosheet_pitching", True),
    RetrosheetArchive("fielding.zip", "fielding.csv", "retrosheet_fielding", True),
    RetrosheetArchive("biodata.zip", "biofile0.csv", "retrosheet_biofile", False),
)


def download_all(
    target_dir: Path | None = None,
    *,
    http_get: HttpGet | None = None,
    downloaded_at: str | None = None,
) -> Path:
    """Download the Retrosheet archives, extract them, and write a manifest."""
    target_dir = Path(target_dir or RETROSHEET_DATA_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    get = http_get or _requests_get

    for archive in ARCHIVES:
        _download_archive(archive, target_dir, get)

    return write_manifest(target_dir, downloaded_at=downloaded_at)


def write_manifest(target_dir: Path | None = None, *, downloaded_at: str | None = None) -> Path:
    """Write a Retrosheet manifest from locally extracted CSV files."""
    target_dir = Path(target_dir or RETROSHEET_DATA_DIR)
    timestamp = downloaded_at or datetime.now(ZoneInfo("America/New_York")).isoformat(
        timespec="seconds"
    )
    files = [_file_manifest(target_dir, archive) for archive in ARCHIVES]
    year_mins: list[int] = []
    year_maxes: list[int] = []
    for item in files:
        coverage = item["year_coverage"]
        if coverage["min"] is not None:
            year_mins.append(coverage["min"])
        if coverage["max"] is not None:
            year_maxes.append(coverage["max"])

    manifest = {
        "dataset": {
            "name": "Retrosheet CSV daily logs and biographical data",
            "source_url": "https://www.retrosheet.org/downloads/csvdownloads.html",
            "attribution": RETROSHEET_ATTRIBUTION,
            "license_notes": (
                "Retrosheet data is free to use with required attribution. Retrosheet "
                "makes no guarantees of accuracy and updates data as corrections arrive."
            ),
        },
        "download": {
            "downloaded_at": timestamp,
            "download_tool": "python -m baseball_rag.db.secondary_sources.retrosheet",
            "notes": "Only batting.zip, pitching.zip, fielding.zip, and biodata.zip are fetched.",
        },
        "coverage": {
            "year_coverage": {
                "min": min(year_mins) if year_mins else None,
                "max": max(year_maxes) if year_maxes else None,
            }
        },
        "files": files,
    }

    manifest_path = target_dir / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _download_archive(archive: RetrosheetArchive, target_dir: Path, http_get: HttpGet) -> None:
    response = http_get(archive.source_url, 60)
    if response.status_code != 200:
        raise RuntimeError(f"Failed to download {archive.source_url}: HTTP {response.status_code}")

    archive_path = target_dir / archive.archive_name
    with archive_path.open("wb") as output:
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                output.write(chunk)

    _extract_zip(archive_path, target_dir)


def _requests_get(url: str, timeout: int) -> requests.Response:
    return requests.get(url, timeout=timeout)


def _extract_zip(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            destination = (target_dir / member.filename).resolve()
            if not destination.is_relative_to(target_dir.resolve()):
                raise RuntimeError(
                    f"Refusing to extract unsafe Retrosheet member: {member.filename}"
                )
            archive.extract(member, target_dir)


def _file_manifest(target_dir: Path, archive: RetrosheetArchive) -> RetrosheetFileManifest:
    archive_path = target_dir / archive.archive_name
    csv_path = target_dir / archive.csv_name
    rows, year_coverage = _csv_metadata(csv_path)
    return {
        "archive": archive.archive_name,
        "path": f"data/secondary_sources/retrosheet/{archive.csv_name}",
        "source_url": archive.source_url,
        "table": archive.table_name,
        "kind": "stat" if archive.stat_table else "bio",
        "rows": rows,
        "year_coverage": year_coverage,
        "sha256": _sha256(csv_path),
        "archive_sha256": _sha256(archive_path),
    }


def _csv_metadata(path: Path) -> tuple[int, YearCoverage]:
    years: list[int] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = 0
        for row in reader:
            rows += 1
            year = _row_year(row)
            if year is not None:
                years.append(year)

    return rows, {
        "min": min(years) if years else None,
        "max": max(years) if years else None,
    }


def _row_year(row: dict[str, str]) -> int | None:
    for key in ("year", "Year", "season", "Season", "yearID"):
        value = row.get(key)
        if value and value.isdigit():
            return int(value)

    for key in ("date", "Date"):
        value = row.get(key, "")
        if len(value) >= 4 and value[:4].isdigit():
            return int(value[:4])

    gid = row.get("gid") or row.get("GID") or row.get("game_id") or row.get("gameID") or ""
    match = re.search(r"(18|19|20)\d{2}", gid)
    if match:
        return int(match.group(0))
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Download Retrosheet CSV secondary sources.")
    parser.add_argument("--data-dir", type=Path, default=RETROSHEET_DATA_DIR)
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Regenerate the Retrosheet manifest from existing extracted files.",
    )
    args = parser.parse_args()

    manifest_path = (
        write_manifest(args.data_dir) if args.manifest_only else download_all(args.data_dir)
    )
    print(f"Wrote {manifest_path}")


if __name__ == "__main__":
    main()
