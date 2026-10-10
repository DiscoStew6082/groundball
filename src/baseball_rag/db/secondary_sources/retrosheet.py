"""Download and describe Retrosheet CSV secondary-source data."""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import io
import json
import re
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable, NotRequired, Protocol, TypedDict
from zoneinfo import ZoneInfo

import requests

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.db.ingestion_limits import (
    DEFAULT_LIMITS,
    bounded_text_lines,
    bounded_zip,
    copy_bounded,
    install_staged_files,
    validate_archive,
)

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
    archive: NotRequired[str]
    path: str
    source_url: str
    table: str
    kind: str
    rows: int
    year_coverage: YearCoverage
    sha256: str
    archive_sha256: NotRequired[str]


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

# Official biodata.zip includes these companion CSVs. They are not extracted.
BIODATA_MEMBERS = frozenset(
    {
        "ballparks0.csv",
        "biofile0.csv",
        "coaches0.csv",
        "managers0.csv",
        "relatives.csv",
        "teams0.csv",
        "umpires0.csv",
    }
)


def _validate_raw_members(archive: zipfile.ZipFile, expected_name: str) -> None:
    members = validate_archive(archive, DEFAULT_LIMITS)
    names = {member.filename for member in members}
    allowed = BIODATA_MEMBERS if expected_name == "biofile0.csv" else {expected_name}
    if (
        expected_name not in names
        or not names <= allowed
        or any(member.is_dir() for member in members)
    ):
        raise RuntimeError("Retrosheet archive must contain only expected CSV members")


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

    with TemporaryDirectory(prefix=".retrosheet-", dir=target_dir.parent) as temporary:
        staging = Path(temporary)
        # Governed local derivation is never supplied by a raw-source archive.
        derived_name = "pitcher_strikeout_side_events.csv"
        if (target_dir / derived_name).exists():
            with (
                (target_dir / derived_name).open("rb") as source,
                (staging / derived_name).open("wb") as output,
            ):
                copy_bounded(
                    iter(lambda: source.read(8192), b""), output, DEFAULT_LIMITS.member_bytes
                )
        for archive in ARCHIVES:
            _download_archive(archive, staging, get)
        write_manifest(staging, downloaded_at=downloaded_at)
        names = [name for archive in ARCHIVES for name in (archive.archive_name, archive.csv_name)]
        install_staged_files(staging, target_dir, [*names, MANIFEST_FILENAME])
    return target_dir / MANIFEST_FILENAME


def write_manifest(target_dir: Path | None = None, *, downloaded_at: str | None = None) -> Path:
    """Write a Retrosheet manifest from locally extracted CSV files."""
    target_dir = Path(target_dir or RETROSHEET_DATA_DIR)
    timestamp = downloaded_at or datetime.now(ZoneInfo("America/New_York")).isoformat(
        timespec="seconds"
    )
    files = [_file_manifest(target_dir, archive) for archive in ARCHIVES]
    files.extend(_existing_derived_file_manifests(target_dir))
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
            "name": "Retrosheet CSV daily logs and local derived projections",
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
            "notes": (
                "Fetched batting.zip, pitching.zip, fielding.zip, and biodata.zip; "
                "preserves existing local Retrosheet-derived projection entries."
            ),
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
    try:
        with archive_path.open("wb") as output:
            copy_bounded(
                response.iter_content(chunk_size=8192), output, DEFAULT_LIMITS.download_bytes
            )
        _extract_zip(archive_path, target_dir, archive.csv_name)
    finally:
        close = getattr(response, "close", None)
        if close is not None:
            close()


def _requests_get(url: str, timeout: int) -> requests.Response:
    return requests.get(url, timeout=timeout, stream=True)


def _extract_zip(archive_path: Path, target_dir: Path, expected_name: str) -> None:
    with bounded_zip(archive_path, DEFAULT_LIMITS) as archive:
        _validate_raw_members(archive, expected_name)
        with (
            archive.open(expected_name) as source,
            (target_dir / expected_name).open("wb") as output,
        ):
            copy_bounded(iter(lambda: source.read(8192), b""), output, DEFAULT_LIMITS.member_bytes)


def _file_manifest(target_dir: Path, archive: RetrosheetArchive) -> RetrosheetFileManifest:
    archive_path = target_dir / archive.archive_name
    csv_path = target_dir / archive.csv_name
    rows, year_coverage = _csv_metadata(csv_path, archive_path, archive.csv_name)
    local_path = archive_path if archive_path.exists() else csv_path
    return {
        "archive": archive.archive_name,
        "path": f"data/secondary_sources/retrosheet/{local_path.name}",
        "source_url": archive.source_url,
        "table": archive.table_name,
        "kind": "stat" if archive.stat_table else "bio",
        "rows": rows,
        "year_coverage": year_coverage,
        "sha256": _csv_sha256(csv_path, archive_path, archive.csv_name),
        "archive_sha256": _sha256(archive_path) if archive_path.exists() else "",
    }


def _existing_derived_file_manifests(target_dir: Path) -> list[RetrosheetFileManifest]:
    path = target_dir / "pitcher_strikeout_side_events.csv"
    if not path.exists():
        return []
    rows, coverage = _csv_metadata(path, None, path.name)
    return [
        {
            "path": f"data/secondary_sources/retrosheet/{path.name}",
            "source_url": "https://www.retrosheet.org/events/",
            "table": "retrosheet_pitcher_strikeout_side_events",
            "kind": "event_derived_evidence",
            "rows": rows,
            "year_coverage": coverage,
            "sha256": _sha256(path),
        }
    ]


def _csv_metadata(
    path: Path, archive_path: Path | None, member_name: str
) -> tuple[int, YearCoverage]:
    min_year: int | None = None
    max_year: int | None = None
    with _open_csv_text(path, archive_path, member_name) as f:
        reader = csv.DictReader(bounded_text_lines(f))
        if not reader.fieldnames or len(reader.fieldnames) > 256:
            raise RuntimeError("Invalid Retrosheet CSV header")
        if not {"gid", "id", "retroID"}.intersection(reader.fieldnames):
            raise RuntimeError("Invalid Retrosheet CSV identity header")
        rows = 0
        for row in reader:
            rows += 1
            if rows > DEFAULT_LIMITS.rows or None in row or None in row.values():
                raise RuntimeError("Retrosheet CSV exceeds row budget or has invalid rows")
            year = _row_year(row)
            if year is not None:
                min_year = year if min_year is None else min(min_year, year)
                max_year = year if max_year is None else max(max_year, year)

    return rows, {
        "min": min_year,
        "max": max_year,
    }


@contextlib.contextmanager
def _open_csv_text(path: Path, archive_path: Path | None, member_name: str):
    if archive_path is not None and archive_path.exists():
        if archive_path.stat().st_size > DEFAULT_LIMITS.download_bytes:
            raise RuntimeError("Retrosheet archive exceeds byte budget")
        with bounded_zip(archive_path, DEFAULT_LIMITS) as archive:
            _validate_raw_members(archive, member_name)
            with archive.open(member_name) as raw:
                with io.TextIOWrapper(raw, encoding="utf-8", newline="") as f:
                    yield f
        return
    if path.stat().st_size > DEFAULT_LIMITS.member_bytes:
        raise RuntimeError("Retrosheet CSV exceeds byte budget")
    with path.open(newline="", encoding="utf-8") as f:
        yield f


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


def _csv_sha256(path: Path, archive_path: Path, member_name: str) -> str:
    if archive_path.exists():
        digest = hashlib.sha256()
        with bounded_zip(archive_path, DEFAULT_LIMITS) as archive:
            with archive.open(member_name) as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()
    return _sha256(path)


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
