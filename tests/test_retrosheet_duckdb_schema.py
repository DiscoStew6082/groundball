"""Tests for optional Retrosheet DuckDB tables."""

from __future__ import annotations

import json
import zipfile

import duckdb

from baseball_rag.db import duckdb_schema
from baseball_rag.db.secondary_sources import retrosheet, retrosheet_database


def _write_core_lahman_csvs(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "Batting.csv").write_text(
        "playerID,yearID,teamID,lgID,G,AB,H,HR,RBI,SB,BB\n"
        "ruthba01,1927,NYA,AL,151,540,192,60,164,7,137\n",
        encoding="utf-8",
    )
    (data_dir / "Pitching.csv").write_text(
        "playerID,yearID,teamID,lgID,W,L,ERA,IPouts\nruthba01,1916,BOS,AL,23,12,1.75,969\n",
        encoding="utf-8",
    )
    (data_dir / "Fielding.csv").write_text(
        "playerID,yearID,teamID,lgID,POS,PO,A,E\nruthba01,1927,NYA,AL,OF,302,14,6\n",
        encoding="utf-8",
    )
    (data_dir / "People.csv").write_text(
        "playerID,nameFirst,nameLast\nruthba01,Babe,Ruth\n",
        encoding="utf-8",
    )


def _table_count(conn: duckdb.DuckDBPyConnection, table_name: str) -> int:
    return conn.execute(
        """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchone()[0]


def test_duckdb_preserves_lahman_tables_when_retrosheet_files_are_absent(tmp_path, monkeypatch):
    _write_core_lahman_csvs(tmp_path)
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert conn.execute("SELECT count(*) FROM batting").fetchone()[0] == 1
        assert _table_count(conn, "retrosheet_batting") == 0
        assert _table_count(conn, "retrosheet_biofile") == 0
    finally:
        conn.close()
        duckdb_schema._cached_conn = None


def test_duckdb_loads_optional_retrosheet_tables_with_stat_filters(tmp_path, monkeypatch):
    _write_core_lahman_csvs(tmp_path)
    retrosheet_dir = tmp_path / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True)
    (retrosheet_dir / "batting.csv").write_text(
        "gid,stattype,gametype,b_pa\n"
        "NYA192704180,value,regular,4\n"
        "NYA192710050,value,playoff,4\n"
        "NYA192704190,official,regular,5\n"
        "NYA192704200,value,exhibition,4\n",
        encoding="utf-8",
    )
    (retrosheet_dir / "pitching.csv").write_text(
        "gid,stattype,gametype,p_ipouts\n"
        "NYA192704180,value,regular,27\n"
        "NYA192704190,official,regular,27\n",
        encoding="utf-8",
    )
    (retrosheet_dir / "fielding.csv").write_text(
        "gid,stattype,gametype,d_po\nNYA192704180,value,playoff,3\nNYA192704190,value,allstar,3\n",
        encoding="utf-8",
    )
    (retrosheet_dir / "biofile0.csv").write_text(
        "id,name_first,name_last\nruthb101,Babe,Ruth\ngehrl101,Lou,Gehrig\n",
        encoding="utf-8",
    )
    (retrosheet_dir / "pitcher_strikeout_side_events.csv").write_text(
        "retroID,year,game_id,inning,batting_home,started_half_inning,"
        "strikeout_outs,total_outs_recorded,event_sequence,game_date,home_team_id,"
        "away_team_id,pitcher_team_id,opponent_team_id,site\n"
        "ruthb101,1916,BOS191604180,9,0,true,3,3,K|K|K,1916-04-18,BOS,NYA,BOS,NYA,BOS01\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert conn.execute("SELECT count(*) FROM retrosheet_batting").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM retrosheet_pitching").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM retrosheet_fielding").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM retrosheet_biofile").fetchone()[0] == 2
        assert (
            conn.execute(
                "SELECT count(*) FROM retrosheet_pitcher_strikeout_side_events"
            ).fetchone()[0]
            == 1
        )
        assert (
            conn.execute(
                "SELECT opponent_team_id FROM retrosheet_pitcher_strikeout_side_events"
            ).fetchone()[0]
            == "NYA"
        )
        assert conn.execute("SELECT count(*) FROM batting").fetchone()[0] == 1
    finally:
        conn.close()
        duckdb_schema._cached_conn = None


def test_duckdb_prefers_tracked_retrosheet_zip_over_loose_csv(tmp_path, monkeypatch):
    _write_core_lahman_csvs(tmp_path)
    retrosheet_dir = tmp_path / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True)
    with zipfile.ZipFile(retrosheet_dir / "batting.zip", "w") as archive:
        archive.writestr(
            "batting.csv",
            "gid,id,stattype,gametype,date,b_sb\n"
            "OAK196906100,campb101,value,regular,1969-06-10,1\n"
            "OAK196906110,campb101,official,regular,1969-06-11,1\n"
            "OAK196906120,campb101,value,exhibition,1969-06-12,1\n",
        )
    (retrosheet_dir / "batting.csv").write_text(
        "gid,id,stattype,gametype,date,b_sb\nOAK196906100,campb101,value,regular,1969-06-10,0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    monkeypatch.setenv(
        duckdb_schema.RETROSHEET_EXTRACT_DIR_ENV,
        str(tmp_path / "retrosheet-cache"),
    )
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert (
            conn.execute("SELECT sum(CAST(b_sb AS INTEGER)) FROM retrosheet_batting").fetchone()[0]
            == 1
        )
        assert (retrosheet_dir / "batting.csv").exists()
        assert list((tmp_path / "retrosheet-cache").glob("*/batting.csv"))
    finally:
        conn.close()
        duckdb_schema._cached_conn = None


def test_duckdb_prefers_retrosheet_database_cache_over_csv_sources(tmp_path, monkeypatch):
    _write_core_lahman_csvs(tmp_path)
    retrosheet_dir = tmp_path / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True)
    with zipfile.ZipFile(retrosheet_dir / "batting.zip", "w") as archive:
        archive.writestr(
            "batting.csv",
            "gid,id,stattype,gametype,date,b_sb\n"
            "OAK196906100,campb101,value,regular,1969-06-10,1\n",
        )
    with zipfile.ZipFile(retrosheet_dir / "pitching.zip", "w") as archive:
        archive.writestr(
            "pitching.csv",
            "gid,id,stattype,gametype,date,p_ipouts\n"
            "OAK196906100,fingr101,value,regular,1969-06-10,27\n",
        )
    with zipfile.ZipFile(retrosheet_dir / "fielding.zip", "w") as archive:
        archive.writestr(
            "fielding.csv",
            "gid,id,stattype,gametype,date,d_po\n"
            "OAK196906100,campb101,value,regular,1969-06-10,3\n",
        )
    with zipfile.ZipFile(retrosheet_dir / "biodata.zip", "w") as archive:
        archive.writestr("biofile0.csv", "id,name_first,name_last\ncampb101,Bert,Campaneris\n")
    (retrosheet_dir / "batting.csv").write_text(
        "gid,id,stattype,gametype,date,b_sb\nOAK196906100,campb101,value,regular,1969-06-10,0\n",
        encoding="utf-8",
    )
    retrosheet.write_manifest(retrosheet_dir, downloaded_at="2026-07-03T17:00:00-04:00")
    retrosheet_database.build_database(retrosheet_dir)
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert (
            conn.execute("SELECT sum(CAST(b_sb AS INTEGER)) FROM retrosheet_batting").fetchone()[0]
            == 1
        )
    finally:
        conn.close()
        duckdb_schema._cached_conn = None


def test_duckdb_ignores_stale_retrosheet_database_cache(tmp_path, monkeypatch):
    _write_core_lahman_csvs(tmp_path)
    retrosheet_dir = tmp_path / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True)
    (retrosheet_dir / "batting.csv").write_text(
        "gid,id,stattype,gametype,date,b_sb\nOAK196906100,campb101,value,regular,1969-06-10,0\n",
        encoding="utf-8",
    )
    (retrosheet_dir / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "archive": "batting.zip",
                        "table": "retrosheet_batting",
                        "archive_sha256": "fresh",
                    }
                ],
                "cache": {
                    "database": {
                        "path": "data/secondary_sources/retrosheet/retrosheet.duckdb",
                        "source_archive_sha256": {"batting.zip": "stale"},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    cache_conn = duckdb.connect(str(retrosheet_dir / duckdb_schema.RETROSHEET_DATABASE_FILENAME))
    try:
        cache_conn.execute(
            """
            CREATE TABLE retrosheet_batting AS
            SELECT *
            FROM (
                VALUES ('OAK196906100', 'campb101', 'value', 'regular', '1969-06-10', '1')
            ) AS rows(gid, id, stattype, gametype, date, b_sb)
            """
        )
    finally:
        cache_conn.close()
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert (
            conn.execute("SELECT sum(CAST(b_sb AS INTEGER)) FROM retrosheet_batting").fetchone()[0]
            == 0
        )
    finally:
        conn.close()
        duckdb_schema._cached_conn = None


def test_duckdb_ignores_corrupt_retrosheet_database_cache(tmp_path, monkeypatch):
    _write_core_lahman_csvs(tmp_path)
    retrosheet_dir = tmp_path / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True)
    (retrosheet_dir / "batting.csv").write_text(
        "gid,id,stattype,gametype,date,b_sb\nOAK196906100,campb101,value,regular,1969-06-10,0\n",
        encoding="utf-8",
    )
    (retrosheet_dir / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "archive": "batting.zip",
                        "table": "retrosheet_batting",
                        "archive_sha256": "fresh",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (retrosheet_dir / duckdb_schema.RETROSHEET_DATABASE_FILENAME).write_text(
        "not a duckdb database",
        encoding="utf-8",
    )
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert (
            conn.execute("SELECT sum(CAST(b_sb AS INTEGER)) FROM retrosheet_batting").fetchone()[0]
            == 0
        )
    finally:
        conn.close()
        duckdb_schema._cached_conn = None


def test_duckdb_ignores_retrosheet_database_cache_with_wrong_schema_version(tmp_path, monkeypatch):
    _write_core_lahman_csvs(tmp_path)
    retrosheet_dir = tmp_path / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True)
    (retrosheet_dir / "batting.csv").write_text(
        "gid,id,stattype,gametype,date,b_sb\nOAK196906100,campb101,value,regular,1969-06-10,0\n",
        encoding="utf-8",
    )
    (retrosheet_dir / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "archive": "batting.zip",
                        "table": "retrosheet_batting",
                        "archive_sha256": "fresh",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    cache_conn = duckdb.connect(str(retrosheet_dir / duckdb_schema.RETROSHEET_DATABASE_FILENAME))
    try:
        cache_conn.execute(
            """
            CREATE TABLE retrosheet_batting AS
            SELECT *
            FROM (
                VALUES ('OAK196906100', 'campb101', 'value', 'regular', '1969-06-10', '1')
            ) AS rows(gid, id, stattype, gametype, date, b_sb)
            """
        )
        cache_conn.execute("CREATE TABLE retrosheet_cache_metadata (key TEXT, value TEXT)")
        cache_conn.executemany(
            "INSERT INTO retrosheet_cache_metadata VALUES (?, ?)",
            [
                ("schema_version", "0"),
                ("source_archive_sha256", json.dumps({"batting.zip": "fresh"})),
            ],
        )
    finally:
        cache_conn.close()
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert (
            conn.execute("SELECT sum(CAST(b_sb AS INTEGER)) FROM retrosheet_batting").fetchone()[0]
            == 0
        )
    finally:
        conn.close()
        duckdb_schema._cached_conn = None
