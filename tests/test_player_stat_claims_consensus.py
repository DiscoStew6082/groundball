from __future__ import annotations

import duckdb
import pytest

from baseball_rag.db.biography_stat_vocabulary import supported_biography_claim_stats
from baseball_rag.db.player_stat_claims import (
    PlayerStatClaim,
    shape_biography_stat_claim_consensus,
    verify_player_stat_claims_consensus,
)
from baseball_rag.db.stat_registry import supported_stats


def _conn(*, retrosheet: bool = True) -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE people (playerID TEXT, retroID TEXT)")
    conn.execute(
        """
        CREATE TABLE batting (
            playerID TEXT, yearID INTEGER, HR INTEGER, RBI INTEGER, H INTEGER,
            AB INTEGER, R INTEGER, "2B" INTEGER, "3B" INTEGER, SB INTEGER,
            BB INTEGER, SO INTEGER, HBP INTEGER, SF INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE pitching (
            playerID TEXT, yearID INTEGER, W INTEGER, L INTEGER, G INTEGER,
            GS INTEGER, SV INTEGER, IPouts INTEGER, H INTEGER, ER INTEGER,
            BB INTEGER, SO INTEGER
        )
        """
    )
    conn.execute("CREATE TABLE fielding (playerID TEXT, yearID INTEGER, PO INTEGER)")
    if retrosheet:
        conn.execute("CREATE TABLE retrosheet_biofile (retroID TEXT)")
        conn.execute(
            """
            CREATE TABLE retrosheet_batting (
                retroID TEXT, yearID INTEGER, HR INTEGER, RBI INTEGER, H INTEGER,
                AB INTEGER, R INTEGER, "2B" INTEGER, "3B" INTEGER, SB INTEGER,
                BB INTEGER, SO INTEGER, HBP INTEGER, SF INTEGER
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE retrosheet_pitching (
                retroID TEXT, yearID INTEGER, W INTEGER, L INTEGER, game_id TEXT,
                GS INTEGER, SV INTEGER, IPouts INTEGER, H INTEGER, ER INTEGER,
                BB INTEGER, SO INTEGER
            )
            """
        )
        conn.execute("CREATE TABLE retrosheet_fielding (retroID TEXT, yearID INTEGER, PO INTEGER)")
    return conn


def _add_player(conn: duckdb.DuckDBPyConnection, player_id: str = "player01") -> None:
    conn.execute("INSERT INTO people VALUES (?, ?)", [player_id, "retro001"])
    conn.execute("INSERT INTO retrosheet_biofile VALUES ('retro001')")


def _add_batting(
    conn: duckdb.DuckDBPyConnection,
    *,
    player_id: str = "player01",
    lahman_hr: int | None = 60,
    retro_hr: int | None = 60,
) -> None:
    if lahman_hr is not None:
        conn.execute(
            """
            INSERT INTO batting VALUES
            (?, 1927, ?, 120, 30, 100, 90, 5, 1, 3, 20, 10, 2, 5)
            """,
            [player_id, lahman_hr],
        )
    if retro_hr is not None:
        conn.execute(
            """
            INSERT INTO retrosheet_batting VALUES
            ('retro001', 1927, ?, 120, 30, 100, 90, 5, 1, 3, 20, 10, 2, 5)
            """,
            [retro_hr],
        )


def _row(
    conn: duckdb.DuckDBPyConnection,
    claim: PlayerStatClaim,
    *,
    player_id: str = "player01",
) -> dict:
    return verify_player_stat_claims_consensus(player_id, [claim], conn=conn)[0].to_row()


def test_consensus_verifies_claim_when_lahman_and_retrosheet_agree():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["status"] == "verified"
    assert row["actual_value"] == 60
    assert row["table"] == "batting"
    assert row["sql"] is not None
    assert row["warning"] is None
    assert row["consensus_status"] == "verified_by_all"
    assert row["primary_status"] == "verified"
    assert row["primary_actual_value"] == 60
    assert row["secondary_status"] == "verified"
    assert row["secondary_actual_value"] == 60
    assert row["secondary_table"] == "retrosheet_batting"
    assert row["secondary_warning"] is None


def test_consensus_read_model_shapes_biography_presentation():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, lahman_hr=61, retro_hr=61)
    verification = verify_player_stat_claims_consensus(
        "player01",
        [PlayerStatClaim(stat="HR", value=60, year=1927, text="60 home runs in 1927")],
        conn=conn,
    )[0]

    presentation = shape_biography_stat_claim_consensus([verification])

    assert presentation.summary == {
        "total_claims": 1,
        "verified_by_all": 0,
        "primary_only": 0,
        "secondary_only": 0,
        "contradicted_by_all": 1,
        "conflicts": 0,
        "unsupported": 0,
        "score": "failing",
    }
    assert "Stat claim consensus: total claims 1" in presentation.note
    assert (
        "HR was claimed as 60, but Lahman/Retrosheet consensus has 61 for season 1927"
        in presentation.note
    )
    assert presentation.warnings == [
        "DuckDB has 61 for HR (season 1927), not 60.",
    ]
    assert presentation.tables == ["batting"]
    assert presentation.sql is not None
    assert presentation.rows[0]["source_label"] == "Lahman and Retrosheet consensus"
    assert "Lahman" in presentation.source_detail
    assert "Retrosheet" in presentation.source_detail
    assert presentation.data_manifest["consensus_sources"][1]["upstream"] == "Retrosheet"


def test_consensus_verifies_primary_only_when_retrosheet_table_is_missing():
    conn = _conn(retrosheet=False)
    conn.execute("INSERT INTO people VALUES ('player01', 'retro001')")
    _add_batting(conn, retro_hr=None)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["consensus_status"] == "verified_primary_only"
    assert row["primary_status"] == "verified"
    assert row["secondary_status"] == "unsupported"
    assert row["secondary_table"] == "retrosheet_biofile"
    assert "retrosheet_biofile is not available" in row["secondary_warning"]


@pytest.mark.parametrize(
    ("lahman_hr", "retro_hr", "claim_value", "expected_status"),
    [
        (60, 60, 60, "verified_by_all"),
        (60, None, 60, "verified_primary_only"),
        (None, 60, 60, "verified_secondary_only"),
        (61, 61, 60, "contradicted_by_all"),
        (60, 61, 60, "conflict"),
    ],
)
def test_consensus_public_rows_preserve_status_shape_for_all_source_outcomes(
    lahman_hr: int | None,
    retro_hr: int | None,
    claim_value: int,
    expected_status: str,
):
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, lahman_hr=lahman_hr, retro_hr=retro_hr)

    row = _row(conn, PlayerStatClaim(stat="HR", value=claim_value, year=1927))

    assert row["consensus_status"] == expected_status
    assert {
        "stat",
        "claimed_value",
        "actual_value",
        "status",
        "sql",
        "consensus_status",
        "primary_status",
        "primary_actual_value",
        "secondary_status",
        "secondary_actual_value",
        "secondary_table",
        "secondary_warning",
        "source_label",
    }.issubset(row)


def test_consensus_preserves_primary_result_when_retrosheet_stat_table_has_no_player_column():
    conn = _conn(retrosheet=False)
    conn.execute("INSERT INTO people VALUES ('player01', 'retro001')")
    conn.execute("CREATE TABLE retrosheet_biofile (retroID TEXT)")
    conn.execute("INSERT INTO retrosheet_biofile VALUES ('retro001')")
    conn.execute(
        "CREATE TABLE retrosheet_batting (unknown_player TEXT, yearID INTEGER, HR INTEGER)"
    )
    _add_batting(conn, retro_hr=None)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["consensus_status"] == "verified_primary_only"
    assert row["primary_status"] == "verified"
    assert row["secondary_status"] == "unsupported"
    assert row["secondary_table"] == "retrosheet_batting"
    assert "has no player id column" in row["secondary_warning"]


def test_consensus_combines_internal_source_evidence_adapters(monkeypatch):
    from baseball_rag.db import player_stat_claims
    from baseball_rag.db.player_stat_claims import (
        PlayerStatVerification,
        RetrosheetStatVerification,
    )

    calls = []

    def fake_lahman(conn, player_id, claim):
        calls.append(("lahman", player_id, claim.stat))
        return player_stat_claims.ClaimEvidence(
            "Lahman",
            PlayerStatVerification(
                claim=claim,
                status="verified",
                actual_value=60,
                table="batting",
                sql="select lahman",
                params=[player_id],
            ),
        )

    def fake_retrosheet(conn, player_id, claim):
        calls.append(("retrosheet", player_id, claim.stat))
        return player_stat_claims.ClaimEvidence(
            "Retrosheet",
            RetrosheetStatVerification(
                status="contradicted",
                actual_value=61,
                table="retrosheet_batting",
                sql="select retrosheet",
                params=["retro001", 1927],
            ),
        )

    monkeypatch.setattr(player_stat_claims, "_lahman_evidence", fake_lahman)
    monkeypatch.setattr(player_stat_claims, "_retrosheet_evidence", fake_retrosheet)
    conn = _conn()

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert calls == [
        ("lahman", "player01", "HR"),
        ("retrosheet", "player01", "HR"),
    ]
    assert row["consensus_status"] == "conflict"
    assert row["primary_status"] == "verified"
    assert row["secondary_status"] == "contradicted"


def test_consensus_preserves_primary_contradiction_when_retrosheet_table_is_missing():
    conn = _conn(retrosheet=False)
    conn.execute("INSERT INTO people VALUES ('player01', 'retro001')")
    _add_batting(conn, retro_hr=None)

    row = _row(conn, PlayerStatClaim(stat="HR", value=61, year=1927))

    assert row["consensus_status"] == "unsupported"
    assert row["status"] == "contradicted"
    assert row["primary_status"] == "contradicted"
    assert row["actual_value"] == 60
    assert row["warning"] is not None


def test_consensus_verifies_primary_only_when_retrosheet_stat_row_is_missing():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, retro_hr=None)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["consensus_status"] == "verified_primary_only"
    assert row["primary_status"] == "verified"
    assert row["secondary_status"] == "no_data"
    assert row["secondary_table"] == "retrosheet_batting"


def test_consensus_verifies_secondary_only_when_lahman_row_is_missing():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, lahman_hr=None, retro_hr=60)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["consensus_status"] == "verified_secondary_only"
    assert row["primary_status"] == "no_data"
    assert row["secondary_status"] == "verified"
    assert row["secondary_actual_value"] == 60


def test_consensus_contradicts_by_all_when_sources_agree_with_each_other_not_claim():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, lahman_hr=61, retro_hr=61)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["consensus_status"] == "contradicted_by_all"
    assert row["primary_status"] == "contradicted"
    assert row["secondary_status"] == "contradicted"
    assert row["primary_actual_value"] == 61
    assert row["secondary_actual_value"] == 61


@pytest.mark.parametrize(
    ("lahman_hr", "retro_hr", "expected_primary", "expected_secondary"),
    [
        (60, 61, "verified", "contradicted"),
        (61, 60, "contradicted", "verified"),
        (62, 61, "contradicted", "contradicted"),
    ],
)
def test_consensus_conflicts_when_sources_have_different_values(
    lahman_hr: int,
    retro_hr: int,
    expected_primary: str,
    expected_secondary: str,
):
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, lahman_hr=lahman_hr, retro_hr=retro_hr)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["consensus_status"] == "conflict"
    assert row["primary_status"] == expected_primary
    assert row["secondary_status"] == expected_secondary


def test_consensus_reports_missing_retroid_without_chadwick_lookup():
    conn = _conn()
    conn.execute("INSERT INTO people VALUES ('player01', NULL)")
    _add_batting(conn)

    row = _row(conn, PlayerStatClaim(stat="HR", value=60, year=1927))

    assert row["consensus_status"] == "verified_primary_only"
    assert row["secondary_status"] == "unsupported"
    assert "people.retroID mapping" in row["secondary_warning"]
    assert "Chadwick" not in row["secondary_warning"]


def test_consensus_unsupported_for_unsupported_stats():
    conn = _conn()
    _add_player(conn)

    row = _row(conn, PlayerStatClaim(stat="MVP", value=3, scope="career"))

    assert row["consensus_status"] == "unsupported"
    assert row["primary_status"] == "unsupported_stat"
    assert row["secondary_status"] == "unsupported"
    assert row["secondary_actual_value"] is None


def test_consensus_keeps_sql_only_stats_out_of_biography_claim_vocabulary():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn)

    row = _row(conn, PlayerStatClaim(stat="BB", value=20, year=1927))

    assert "BB" in supported_stats()
    assert "BB" not in supported_biography_claim_stats()
    assert row["consensus_status"] == "unsupported"
    assert row["primary_status"] == "unsupported_stat"
    assert row["secondary_status"] == "unsupported"
    assert "Unsupported biography stat claim" in row["warning"]


@pytest.mark.parametrize("bad_value", ["many", None, float("nan")])
def test_consensus_unsupported_for_invalid_values(bad_value: object):
    conn = _conn()
    _add_player(conn)
    _add_batting(conn)

    row = _row(conn, PlayerStatClaim(stat="HR", value=bad_value, year=1927))

    assert row["consensus_status"] == "unsupported"
    assert row["primary_status"] == "invalid_value"
    assert row["secondary_status"] == "unsupported"


def test_consensus_refutes_a_rod_301_stolen_bases_when_both_sources_have_329():
    conn = _conn()
    conn.execute("INSERT INTO people VALUES ('rodrial01', 'rodra001')")
    conn.execute("INSERT INTO retrosheet_biofile VALUES ('rodra001')")
    conn.execute(
        """
        INSERT INTO batting VALUES
        ('rodrial01', 2016, 696, 2086, 3115, 10566, 2021, 548, 31, 329, 1338, 2287, 176, 111)
        """
    )
    conn.execute(
        """
        INSERT INTO retrosheet_batting VALUES
        ('rodra001', 2016, 696, 2086, 3115, 10566, 2021, 548, 31, 329, 1338, 2287, 176, 111)
        """
    )

    row = _row(
        conn,
        PlayerStatClaim(stat="SB", value=301, scope="career", text="301 SB"),
        player_id="rodrial01",
    )

    assert row["consensus_status"] == "contradicted_by_all"
    assert row["primary_actual_value"] == 329
    assert row["secondary_actual_value"] == 329


def test_consensus_verifies_real_retrosheet_daily_log_headers():
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE people (playerID TEXT, retroID TEXT)")
    conn.execute(
        """
        CREATE TABLE batting (
            playerID TEXT, yearID INTEGER, HR INTEGER, RBI INTEGER, H INTEGER,
            AB INTEGER, R INTEGER, "2B" INTEGER, "3B" INTEGER, SB INTEGER,
            BB INTEGER, SO INTEGER, HBP INTEGER, SF INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE pitching (
            playerID TEXT, yearID INTEGER, W INTEGER, L INTEGER, G INTEGER,
            GS INTEGER, SV INTEGER, IPouts INTEGER, H INTEGER, ER INTEGER,
            BB INTEGER, SO INTEGER
        )
        """
    )
    conn.execute("CREATE TABLE fielding (playerID TEXT, yearID INTEGER, PO INTEGER)")
    conn.execute("CREATE TABLE retrosheet_biofile (id TEXT)")
    conn.execute(
        """
        CREATE TABLE retrosheet_batting (
            gid TEXT, id TEXT, stattype TEXT, gametype TEXT, date TEXT,
            b_hr INTEGER, b_rbi INTEGER, b_h INTEGER, b_ab INTEGER, b_r INTEGER,
            b_d INTEGER, b_t INTEGER, b_sb INTEGER, b_w INTEGER, b_k INTEGER,
            b_hbp INTEGER, b_sf INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE retrosheet_pitching (
            gid TEXT, id TEXT, stattype TEXT, gametype TEXT, date TEXT,
            wp INTEGER, lp INTEGER, save INTEGER, gs INTEGER, p_ipouts INTEGER,
            p_h INTEGER, p_er INTEGER, p_w INTEGER, p_k INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE retrosheet_fielding (
            gid TEXT, id TEXT, stattype TEXT, gametype TEXT, date TEXT, d_po INTEGER
        )
        """
    )
    conn.execute("INSERT INTO people VALUES ('ruthba01', 'ruthb101')")
    conn.execute("INSERT INTO retrosheet_biofile VALUES ('ruthb101')")
    conn.execute(
        """
        INSERT INTO batting VALUES
        ('ruthba01', 1927, 60, 164, 192, 540, 158, 29, 8, 7, 137, 89, 0, 14)
        """
    )
    conn.executemany(
        "INSERT INTO retrosheet_batting VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                "NYA192704180",
                "ruthb101",
                "value",
                "regular",
                "19270418",
                1,
                4,
                3,
                5,
                2,
                1,
                0,
                0,
                1,
                0,
                0,
                1,
            ),
            (
                "NYA192710010",
                "ruthb101",
                "value",
                "playoff",
                "19271001",
                59,
                160,
                189,
                535,
                156,
                28,
                8,
                7,
                136,
                89,
                0,
                13,
            ),
            (
                "NYA192704200",
                "ruthb101",
                "official",
                "regular",
                "19270420",
                99,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
            (
                "NYA192704210",
                "ruthb101",
                "value",
                "allstar",
                "19270421",
                99,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
        ],
    )
    conn.execute("INSERT INTO pitching VALUES ('ruthba01', 1927, 1, 0, 2, 1, 1, 54, 10, 4, 3, 12)")
    conn.execute(
        """
        INSERT INTO retrosheet_pitching VALUES
        ('NYA192704180', 'ruthb101', 'value', 'regular', '19270418', 1, 0, 0, 1, 27, 5, 2, 1, 6),
        ('NYA192710010', 'ruthb101', 'value', 'playoff', '19271001', 0, 0, 1, 0, 27, 5, 2, 2, 6),
        ('NYA192704200', 'ruthb101', 'official', 'regular', '19270420', 1, 0, 0, 0, 27, 5, 2, 1, 6),
        ('NYA192704210', 'ruthb101', 'value', 'allstar', '19270421', 1, 0, 0, 0, 27, 5, 2, 1, 6)
        """
    )
    conn.execute("INSERT INTO fielding VALUES ('ruthba01', 1927, 302)")
    conn.execute(
        """
        INSERT INTO retrosheet_fielding VALUES
        ('NYA192704180', 'ruthb101', 'value', 'regular', '19270418', 100),
        ('NYA192710010', 'ruthb101', 'value', 'playoff', '19271001', 202),
        ('NYA192704200', 'ruthb101', 'official', 'regular', '19270420', 99),
        ('NYA192704210', 'ruthb101', 'value', 'allstar', '19270421', 99)
        """
    )

    rows = {
        claim.stat: _row(conn, claim, player_id="ruthba01")
        for claim in [
            PlayerStatClaim(stat="HR", value=60, year=1927),
            PlayerStatClaim(stat="AVG", value=0.356, year=1927),
            PlayerStatClaim(stat="W", value=1, year=1927),
            PlayerStatClaim(stat="SO", value=12, year=1927, text="12 strikeouts as a pitcher"),
            PlayerStatClaim(stat="PO", value=302, year=1927),
        ]
    }

    assert rows["HR"]["secondary_status"] == "verified"
    assert rows["AVG"]["secondary_status"] == "verified"
    assert rows["W"]["secondary_status"] == "verified"
    assert rows["SO"]["secondary_status"] == "verified"
    assert rows["PO"]["secondary_status"] == "verified"

    result = verify_player_stat_claims_consensus(
        "ruthba01",
        [PlayerStatClaim(stat="HR", value=60, year=1927)],
        conn=conn,
    )[0]
    assert "LOWER(CAST(rb.\"stattype\" AS VARCHAR)) = 'value'" in result.secondary.sql
    assert (
        "LOWER(CAST(rb.\"gametype\" AS VARCHAR)) IN ('regular', 'playoff')" in result.secondary.sql
    )


@pytest.mark.parametrize("stat", supported_biography_claim_stats())
def test_consensus_has_retrosheet_mapping_for_every_biography_claim_stat(stat: str):
    conn = _conn()
    _add_player(conn)
    conn.execute(
        """
        INSERT INTO batting VALUES
        ('player01', 1927, 10, 120, 30, 100, 90, 5, 1, 3, 20, 10, 2, 5)
        """
    )
    conn.execute(
        """
        INSERT INTO retrosheet_batting VALUES
        ('retro001', 1927, 10, 120, 30, 100, 90, 5, 1, 3, 20, 10, 2, 5)
        """
    )
    conn.execute(
        """
        INSERT INTO pitching VALUES
        ('player01', 1927, 20, 10, 2, 30, 5, 900, 100, 40, 50, 200)
        """
    )
    conn.execute(
        """
        INSERT INTO retrosheet_pitching VALUES
        ('retro001', 1927, 20, 10, 'game-a', 30, 5, 450, 50, 20, 25, 100),
        ('retro001', 1927, 0, 0, 'game-b', 0, 0, 450, 50, 20, 25, 100)
        """
    )
    conn.execute("INSERT INTO fielding VALUES ('player01', 1927, 300)")
    conn.execute("INSERT INTO retrosheet_fielding VALUES ('retro001', 1927, 300)")
    expected = {
        "2B": 5,
        "3B": 1,
        "AB": 100,
        "AVG": 0.300,
        "BB": 20,
        "ERA": 1.2,
        "G": 2,
        "GS": 30,
        "H": 30,
        "HR": 10,
        "L": 10,
        "OPS": 1.079,
        "PO": 300,
        "R": 90,
        "RBI": 120,
        "SB": 3,
        "SO": 10,
        "SV": 5,
        "W": 20,
        "WHIP": 0.5,
    }

    row = _row(conn, PlayerStatClaim(stat=stat, value=expected[stat], year=1927))

    assert row["secondary_status"] == "verified"
    assert row["secondary_table"] in {
        "retrosheet_batting",
        "retrosheet_pitching",
        "retrosheet_fielding",
    }
    assert row["secondary_warning"] is None


def test_consensus_contextual_pitching_strikeouts_use_retrosheet_pitching_table():
    conn = _conn()
    _add_player(conn)
    conn.execute(
        "INSERT INTO pitching VALUES ('player01', 1927, 20, 10, 2, 30, 5, 900, 100, 40, 50, 200)"
    )
    conn.execute(
        """
        INSERT INTO retrosheet_pitching VALUES
        ('retro001', 1927, 20, 10, 'game-a', 30, 5, 450, 50, 20, 25, 100),
        ('retro001', 1927, 0, 0, 'game-b', 0, 0, 450, 50, 20, 25, 100)
        """
    )

    row = _row(
        conn,
        PlayerStatClaim(
            stat="SO",
            value=200,
            year=1927,
            text="struck out 200 batters as a pitcher",
        ),
    )

    assert row["consensus_status"] == "verified_by_all"
    assert row["table"] == "pitching"
    assert row["secondary_table"] == "retrosheet_pitching"
    assert row["secondary_warning"] is None


def test_consensus_retrosheet_sql_filters_by_retroid_and_year():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn)

    result = verify_player_stat_claims_consensus(
        "player01",
        [PlayerStatClaim(stat="HR", value=60, year=1927)],
        conn=conn,
    )[0]

    assert "FROM retrosheet_batting rb" in result.secondary.sql
    assert 'rb."retroID" = ?' in result.secondary.sql
    assert 'rb."yearID" = ?' in result.secondary.sql
    assert result.secondary.params == ["retro001", 1927]


def test_consensus_provenance_marks_placeholder_retrosheet_manifest_optional():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn)
    verification = verify_player_stat_claims_consensus(
        "player01",
        [PlayerStatClaim(stat="HR", value=60, year=1927)],
        conn=conn,
    )[0]

    presentation = shape_biography_stat_claim_consensus([verification])

    assert presentation.data_manifest["dataset"]["name"] == "NeuML/baseballdata"
    retrosheet = presentation.data_manifest["secondary_manifests"]["retrosheet"]
    assert retrosheet["available"] is False
    assert retrosheet["dataset"]["name"] == "Retrosheet CSV daily logs and biographical data"


def test_consensus_presentation_surfaces_retrosheet_sql_for_secondary_only_evidence():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, lahman_hr=None, retro_hr=60)
    verification = verify_player_stat_claims_consensus(
        "player01",
        [PlayerStatClaim(stat="HR", value=60, year=1927)],
        conn=conn,
    )[0]

    presentation = shape_biography_stat_claim_consensus([verification])

    assert presentation.rows[0]["consensus_status"] == "verified_secondary_only"
    assert "FROM batting b" in presentation.rows[0]["primary_sql"]
    assert "FROM retrosheet_batting rb" in presentation.rows[0]["secondary_sql"]
    assert presentation.rows[0]["sql"] == presentation.rows[0]["secondary_sql"]
    assert presentation.rows[0]["params"] == presentation.rows[0]["secondary_params"]
    assert presentation.sql == presentation.rows[0]["secondary_sql"]


def test_consensus_presentation_surfaces_retrosheet_sql_for_verified_secondary_conflict():
    conn = _conn()
    _add_player(conn)
    _add_batting(conn, lahman_hr=61, retro_hr=60)
    verification = verify_player_stat_claims_consensus(
        "player01",
        [PlayerStatClaim(stat="HR", value=60, year=1927)],
        conn=conn,
    )[0]

    presentation = shape_biography_stat_claim_consensus([verification])

    assert presentation.rows[0]["consensus_status"] == "conflict"
    assert presentation.rows[0]["primary_status"] == "contradicted"
    assert presentation.rows[0]["secondary_status"] == "verified"
    assert presentation.rows[0]["sql"] == presentation.rows[0]["secondary_sql"]
    assert presentation.rows[0]["params"] == presentation.rows[0]["secondary_params"]
    assert presentation.sql == presentation.rows[0]["secondary_sql"]
