"""Tests for optional Retrosheet DuckDB tables."""

from __future__ import annotations

import duckdb

from baseball_rag.db import duckdb_schema


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
    monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
    duckdb_schema._cached_conn = None

    conn = duckdb_schema.get_duckdb()

    try:
        assert conn.execute("SELECT count(*) FROM retrosheet_batting").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM retrosheet_pitching").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM retrosheet_fielding").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM retrosheet_biofile").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM batting").fetchone()[0] == 1
    finally:
        conn.close()
        duckdb_schema._cached_conn = None
