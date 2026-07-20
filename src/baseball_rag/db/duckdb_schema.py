"""DuckDB CSV schema setup — zero-ingestion queries over NeuML/baseballdata CSVs."""

import hashlib
import json
import os
import tempfile
import threading
import zipfile
from pathlib import Path

import duckdb

# Module-level singleton connection with double-checked locking for thread safety.
_cached_conn: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()

# Project root: go up 4 levels — lahman.py -> db/ -> baseball_rag/ -> src/ -> repo/
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = REPOSITORY_ROOT / "data"
RETROSHEET_TEAM_REFERENCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "query"
    / "catalog"
    / "assets"
    / "retrosheet_team_reference.csv"
)
RETROSHEET_TEAM_REFERENCE_MANIFEST_PATH = RETROSHEET_TEAM_REFERENCE_PATH.with_suffix(
    ".manifest.json"
)
RETROSHEET_DATA_SUBDIR = Path("secondary_sources") / "retrosheet"
RETROSHEET_STAT_TABLES = {
    "retrosheet_batting": "batting.csv",
    "retrosheet_pitching": "pitching.csv",
    "retrosheet_fielding": "fielding.csv",
}
RETROSHEET_ARCHIVES = {
    "batting.csv": "batting.zip",
    "pitching.csv": "pitching.zip",
    "fielding.csv": "fielding.zip",
    "biofile0.csv": "biodata.zip",
}
RETROSHEET_DATABASE_FILENAME = "retrosheet.duckdb"
RETROSHEET_DERIVED_TABLES = {
    "retrosheet_pitcher_strikeout_side_events": "pitcher_strikeout_side_events.csv",
}
RETROSHEET_BIOFILE = ("retrosheet_biofile", "biofile0.csv")
RETROSHEET_EXTRACT_DIR_ENV = "BASEBALL_RAG_RETROSHEET_EXTRACT_DIR"


def get_duckdb() -> duckdb.DuckDBPyConnection:
    """Return a shared in-memory DuckDB connection, creating it on first call.

    Thread-safe singleton using double-checked locking. The connection is
    reused across all calls — callers must NOT close it.
    """
    global _cached_conn

    if _cached_conn is not None:
        try:
            _cached_conn.execute("SELECT 1")
            return _cached_conn
        except Exception:
            # Connection was closed; discard it and fall through to recreate.
            _cached_conn = None

    with _lock:
        # Check again after acquiring the lock (double-checked locking pattern).
        if _cached_conn is None:
            conn = duckdb.connect(database=":memory:", read_only=False)

            # Register CSVs via read_csv_auto
            batting_path = str(DATA_DIR / "Batting.csv")
            fielding_path = str(DATA_DIR / "Fielding.csv")
            people_path = str(DATA_DIR / "People.csv")
            pitching_path = str(DATA_DIR / "Pitching.csv")

            conn.execute(f"CREATE TABLE batting AS SELECT * FROM read_csv_auto('{batting_path}')")
            conn.execute(f"CREATE TABLE fielding AS SELECT * FROM read_csv_auto('{fielding_path}')")
            conn.execute(f"CREATE TABLE people AS SELECT * FROM read_csv_auto('{people_path}')")
            conn.execute(f"CREATE TABLE pitching AS SELECT * FROM read_csv_auto('{pitching_path}')")
            _load_optional_retrosheet_tables(conn, DATA_DIR)

            _load_retrosheet_team_reference(conn)

            # Assign to module-level singleton (global declared at function top).
            _cached_conn = conn

        return _cached_conn


def _load_retrosheet_team_reference(conn: duckdb.DuckDBPyConnection) -> None:
    manifest = json.loads(RETROSHEET_TEAM_REFERENCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    observed = hashlib.sha256(RETROSHEET_TEAM_REFERENCE_PATH.read_bytes()).hexdigest()
    if observed != manifest["sha256"]:
        raise ValueError("Retrosheet team-reference checksum does not match its manifest.")
    conn.execute(
        "CREATE TABLE retrosheet_team_reference AS SELECT * FROM read_csv_auto(?)",
        [str(RETROSHEET_TEAM_REFERENCE_PATH)],
    )


def _load_optional_retrosheet_tables(conn: duckdb.DuckDBPyConnection, data_dir: Path) -> None:
    retrosheet_dir = data_dir / RETROSHEET_DATA_SUBDIR
    if not retrosheet_dir.exists():
        return

    cached_tables = _load_retrosheet_database_tables(conn, retrosheet_dir)

    for table_name, csv_name in RETROSHEET_STAT_TABLES.items():
        if table_name in cached_tables:
            continue
        csv_path = _ensure_retrosheet_csv(retrosheet_dir, csv_name)
        if csv_path.exists():
            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM read_csv_auto('{_sql_string(csv_path)}', all_varchar=true)
                WHERE lower(stattype) = 'value'
                  AND lower(gametype) IN ('regular', 'playoff')
                """
            )

    table_name, csv_name = RETROSHEET_BIOFILE
    if table_name not in cached_tables:
        csv_path = _ensure_retrosheet_csv(retrosheet_dir, csv_name)
        if csv_path.exists():
            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM read_csv_auto('{_sql_string(csv_path)}')
                """
            )

    for table_name, csv_name in RETROSHEET_DERIVED_TABLES.items():
        csv_path = retrosheet_dir / csv_name
        if csv_path.exists():
            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM read_csv_auto('{_sql_string(csv_path)}')
                """
            )


def _load_retrosheet_database_tables(
    conn: duckdb.DuckDBPyConnection,
    retrosheet_dir: Path,
) -> set[str]:
    database_path = retrosheet_dir / RETROSHEET_DATABASE_FILENAME
    if not database_path.exists():
        return set()
    if not _retrosheet_database_cache_valid(retrosheet_dir, database_path):
        return set()

    alias = "retrosheet_cache"
    loaded_tables: set[str] = set()
    try:
        conn.execute(f"ATTACH '{_sql_string(database_path)}' AS {alias} (READ_ONLY)")
    except duckdb.Error:
        return set()
    try:
        for table_name in RETROSHEET_STAT_TABLES:
            if not _attached_table_exists(conn, alias, table_name):
                continue
            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM {alias}.{table_name}
                WHERE lower(stattype) = 'value'
                  AND lower(gametype) IN ('regular', 'playoff')
                """
            )
            loaded_tables.add(table_name)

        table_name, _csv_name = RETROSHEET_BIOFILE
        if _attached_table_exists(conn, alias, table_name):
            conn.execute(
                f"""
                CREATE TABLE {table_name} AS
                SELECT *
                FROM {alias}.{table_name}
                """
            )
            loaded_tables.add(table_name)
    finally:
        conn.execute(f"DETACH {alias}")
    return loaded_tables


def _retrosheet_database_cache_valid(retrosheet_dir: Path, database_path: Path) -> bool:
    manifest_path = retrosheet_dir / "manifest.json"
    if not manifest_path.exists():
        return False

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False

    cache = manifest.get("cache", {}).get("database", {})
    if cache and Path(cache.get("path", "")).name != database_path.name:
        return False

    database_metadata = _retrosheet_database_metadata(database_path)
    if database_metadata is None:
        return False
    if database_metadata.get("schema_version") != "1":
        return False

    database_archive_hashes = _retrosheet_metadata_archive_hashes(database_metadata)
    cached_archive_hashes = (
        database_archive_hashes
        if database_archive_hashes
        else cache.get("source_archive_sha256", {})
    )
    if not isinstance(cached_archive_hashes, dict) or not cached_archive_hashes:
        return False

    manifest_archive_hashes = {
        item.get("archive"): item.get("archive_sha256")
        for item in manifest.get("files", [])
        if item.get("archive") and item.get("archive_sha256")
    }
    for archive_name, archive_hash in manifest_archive_hashes.items():
        if cached_archive_hashes.get(archive_name) != archive_hash:
            return False
    return True


def _retrosheet_database_metadata(database_path: Path) -> dict[str, str] | None:
    try:
        metadata_conn = duckdb.connect(str(database_path), read_only=True)
    except duckdb.Error:
        return None
    try:
        table_exists = metadata_conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_name = 'retrosheet_cache_metadata'
            LIMIT 1
            """
        ).fetchone()
        if not table_exists:
            return None
        rows = metadata_conn.execute("SELECT key, value FROM retrosheet_cache_metadata").fetchall()
    except duckdb.Error:
        return None
    finally:
        metadata_conn.close()

    return {key: value for key, value in rows}


def _retrosheet_metadata_archive_hashes(metadata: dict[str, str]) -> dict[str, str] | None:
    raw_value = metadata.get("source_archive_sha256")
    if raw_value is None:
        return None
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _attached_table_exists(
    conn: duckdb.DuckDBPyConnection,
    schema_name: str,
    table_name: str,
) -> bool:
    return bool(
        conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_catalog = ?
              AND table_name = ?
            LIMIT 1
            """,
            [schema_name, table_name],
        ).fetchone()
    )


def _ensure_retrosheet_csv(retrosheet_dir: Path, csv_name: str) -> Path:
    csv_path = retrosheet_dir / csv_name
    archive_name = RETROSHEET_ARCHIVES.get(csv_name)
    if archive_name is None:
        return csv_path
    archive_path = retrosheet_dir / archive_name
    if not archive_path.exists():
        return csv_path

    cache_dir = _retrosheet_extract_dir(archive_path)
    extracted_path = cache_dir / csv_name
    if extracted_path.exists():
        return extracted_path

    with zipfile.ZipFile(archive_path) as archive:
        member = archive.getinfo(csv_name)
        destination = (cache_dir / member.filename).resolve()
        if not destination.is_relative_to(cache_dir.resolve()):
            raise RuntimeError(f"Refusing to extract unsafe Retrosheet member: {member.filename}")
        cache_dir.mkdir(parents=True, exist_ok=True)
        archive.extract(member, cache_dir)
    return extracted_path


def _retrosheet_extract_dir(archive_path: Path) -> Path:
    root = os.environ.get(RETROSHEET_EXTRACT_DIR_ENV)
    base_dir = Path(root) if root else Path(tempfile.gettempdir()) / "groundball-retrosheet"
    stat = archive_path.stat()
    cache_key = f"{archive_path.stem}-{stat.st_size}-{int(stat.st_mtime)}"
    return base_dir / cache_key


def _sql_string(path: Path) -> str:
    return str(path).replace("'", "''")
