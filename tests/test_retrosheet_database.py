"""Tests for the Retrosheet DuckDB cache builder."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

import duckdb

from baseball_rag.db.duckdb_schema import RETROSHEET_DATABASE_FILENAME
from baseball_rag.db.secondary_sources import retrosheet_database


def _zip_bytes(member_name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return buffer.getvalue()


def test_build_database_creates_query_cache_from_archives_without_expanded_csvs(tmp_path):
    archives = {
        "batting.zip": _zip_bytes(
            "batting.csv",
            "gid,id,stattype,gametype,date,b_sb\n"
            "OAK196906100,campb101,value,regular,1969-06-10,1\n"
            "OAK196906110,campb101,official,regular,1969-06-11,2\n",
        ),
        "pitching.zip": _zip_bytes(
            "pitching.csv",
            "gid,id,stattype,gametype,date,p_ipouts\n"
            "OAK196906100,fingr101,value,regular,1969-06-10,27\n",
        ),
        "fielding.zip": _zip_bytes(
            "fielding.csv",
            "gid,id,stattype,gametype,date,d_po\n"
            "OAK196906100,campb101,value,regular,1969-06-10,3\n",
        ),
        "biodata.zip": _zip_bytes(
            "biofile0.csv",
            "id,name_first,name_last\ncampb101,Bert,Campaneris\n",
        ),
    }
    for archive_name, content in archives.items():
        (tmp_path / archive_name).write_bytes(content)

    database_path = retrosheet_database.build_database(tmp_path, update_manifest=True)

    assert database_path == tmp_path / RETROSHEET_DATABASE_FILENAME
    assert database_path.exists()
    assert not (tmp_path / "batting.csv").exists()
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    cache = manifest["cache"]["database"]
    assert cache["path"].endswith(RETROSHEET_DATABASE_FILENAME)
    assert cache["tables"] == [
        "retrosheet_batting",
        "retrosheet_pitching",
        "retrosheet_fielding",
        "retrosheet_biofile",
    ]
    assert set(cache["source_archive_sha256"]) == set(archives)
    assert len(cache["sha256"]) == 64

    conn = duckdb.connect(str(database_path), read_only=True)
    try:
        assert conn.execute("SELECT count(*) FROM retrosheet_batting").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM retrosheet_pitching").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM retrosheet_fielding").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM retrosheet_biofile").fetchone()[0] == 1
        metadata = dict(conn.execute("SELECT key, value FROM retrosheet_cache_metadata").fetchall())
        assert metadata["schema_version"] == "1"
        assert set(json.loads(metadata["source_archive_sha256"])) == set(archives)
    finally:
        conn.close()


def test_build_database_does_not_update_manifest_by_default(tmp_path):
    for archive_name, member_name in [
        ("batting.zip", "batting.csv"),
        ("pitching.zip", "pitching.csv"),
        ("fielding.zip", "fielding.csv"),
        ("biodata.zip", "biofile0.csv"),
    ]:
        (tmp_path / archive_name).write_bytes(
            _zip_bytes(member_name, "gid,stattype,gametype,date\nOAK196906100,value,regular,1969\n")
        )
    (tmp_path / "manifest.json").write_text('{"files": []}\n', encoding="utf-8")

    retrosheet_database.build_database(tmp_path)

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert "cache" not in manifest
