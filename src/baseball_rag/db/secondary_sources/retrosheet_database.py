"""Build a local DuckDB cache for Retrosheet CSV daily logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from baseball_rag.db.duckdb_schema import RETROSHEET_DATABASE_FILENAME
from baseball_rag.db.secondary_sources.retrosheet import (
    ARCHIVES,
    MANIFEST_FILENAME,
    RETROSHEET_DATA_DIR,
    _sha256,
    write_manifest,
)

CACHE_SCHEMA_VERSION = "1"


def build_database(
    target_dir: Path | None = None,
    *,
    database_path: Path | None = None,
    update_manifest: bool = False,
) -> Path:
    """Build a query-optimized DuckDB cache from local Retrosheet archives."""
    target_dir = Path(target_dir or RETROSHEET_DATA_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    database_path = Path(database_path or target_dir / RETROSHEET_DATABASE_FILENAME)
    if database_path.exists():
        database_path.unlink()

    conn = duckdb.connect(str(database_path))
    try:
        for archive in ARCHIVES:
            with _csv_source_path(target_dir, archive.archive_name, archive.csv_name) as csv_path:
                conn.execute(
                    f"""
                    CREATE TABLE {archive.table_name} AS
                    SELECT *
                    FROM read_csv_auto('{_sql_string(csv_path)}', all_varchar=true)
                    """
                )
        _write_cache_metadata_table(conn, target_dir)
        conn.execute("CHECKPOINT")
    finally:
        conn.close()
    if update_manifest:
        _write_cache_manifest_metadata(target_dir, database_path)
    return database_path


def _write_cache_metadata_table(conn: duckdb.DuckDBPyConnection, target_dir: Path) -> None:
    archive_hashes = _source_archive_hashes(target_dir)
    conn.execute("CREATE TABLE retrosheet_cache_metadata (key TEXT, value TEXT)")
    conn.executemany(
        "INSERT INTO retrosheet_cache_metadata VALUES (?, ?)",
        [
            ("schema_version", CACHE_SCHEMA_VERSION),
            ("source_archive_sha256", json.dumps(archive_hashes, sort_keys=True)),
            ("tables", json.dumps([archive.table_name for archive in ARCHIVES])),
        ],
    )


def _write_cache_manifest_metadata(target_dir: Path, database_path: Path) -> None:
    manifest_path = target_dir / MANIFEST_FILENAME
    if not manifest_path.exists():
        write_manifest(target_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cache"] = {
        "database": {
            "path": f"data/secondary_sources/retrosheet/{database_path.name}",
            "built_at": datetime.now(ZoneInfo("America/New_York")).isoformat(timespec="seconds"),
            "schema_version": CACHE_SCHEMA_VERSION,
            "tables": [archive.table_name for archive in ARCHIVES],
            "source_archive_sha256": _source_archive_hashes(target_dir),
            "sha256": _file_sha256(database_path),
        }
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _source_archive_hashes(target_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for archive in ARCHIVES:
        archive_path = target_dir / archive.archive_name
        if archive_path.exists():
            hashes[archive.archive_name] = _sha256(archive_path)
    return hashes


@contextmanager
def _csv_source_path(target_dir: Path, archive_name: str, csv_name: str) -> Iterator[Path]:
    archive_path = target_dir / archive_name
    loose_csv_path = target_dir / csv_name
    if not archive_path.exists():
        if not loose_csv_path.exists():
            raise FileNotFoundError(
                f"Retrosheet source is missing: expected {archive_path} or {loose_csv_path}"
            )
        yield loose_csv_path
        return

    with tempfile.TemporaryDirectory(prefix="groundball-retrosheet-build-") as temp_dir:
        temp_path = Path(temp_dir)
        with zipfile.ZipFile(archive_path) as archive:
            member = archive.getinfo(csv_name)
            destination = (temp_path / member.filename).resolve()
            if not destination.is_relative_to(temp_path.resolve()):
                raise RuntimeError(
                    f"Refusing to extract unsafe Retrosheet member: {member.filename}"
                )
            archive.extract(member, temp_path)
        yield destination


def _sql_string(path: Path) -> str:
    return str(path).replace("'", "''")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a Retrosheet DuckDB cache.")
    parser.add_argument("--data-dir", type=Path, default=RETROSHEET_DATA_DIR)
    parser.add_argument("--database", type=Path, default=None)
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        help="Record local cache metadata in the Retrosheet manifest.",
    )
    args = parser.parse_args()

    database_path = build_database(
        args.data_dir,
        database_path=args.database,
        update_manifest=args.update_manifest,
    )
    print(f"Wrote {database_path}")


if __name__ == "__main__":
    main()
