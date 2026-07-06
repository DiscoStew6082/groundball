"""Tests for grounded database questions with deterministic SQL generation."""

from unittest.mock import MagicMock, patch

import pytest


def _write_core_csvs_with_retro_ids(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "Batting.csv").write_text(
        "playerID,yearID,teamID,lgID,G,AB,H,HR,RBI,SB,BB\n"
        "campbe01,1969,OAK,AL,1,4,1,0,0,1,0\n"
        "hendrri01,1982,OAK,AL,1,4,1,0,0,1,0\n",
        encoding="utf-8",
    )
    (data_dir / "Pitching.csv").write_text(
        "playerID,yearID,teamID,lgID,W,L,ERA,IPouts\n",
        encoding="utf-8",
    )
    (data_dir / "Fielding.csv").write_text(
        "playerID,yearID,teamID,lgID,POS,PO,A,E\n",
        encoding="utf-8",
    )
    (data_dir / "People.csv").write_text(
        "playerID,retroID,nameFirst,nameLast\n"
        "campbe01,campb101,Bert,Campaneris\n"
        "hendrri01,hendr001,Rickey,Henderson\n"
        "ryanno01,ryann001,Nolan,Ryan\n"
        "clemero02,clemr001,Roger,Clemens\n",
        encoding="utf-8",
    )


def _write_retrosheet_batting_streak_fixture(data_dir):
    retrosheet_dir = data_dir / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True)
    campy_rows = "\n".join(
        f"OAK196906{day:02d}0,campb101,OAK,value,1,1,"
        f"{1 if day <= 12 else 0},{1 if day <= 13 else 0},"
        f"{1 if day <= 14 else 0},196906{day:02d},regular,KCA"
        for day in range(10, 22)
    )
    (retrosheet_dir / "batting.csv").write_text(
        "gid,id,team,stattype,b_sb,b_h,b_hr,b_rbi,b_r,date,gametype,opp\n"
        "OAK196906090,campb101,OAK,value,0,0,0,0,0,19690609,regular,KCA\n"
        f"{campy_rows}\n"
        "OAK196906220,campb101,OAK,value,0,0,0,0,0,19690622,regular,KCA\n"
        "OAK198205010,hendr001,OAK,value,1,1,1,0,1,19820501,regular,SEA\n"
        "OAK198205020,hendr001,OAK,value,1,2,2,1,0,19820502,regular,SEA\n"
        "OAK198205030,hendr001,OAK,value,0,0,0,0,0,19820503,regular,SEA\n"
        "NYA198205040,hendr001,OAK,value,2,1,0,1,1,19820504,regular,NYA\n"
        "OAK198205050,hendr001,OAK,value,3,1,0,1,1,19820505,regular,SEA\n"
        "OAK198210100,hendr001,OAK,value,1,1,1,1,1,19821010,playoff,KCA\n"
        "OAK198210110,hendr001,OAK,value,1,1,1,1,1,19821011,playoff,KCA\n",
        encoding="utf-8",
    )


def _write_retrosheet_pitching_game_log_fixture(data_dir):
    retrosheet_dir = data_dir / "secondary_sources" / "retrosheet"
    retrosheet_dir.mkdir(parents=True, exist_ok=True)
    (retrosheet_dir / "pitching.csv").write_text(
        "gid,id,team,p_seq,stattype,p_ipouts,p_k,date,number,site,vishome,opp,gametype\n"
        "CAL197305150,ryann001,CAL,1,value,27,12,19730515,0,CAL01,h,BAL,regular\n"
        "CAL197306010,ryann001,CAL,1,value,27,9,19730601,0,CAL01,h,DET,regular\n"
        "CAL197307150,ryann001,CAL,1,value,27,17,19730715,0,CAL01,h,DET,regular\n"
        "BOS198609180,clemr001,BOS,1,value,27,15,19860918,0,BOS07,h,NYA,regular\n"
        "BOS198610080,clemr001,BOS,1,value,27,10,19861008,0,BOS07,h,CAL,playoff\n",
        encoding="utf-8",
    )


class TestAssembleSQL:
    """Unit tests for the deterministic SQL assembler.

    _assemble_sql(intent) must always produce the same SQL for the same intent,
    regardless of what the LLM might have returned. No LLM calls -- pure function.
    """

    def test_assembles_batting_only(self):
        from baseball_rag.db.grounded_database_assembler import _assemble_sql
        from baseball_rag.db.grounded_database_types import QuerySpec

        intent = QuerySpec(
            stat_tables=["batting"],
            team_name_pattern="Braves",
            year_value=1936,
        )
        sql = _assemble_sql(intent)

        assert "people" in sql.sql.lower()
        assert "batting" in sql.sql.lower()
        assert "teams" in sql.sql.lower()
        assert "?" in sql.sql
        assert sql.params == ["%Braves%", 1936]

    def test_assembles_batting_and_pitching_union(self):
        from baseball_rag.db.grounded_database_assembler import _assemble_sql
        from baseball_rag.db.grounded_database_types import QuerySpec

        intent = QuerySpec(
            stat_tables=["batting", "pitching"],
            team_name_pattern="Yankees",
            year_value=1950,
        )
        sql = _assemble_sql(intent)

        assert "union" in sql.sql.lower()
        assert "batting" in sql.sql.lower()
        assert "pitching" in sql.sql.lower()

    def test_assembles_without_year(self):
        from baseball_rag.db.grounded_database_assembler import _assemble_sql
        from baseball_rag.db.grounded_database_types import QuerySpec

        intent = QuerySpec(stat_tables=["batting"], team_name_pattern="Cubs")
        sql = _assemble_sql(intent)

        assert sql.params == ["%Cubs%"]
        # No year filter means no 1936 etc.
        assert "yearid" not in sql.sql.lower() or "BETWEEN" not in sql.sql.upper()

    def test_always_distinct(self):
        from baseball_rag.db.grounded_database_assembler import _assemble_sql
        from baseball_rag.db.grounded_database_types import QuerySpec

        intent = QuerySpec(
            stat_tables=["batting", "pitching"],
            team_name_pattern="Dodgers",
            year_value=1955,
        )
        sql = _assemble_sql(intent)

        # DISTINCT must be present to avoid duplicate players appearing twice
        assert "distinct" in sql.sql.lower()


class TestDeterministicTemplates:
    """Tests for common grounded database patterns that should bypass the LLM."""

    def _run_query(self, question: str, *, request_fn=None):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import query

        return query(question, get_duckdb(), request_fn=request_fn or MagicMock())

    def test_triple_crown_template_bypasses_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("who won the Triple Crown and which years", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.params == [300]
        assert {"name", "yearID", "HR", "RBI", "AVG"} <= set(result.columns)
        assert ("Rogers Hornsby", 1922, "NL", 42, 152, 0.401) in result.rows
        assert all(row[2] in ("AL", "NL") for row in result.rows)

    def test_thirty_thirty_template_bypasses_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("show me 30-30 club seasons", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.params == [30, 30]
        assert ("Hank Aaron", 1963, 44, 31) in result.rows

    def test_thirty_thirty_template_exposes_catalog_metadata(self):
        from baseball_rag.db.grounded_database_templates import match_template

        matched = match_template("show me 30-30 club seasons")

        assert matched is not None
        assert matched.template_id == "thirty_thirty_club"
        assert matched.match_facts == {"pattern": "30-30 club"}
        assert matched.route_owner is True
        assert matched.query_spec is None
        assert matched.assembled.params == [30, 30]
        assert matched.source_detail == (
            "Matched local 30-30 club template: player seasons with at least 30 HR and 30 SB."
        )

    def test_stolen_base_streak_template_answers_all_time_and_player_specific(
        self, tmp_path, monkeypatch
    ):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import format_result, query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_batting_streak_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            all_time = query(
                "what is the longest stolen base streak in MLB history",
                conn,
                request_fn=mock_call,
            )
            player_specific = query(
                "what was Rickey Henderson's longest stolen base streak",
                conn,
                request_fn=mock_call,
            )
            postseason = query(
                "what was Rickey Henderson's longest postseason stolen base streak",
                conn,
                request_fn=mock_call,
            )
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert all_time.rows[0][:4] == ("Bert Campaneris", 12, "1969-06-10", "1969-06-21")
        assert player_specific.rows[0][0:2] == ("Rickey Henderson", 2)
        assert postseason.rows[0][0:2] == ("Rickey Henderson", 2)
        assert "Bert Campaneris had the longest stolen-base streak" in format_result(
            all_time, "question"
        )

    def test_batting_stat_streak_template_answers_hit_streaks(self, tmp_path, monkeypatch):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import format_result, query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_batting_streak_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            all_time = query(
                "what is the longest hit streak in MLB history",
                conn,
                request_fn=mock_call,
            )
            player_specific = query(
                "what was Rickey Henderson's longest hitting streak",
                conn,
                request_fn=mock_call,
            )
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert all_time.rows[0][:4] == ("Bert Campaneris", 12, "1969-06-10", "1969-06-21")
        assert player_specific.rows[0][0:2] == ("Rickey Henderson", 2)
        assert "Bert Campaneris had the longest hit streak" in format_result(all_time, "question")

    @pytest.mark.parametrize(
        ("question", "expected_name", "expected_games", "formatted"),
        [
            (
                "what is the longest home run game streak in MLB history",
                "Bert Campaneris",
                3,
                "Bert Campaneris had the longest home-run game streak",
            ),
            (
                "what was Rickey Henderson's longest RBI streak",
                "Rickey Henderson",
                2,
                "Rickey Henderson had the longest RBI game streak",
            ),
            (
                "what was Rickey Henderson's longest run-scored streak",
                "Rickey Henderson",
                2,
                "Rickey Henderson had the longest run-scored streak",
            ),
            (
                "what was Rickey Henderson's longest postseason home run streak",
                "Rickey Henderson",
                2,
                "Rickey Henderson had the longest home-run game streak: "
                "2 consecutive postseason games",
            ),
        ],
    )
    def test_batting_stat_streak_template_answers_other_stat_families(
        self, tmp_path, monkeypatch, question, expected_name, expected_games, formatted
    ):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import format_result, query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_batting_streak_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            result = query(question, conn, request_fn=mock_call)
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert result.rows[0][0:2] == (expected_name, expected_games)
        assert formatted in format_result(result, "question")

    def test_pitcher_daily_strikeout_game_log_uses_retrosheet_pitching(self, tmp_path, monkeypatch):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import format_result, query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_pitching_game_log_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            result = query(
                "show Nolan Ryan games with at least 10 strikeouts",
                conn,
                request_fn=mock_call,
            )
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert result.source_label == "Deterministic template query"
        assert result.params == ["nolan ryan", 10, "regular"]
        assert result.columns == [
            "game_date",
            "game_id",
            "name",
            "team",
            "opponent",
            "stat",
            "stat_value",
            "gametype",
        ]
        assert result.rows == [
            ("1973-05-15", "CAL197305150", "Nolan Ryan", "CAL", "BAL", "SO", 12, "regular"),
            ("1973-07-15", "CAL197307150", "Nolan Ryan", "CAL", "DET", "SO", 17, "regular"),
        ]
        formatted = format_result(result, "question")
        assert "Nolan Ryan SO game log" in formatted
        assert "Retrosheet game-level logs" in formatted

    def test_pitcher_daily_strikeout_game_log_accepts_show_game_log_prefix(
        self, tmp_path, monkeypatch
    ):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_pitching_game_log_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            result = query("show Nolan Ryan strikeout game log in 1973", conn, request_fn=mock_call)
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert result.params == ["nolan ryan", 0, "regular", 1973]
        assert result.row_count == 3

    def test_pitcher_daily_strikeout_game_log_supports_postseason_filter(
        self, tmp_path, monkeypatch
    ):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_pitching_game_log_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            result = query(
                "show Roger Clemens postseason games with at least 10 strikeouts",
                conn,
                request_fn=mock_call,
            )
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert result.params == ["roger clemens", 10, "playoff"]
        assert result.rows == [
            ("1986-10-08", "BOS198610080", "Roger Clemens", "BOS", "CAL", "SO", 10, "playoff")
        ]

    @pytest.mark.parametrize(
        ("question", "reason"),
        [
            ("show Nolan Ryan pitch-by-pitch strikeout game logs", "Pitch-level details"),
            ("show Nolan Ryan inning by inning strikeout game logs", "Inning-level"),
            ("show team pitching game logs with at least 10 strikeouts", "Team pitching game logs"),
        ],
    )
    def test_pitcher_daily_strikeout_game_log_rejects_unmodeled_variants(self, question, reason):
        from baseball_rag.db.grounded_database_templates import match_template

        matched = match_template(question)

        assert matched is not None
        assert matched.template_id == "pitcher_daily_strikeout_game_log"
        assert matched.unsupported_reason == "unsupported"
        assert reason in matched.assembled.params[0]

    @pytest.mark.parametrize(
        ("question", "reason"),
        [
            ("what team has the longest stolen base streak", "Team stolen-base streaks"),
            ("what team has the longest hitting streak", "Team hit streaks"),
            (
                "what is the longest hit and home run streak",
                "Multi-stat batting streaks",
            ),
            (
                "what is the longest home run streak by plate appearance",
                "Play-level or inning-level batting streaks",
            ),
            (
                "what is the longest RBI streak by inning",
                "Play-level or inning-level batting streaks",
            ),
            (
                "what is the longest stolen base streak without being caught stealing",
                "caught-stealing-aware attempt modeling",
            ),
            ("longest stolen base streak stealing third base", "Base-specific"),
        ],
    )
    def test_batting_stat_streak_template_rejects_unmodeled_variants(self, question, reason):
        from baseball_rag.db.grounded_database_templates import match_template

        matched = match_template(question)

        assert matched is not None
        assert matched.unsupported_reason == "unsupported"
        assert reason in matched.assembled.params[0]

    def test_player_batting_game_log_template_answers_stolen_base_threshold(
        self, tmp_path, monkeypatch
    ):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_batting_streak_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            result = query(
                "show Rickey Henderson's games with at least 2 stolen bases",
                conn,
                request_fn=mock_call,
            )
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert result.source_label == "Deterministic template query"
        assert "retrosheet_batting" in result.sql
        assert result.params == ["rickey henderson", "regular", 2]
        assert result.columns == [
            "date",
            "game_id",
            "name",
            "team",
            "opponent_team",
            "stat",
            "stat_value",
            "gametype",
        ]
        assert result.rows == [
            (
                "1982-05-04",
                "NYA198205040",
                "Rickey Henderson",
                "Oakland Athletics",
                "New York Yankees",
                "SB",
                2,
                "regular",
            ),
            (
                "1982-05-05",
                "OAK198205050",
                "Rickey Henderson",
                "Oakland Athletics",
                "Seattle Mariners",
                "SB",
                3,
                "regular",
            ),
        ]

    def test_player_batting_game_log_template_answers_stolen_base_variants(
        self, tmp_path, monkeypatch
    ):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_batting_streak_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            three_steals = query(
                "what games did Rickey Henderson steal 3 bases",
                conn,
                request_fn=mock_call,
            )
            season_log = query(
                "Rickey Henderson stolen base game log in 1982",
                conn,
                request_fn=mock_call,
            )
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert three_steals.params == ["rickey henderson", "regular", 3]
        assert three_steals.rows == [
            (
                "1982-05-05",
                "OAK198205050",
                "Rickey Henderson",
                "Oakland Athletics",
                "Seattle Mariners",
                "SB",
                3,
                "regular",
            )
        ]
        assert season_log.params == ["rickey henderson", "regular", 1982, 1]
        assert [row[0] for row in season_log.rows] == [
            "1982-05-01",
            "1982-05-02",
            "1982-05-04",
            "1982-05-05",
        ]

    def test_player_batting_game_log_template_accepts_show_prefix_and_home_run_verb(
        self, tmp_path, monkeypatch
    ):
        from baseball_rag.db import duckdb_schema
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import query

        _write_core_csvs_with_retro_ids(tmp_path)
        _write_retrosheet_batting_streak_fixture(tmp_path)
        monkeypatch.setattr(duckdb_schema, "DATA_DIR", tmp_path)
        duckdb_schema._cached_conn = None
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        conn = get_duckdb()

        try:
            prefixed = query(
                "show Rickey Henderson hit game log in 1982",
                conn,
                request_fn=mock_call,
            )
            home_runs = query(
                "what games did Rickey Henderson hit 2 home runs",
                conn,
                request_fn=mock_call,
            )
        finally:
            conn.close()
            duckdb_schema._cached_conn = None

        assert mock_call.call_count == 0
        assert prefixed.params == ["rickey henderson", "regular", 1982, 1]
        assert prefixed.row_count == 4
        assert home_runs.params == ["rickey henderson", "regular", 2]
        assert home_runs.rows == [
            (
                "1982-05-02",
                "OAK198205020",
                "Rickey Henderson",
                "Oakland Athletics",
                "Seattle Mariners",
                "HR",
                2,
                "regular",
            )
        ]

    @pytest.mark.parametrize(
        ("question", "reason"),
        [
            ("show team stolen base game logs", "Team batting game logs"),
            (
                "show Rickey Henderson games with stolen bases and home runs",
                "Multi-stat batting game logs",
            ),
            (
                "show Rickey Henderson play by play stolen base game log",
                "Play-level or inning-level batting details",
            ),
            (
                "show Rickey Henderson games stealing third base",
                "Base-specific stolen-base details",
            ),
        ],
    )
    def test_player_batting_game_log_template_rejects_unmodeled_variants(self, question, reason):
        from baseball_rag.db.grounded_database_templates import match_template

        matched = match_template(question)

        assert matched is not None
        assert matched.template_id == "player_batting_game_log"
        assert matched.unsupported_reason == "unsupported"
        assert reason in matched.assembled.params[0]

    def test_500_home_run_club_template_bypasses_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("500 home run club", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.params == [500]
        assert result.rows[0] == ("Barry Bonds", 762)
        assert ("Babe Ruth", 714) in result.rows

    def test_career_pitching_wins_template_bypasses_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query(
            "career pitching wins leaders with at least 500 wins", request_fn=mock_call
        )

        assert mock_call.call_count == 0
        assert result.params == [500]
        assert result.rows == [("Cy Young", 511)]

    def test_career_pitching_wins_leaders_without_threshold(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("career pitching wins leaders", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.params == [25]
        assert result.rows[:3] == [
            ("Cy Young", 511),
            ("Walter Johnson", 417),
            ("Pete Alexander", 373),
        ]

    def test_career_pitching_wins_template_is_planned_before_execution(self):
        import baseball_rag.db.grounded_database_runtime as grounded_database_runtime
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.routing import GroundedDatabaseQuestionCase, route

        assert not hasattr(grounded_database_runtime, "_template_source_detail")
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        planned = grounded_database_runtime.plan_query(
            "career pitching wins leaders", get_duckdb(), request_fn=mock_call
        )

        assert (
            grounded_database_runtime.can_plan_deterministically("career pitching wins leaders")
            is True
        )
        assert isinstance(route("career pitching wins leaders"), GroundedDatabaseQuestionCase)
        assert mock_call.call_count == 0
        assert planned.planning_path == "deterministic_template"
        assert planned.params == [25]
        assert planned.source_label == "Deterministic template query"
        assert "career pitching wins leaders template" in planned.source_detail
        assert "SUM(pi.W) AS career_W" in planned.sql

    def test_plain_batting_leaderboard_stays_on_stat_route(self):
        from baseball_rag.db.grounded_database_runtime import can_plan_deterministically
        from baseball_rag.db.grounded_database_templates import match_template
        from baseball_rag.routing import StatQueryCase, route

        matched = match_template("career home run leaders")

        assert matched is not None
        assert matched.template_id == "career_home_runs"
        assert matched.should_route(competing_stat="HR") is False
        assert matched.should_route(competing_stat=None) is True
        assert can_plan_deterministically("career home run leaders") is True
        assert isinstance(route("career home run leaders"), StatQueryCase)

    def test_plain_season_era_leaderboard_stays_on_stat_route(self):
        from baseball_rag.db.grounded_database_runtime import can_plan_deterministically
        from baseball_rag.routing import StatQueryCase, route

        assert can_plan_deterministically("who had the best ERA in 1968") is True
        assert isinstance(route("who had the best ERA in 1968"), StatQueryCase)
        assert isinstance(route("best ERA in 1968"), StatQueryCase)

    def test_runtime_executes_planned_query_without_result_shape_changes(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import execute_plan, plan_query, query

        conn = get_duckdb()
        planned = plan_query("career pitching wins leaders", conn)
        planned_result = execute_plan(planned, conn)
        direct_result = query("career pitching wins leaders", conn)

        assert planned_result == direct_result
        assert planned_result.params == [25]
        assert planned_result.source_label == "Deterministic template query"
        assert planned_result.rows[:3] == [
            ("Cy Young", 511),
            ("Walter Johnson", 417),
            ("Pete Alexander", 373),
        ]

    def test_grounded_database_runtime_planning_surface_exposes_deterministic_queries(self):
        import baseball_rag.db.grounded_database_runtime as grounded_database_runtime
        from baseball_rag.db.duckdb_schema import get_duckdb

        conn = get_duckdb()
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))

        planned = grounded_database_runtime.plan_query(
            "career pitching wins leaders", conn, request_fn=mock_call
        )
        result = grounded_database_runtime.query(
            "career pitching wins leaders", conn, request_fn=mock_call
        )

        assert mock_call.call_count == 0
        assert (
            grounded_database_runtime.can_plan_deterministically("career pitching wins leaders")
            is True
        )
        assert (
            grounded_database_runtime.should_route_deterministic_grounded_database(
                "career pitching wins leaders",
                competing_stat="W",
            )
            is True
        )
        assert planned.planning_path == "deterministic_template"
        assert planned.params == [25]
        assert result.params == planned.params
        assert result.rows[:3] == [
            ("Cy Young", 511),
            ("Walter Johnson", 417),
            ("Pete Alexander", 373),
        ]

    def test_qualified_season_era_template_bypasses_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query(
            "who had the lowest ERA in 1968 with enough innings", request_fn=mock_call
        )

        assert mock_call.call_count == 0
        assert result.params == [1968, 300, 300]
        assert ("Luis Tiant", 1968, "AL", 1.6, 775) in result.rows
        assert ("Bob Gibson", 1968, "NL", 1.12, 914) in result.rows

    def test_qualified_career_era_template_bypasses_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query(
            "career ERA leaders qualified by enough innings", request_fn=mock_call
        )

        assert mock_call.call_count == 0
        assert result.params == [3000]
        assert result.rows[0] == ("Ed Walsh", 1.82, 8893)

    def test_career_era_accepts_explicit_innings_guard(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query(
            "career ERA leaders with at least 1000 innings", request_fn=mock_call
        )

        assert mock_call.call_count == 0
        assert result.params == [3000]
        assert result.rows[0] == ("Ed Walsh", 1.82, 8893)

    def test_ambiguous_500_club_is_unsupported_without_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("who is in the 500 club", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.row_count == 0
        assert result.columns == ["unsupported_reason"]
        assert result.unsupported_reason == "ambiguous"

    def test_matched_template_exposes_route_ownership_and_unsupported_policy(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import plan_query

        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        planned = plan_query("who is in the 500 club", get_duckdb(), request_fn=mock_call)

        assert mock_call.call_count == 0
        assert planned.planning_path == "deterministic_template"
        assert planned.unsupported_reason == "ambiguous"
        assert planned.source_detail == (
            "Matched local deterministic grounded database SQL template."
        )
        assert planned.params == [
            "The question says 500 club but does not specify home runs or pitching wins."
        ]

    @pytest.mark.parametrize(
        ("question", "expected_team"),
        [
            ("who played for the Braves in 1936", "Boston Braves"),
            ("who played for the Braves%' OR 1=1 -- in 1936", "Boston Braves"),
            ("who played for the Yankees in 1950", "New York Yankees"),
        ],
    )
    def test_roster_template_bypasses_llm_with_parameterized_team_year(
        self, question: str, expected_team: str
    ):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query(question, request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.row_count >= 10
        assert "?" in result.sql
        assert "OR 1=1" not in result.sql
        assert expected_team in {row[1] for row in result.rows}

    def test_roster_template_exposes_local_match_facts_and_query_spec(self):
        from baseball_rag.db.grounded_database_templates import match_template

        matched = match_template("who played for the Braves in 1936")

        assert matched is not None
        assert matched.template_id == "team_season_roster"
        assert matched.match_facts["team_nickname"] == "braves"
        assert matched.match_facts["year"] == 1936
        assert matched.query_spec is not None
        assert matched.query_spec.team_name_pattern == "Braves"
        assert matched.query_spec.year_value == 1936

    @pytest.mark.parametrize(
        ("question", "expected_team", "expected_year"),
        [
            ("Braves roster nineteen thirty six", "Boston Braves", 1936),
            ("Yankees roster nineteen fifty", "New York Yankees", 1950),
            ("Braves roster twenty twenty two", "Atlanta Braves", 2022),
        ],
    )
    def test_roster_template_bypasses_llm_with_spoken_year(
        self, question: str, expected_team: str, expected_year: int
    ):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query(question, request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.row_count >= 10
        assert result.params[-1] == expected_year
        assert expected_team in {row[1] for row in result.rows}

    def test_qualified_batting_average_template_bypasses_llm_with_ab_guard(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("highest batting average in 1894", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.params == [1894, 100, 100]
        assert "AB >= ?" in result.sql
        assert result.columns == ["name", "yearID", "lgID", "AVG", "AB"]
        assert "batting average" in result.source_detail
        assert "ERA" not in result.source_detail

    def test_qualified_batting_average_seasons_template_does_not_require_year(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("best qualified batting average seasons", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.unsupported_reason is None
        assert result.params == [100]
        assert "AB >= ?" in result.sql
        assert result.rows[0] == ("Levi Meyerle", 1871, "NA", 0.492, 130)

    def test_qualified_era_seasons_template_does_not_require_year(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("best qualified ERA seasons", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.unsupported_reason is None
        assert result.params == [300]
        assert "IPouts >= ?" in result.sql
        assert result.rows[0] == ("Dick Redding", 1917, "WES", 0.82, 461)

    def test_underqualified_era_is_unsupported_without_llm(self):
        mock_call = MagicMock(side_effect=AssertionError("template should not call the LLM"))
        result = self._run_query("career ERA leaders", request_fn=mock_call)

        assert mock_call.call_count == 0
        assert result.row_count == 0
        assert result.columns == ["unsupported_reason"]
        assert result.unsupported_reason == "unsupported"

    def test_schema_uses_registry_formula_notes(self):
        import baseball_rag.db.grounded_database_schema as schema
        from baseball_rag.db.duckdb_schema import get_duckdb

        schema._cached_schema = None
        text = schema._get_schema_cached(get_duckdb())

        assert "batting: OPS =" in text
        assert "minimum sample: AB >= 100" in text
        assert "lower values rank better" in text

    def test_avg_and_era_templates_use_registry_stat_semantics(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import query
        from baseball_rag.db.stat_registry import get_stat

        conn = get_duckdb()
        avg_result = query("highest batting average in 1894", conn)
        era_result = query("career ERA leaders qualified by enough innings", conn)

        assert get_stat("AVG").expression("b") in avg_result.sql
        assert get_stat("AVG").sample_clause("b", threshold="?") in avg_result.sql
        assert get_stat("ERA").aggregate_expression("pi") in era_result.sql
        assert get_stat("ERA").sample_clause("pi", aggregate=True, threshold="?") in era_result.sql
        assert "batting average" in avg_result.source_detail
        assert "career ERA leaders template" in era_result.source_detail


class TestParseIntent:
    """Tests for the intent parser -- LLM output -> Intent dataclass."""

    def test_parses_valid_intent_json(self):
        from baseball_rag.db.grounded_database_intent import _parse_intent

        raw = (
            '{"stat_tables": ["batting", "pitching"], '
            '"team_name_pattern": "Braves", "year_value": 1936}'
        )
        intent = _parse_intent(raw)

        assert intent.stat_tables == ["batting", "pitching"]
        assert intent.team_name_pattern == "Braves"
        assert intent.year_value == 1936

    def test_parses_minimal_intent(self):
        from baseball_rag.db.grounded_database_intent import _parse_intent

        raw = '{"stat_tables": ["batting"]}'
        intent = _parse_intent(raw)

        assert intent.stat_tables == ["batting"]
        assert intent.team_name_pattern is None
        assert intent.year_value is None

    def test_strips_markdown_fences(self):
        from baseball_rag.db.grounded_database_intent import _parse_intent

        raw = '```json\n{"stat_tables": ["fielding"], "team_name_pattern": "Giants"}\n```'
        intent = _parse_intent(raw)

        assert intent.stat_tables == ["fielding"]
        assert intent.team_name_pattern == "Giants"

    def test_raises_on_malformed_json(self):
        from baseball_rag.db.grounded_database_intent import _parse_intent

        with pytest.raises(ValueError, match="Could not determine"):
            _parse_intent("not valid json at all")

    def test_raises_when_stat_tables_missing(self):
        from baseball_rag.db.grounded_database_intent import _parse_intent

        with pytest.raises(ValueError, match="stat_tables"):
            _parse_intent('{"team_name_pattern": "Braves"}')


class TestDeterminismSmokeSuite:
    """Smoke tests verifying deterministic output across semantically identical inputs.

    The property under test: equivalent question phrasings must produce identical
    row counts (same players, same SQL). This is the core guarantee of our
    intent-decomposition design -- if this fails, model variance has crept back in.
    """

    def _run_query(self, question: str) -> tuple[int, list[tuple]]:
        from baseball_rag.db.grounded_database_runtime import query

        conn = __import__(
            "baseball_rag.db.duckdb_schema",
            fromlist=["get_duckdb"],
        ).get_duckdb()
        result = query(question, conn)
        return result.row_count, result.rows

    @pytest.mark.llm
    def test_braves_1936_variants(self):
        """All phrasings of 'Braves 1936' must return identical row counts."""
        questions = [
            "Who played for the Braves in 1936?",
            "Who were the Braves players in 1936?",
            "What players were on the Atlanta Braves in 1936?",
            "Braves roster nineteen thirty six",
        ]
        results = [self._run_query(q) for q in questions]
        counts = [r[0] for r in results]

        assert len(set(counts)) == 1, "Non-deterministic row counts across variants: " + ", ".join(
            f"{q}->{c}" for (q,), c in zip(questions, counts)
        )

    @pytest.mark.llm
    def test_braves_2022_variants(self):
        """All phrasings of 'Braves 2022' must return identical row counts."""
        questions = [
            "Who played for the Braves in 2022?",
            "What players were on the Atlanta Braves in 2022?",
            "Braves roster twenty twenty two",
        ]
        results = [self._run_query(q) for q in questions]
        counts = [r[0] for r in results]

        assert len(set(counts)) == 1, "Non-deterministic row counts across variants: " + ", ".join(
            f"{q}->{c}" for (q,), c in zip(questions, counts)
        )

    @pytest.mark.llm
    def test_yankees_1950_variants(self):
        """All phrasings of 'Yankees 1950' must return identical row counts."""
        questions = [
            "Who played for the Yankees in 1950?",
            "What players were on the New York Yankees in 1950?",
            "Yankees roster nineteen fifty",
        ]
        results = [self._run_query(q) for q in questions]
        counts = [r[0] for r in results]

        assert len(set(counts)) == 1, "Non-deterministic row counts across variants: " + ", ".join(
            f"{q}->{c}" for (q,), c in zip(questions, counts)
        )


class TestGenerateQuerySpecDeterminism:
    """Integration-style tests verifying deterministic planning for the same inputs."""

    def test_same_prompt_produces_same_query_spec_twice(self):
        """Identical calls with same intent should produce the same typed query spec."""
        import json

        from baseball_rag.db.grounded_database_intent import _generate_query_spec

        # Mock the LLM to return a known intent JSON
        raw_response = json.dumps(
            {
                "stat_tables": ["batting"],
                "team_name_pattern": "Braves",
                "year_value": 1936,
            }
        )

        mock_resp = MagicMock()
        mock_resp.content = raw_response

        def fake_request(*_args, **_kwargs):
            return mock_resp

        spec1 = _generate_query_spec(
            "Who played for the Braves in 1936?", "schema", request_fn=fake_request
        )
        spec2 = _generate_query_spec(
            "Who played for the Braves in 1936?", "schema", request_fn=fake_request
        )

        assert spec1 == spec2, f"Non-deterministic query spec: {spec1!r} != {spec2!r}"

    def test_generate_query_spec_calls_llm_once(self):
        """_generate_query_spec should make exactly one LLM call per invocation."""
        from baseball_rag.db.grounded_database_intent import _generate_query_spec

        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Braves", "year_value": 1936}'
        )

        mock_call = MagicMock(return_value=mock_resp)

        _generate_query_spec("Who played for the Braves in 1936?", "schema", request_fn=mock_call)

        assert mock_call.call_count == 1

    def test_missing_stat_tables_after_retry_is_not_recovered_from_roster_shape(self):
        from baseball_rag.db.grounded_database_intent import _generate_query_spec

        first_response = MagicMock()
        first_response.content = '{"team_name_pattern": "Braves", "year_value": 1936}'
        retry_response = MagicMock()
        retry_response.content = '{"team_name_pattern": "Braves", "year_value": 1936}'
        mock_call = MagicMock(side_effect=[first_response, retry_response])

        with pytest.raises(ValueError, match="stat_tables"):
            _generate_query_spec(
                "Who played for the Braves in 1936?",
                "schema",
                request_fn=mock_call,
            )

        assert mock_call.call_count == 2

    def test_roster_intent_is_planned_before_execution_without_llm(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import can_plan_deterministically, plan_query

        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Yankees", "year_value": 1950}'
        )

        mock_call = MagicMock(return_value=mock_resp)

        planned = plan_query(
            "Who played for the Yankees in 1950?", get_duckdb(), request_fn=mock_call
        )

        assert can_plan_deterministically("Who played for the Yankees in 1950?") is True
        assert mock_call.call_count == 0
        assert planned.planning_path == "deterministic_template"
        assert planned.params == ["%yankees%", 1950]
        assert planned.source_label == "Deterministic template query"
        assert "roster template" in planned.source_detail
        assert planned.query_spec is not None
        assert planned.query_spec.stat_tables == ["batting"]

    def test_historical_team_identity_is_typed_before_sql_assembly(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import plan_query

        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Braves", "year_value": 1936}'
        )

        mock_call = MagicMock(return_value=mock_resp)
        planned = plan_query(
            "Braves batting records in 1936",
            get_duckdb(),
            request_fn=mock_call,
        )

        assert planned.planning_path == "llm_intent"
        assert mock_call.call_count == 1
        assert planned.query_spec is not None
        assert planned.query_spec.team_identity is not None
        assert planned.query_spec.team_identity.team_id == "BSN"
        assert planned.query_spec.team_identity.year == 1936
        assert planned.params == ["BSN", 1936]
        assert "batting.teamID = ?" in planned.sql

    def test_router_year_can_feed_historical_team_identity_when_llm_omits_year(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import plan_query

        mock_resp = MagicMock()
        mock_resp.content = '{"stat_tables": ["batting"], "team_name_pattern": "Braves"}'

        mock_call = MagicMock(return_value=mock_resp)
        planned = plan_query(
            "Braves batting records",
            get_duckdb(),
            year=1936,
            request_fn=mock_call,
        )

        assert planned.planning_path == "llm_intent"
        assert mock_call.call_count == 1
        assert planned.query_spec is not None
        assert planned.query_spec.year_value == 1936
        assert planned.query_spec.team_identity is not None
        assert planned.query_spec.team_identity.team_id == "BSN"
        assert planned.params == ["BSN", 1936]

    @pytest.mark.parametrize(
        ("question", "team_pattern", "year", "team_id"),
        [
            ("Braves batting records in 1953", "Braves", 1953, "ML1"),
            ("Athletics batting records in 1955", "Athletics", 1955, "KC1"),
            ("Marlins batting records in 1993", "Marlins", 1993, "FLO"),
            ("Angels batting records in 2005", "Angels", 2005, "LAA"),
        ],
    )
    def test_historical_team_identity_matches_loaded_stat_team_ids(
        self, question: str, team_pattern: str, year: int, team_id: str
    ):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.grounded_database_runtime import execute_plan, plan_query

        conn = get_duckdb()
        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], '
            f'"team_name_pattern": "{team_pattern}", "year_value": {year}}}'
        )

        mock_call = MagicMock(return_value=mock_resp)
        planned = plan_query(question, conn, request_fn=mock_call)
        result = execute_plan(planned, conn)

        assert planned.planning_path == "llm_intent"
        assert mock_call.call_count == 1
        assert planned.query_spec is not None
        assert planned.query_spec.team_identity is not None
        assert planned.query_spec.team_identity.team_id == team_id
        assert planned.params == [team_id, year]
        assert result.row_count > 0


class TestGroundedDatabaseProvenance:
    """Focused tests for source labels on grounded database query paths."""

    @pytest.mark.parametrize(
        ("question", "detail"),
        [
            ("Who won the Triple Crown and which years?", "Triple Crown template"),
            ("Show me 30-30 club seasons", "30-30 club template"),
            ("Who is in the 500 HR club?", "500 HR club template"),
            ("Career pitching wins leaders", "career pitching wins leaders template"),
        ],
    )
    def test_deterministic_template_source_label(self, question: str, detail: str):
        from baseball_rag.routing import GroundedDatabaseQuestionCase
        from baseball_rag.service import _answer_grounded_database_question

        decision = GroundedDatabaseQuestionCase(
            raw_question=question,
        )

        with patch(
            "baseball_rag.generation.llm.make_request",
            side_effect=AssertionError("deterministic template should not call the LLM"),
        ):
            result = _answer_grounded_database_question(decision.raw_question, decision)

        assert result.sources[0].label == "Deterministic template query"
        assert detail in (result.sources[0].detail or "")

    def test_llm_backed_grounded_database_source_label(self):
        from baseball_rag.routing import GroundedDatabaseQuestionCase
        from baseball_rag.service import _answer_grounded_database_question

        decision = GroundedDatabaseQuestionCase(
            raw_question="Which Mariners hitters had batting records in 1977?",
        )
        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Mariners", "year_value": 1977}'
        )

        with patch("baseball_rag.generation.llm.make_request", return_value=mock_resp):
            result = _answer_grounded_database_question(decision.raw_question, decision)

        assert result.sources[0].label == "LLM-backed typed grounded database query"
        assert "typed intent" in (result.sources[0].detail or "")

    def test_roster_answer_includes_historical_team_name_without_llm(self):
        from baseball_rag.service import answer

        with patch(
            "baseball_rag.generation.llm.make_request",
            side_effect=AssertionError("roster template should not call the LLM"),
        ):
            result = answer("who played for the Braves in 1936")

        assert result.intent == "grounded_database_question"
        assert "Braves" in result.answer
        assert result.sources[0].rows
        assert result.sources[0].columns == ["name", "teamName", "yearID"]
        assert "name" in result.sources[0].rows[0]
        assert "nameFirst" not in result.sources[0].rows[0]
        assert "nameLast" not in result.sources[0].rows[0]
        assert result.sources[0].sql and "?" in result.sources[0].sql

    def test_llm_flavored_grounded_database_answer_uses_verified_stats(self, monkeypatch):
        from baseball_rag.generation.llm import LLMResponse
        from baseball_rag.service import answer

        seen_prompts = []

        def fake_llm(prompt, **_kwargs):
            seen_prompts.append(prompt)
            return LLMResponse(
                content="Rogers Hornsby won the Triple Crown in 1922 with verified stats.",
                model="test-model",
                done=True,
            )

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

        result = answer(
            "who won the Triple Crown and which years",
            answer_mode="llm_flavored",
        )

        assert result.answer == ("Rogers Hornsby won the Triple Crown in 1922 with verified stats.")
        assert result.metadata["answer_mode"] == "llm_flavored"
        assert result.sources[0].type == "duckdb"
        assert result.sources[0].rows
        assert seen_prompts
        assert "Hornsby" in str(seen_prompts[0])
        assert "152" in str(seen_prompts[0])

    def test_grounded_database_answer_uses_query_scope_for_relative_single_season_year(
        self,
        monkeypatch,
    ):
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult
        from baseball_rag.routing import GroundedDatabaseQuestionCase
        from baseball_rag.routing.query_router import TimePeriod, TimePeriodType
        from baseball_rag.service import _answer_grounded_database_question

        monkeypatch.setenv("GROUNDBALL_CURRENT_YEAR", "1937")
        decision = GroundedDatabaseQuestionCase(
            raw_question="Who played for the Braves last year?",
            time_period=TimePeriod(
                type=TimePeriodType.RELATIVE,
                value={"direction": "past", "unit": "year", "count": 1},
            ),
        )
        result = GroundedDatabaseResult(
            sql="SELECT nameFirst FROM batting WHERE yearID = ?",
            rows=[("Hank",)],
            columns=["nameFirst"],
            row_count=1,
            truncated=False,
        )

        with patch("baseball_rag.db.grounded_database_runtime.query", return_value=result) as query:
            _answer_grounded_database_question(decision.raw_question, decision)

        assert decision.time_period.type == TimePeriodType.RELATIVE
        assert query.call_args.kwargs["year"] == 1936

    def test_grounded_database_answer_truncates_source_rows_and_warns(self):
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult
        from baseball_rag.routing import GroundedDatabaseQuestionCase
        from baseball_rag.service import _answer_grounded_database_question

        decision = GroundedDatabaseQuestionCase(raw_question="show players")
        result = GroundedDatabaseResult(
            sql="SELECT name FROM people",
            rows=[(f"Player {index}",) for index in range(150)],
            columns=["name"],
            row_count=150,
            truncated=True,
            source_label="LLM-backed typed grounded database query",
            source_detail="LLM extracted a typed intent.",
        )

        with patch("baseball_rag.db.grounded_database_runtime.query", return_value=result):
            answer = _answer_grounded_database_question(decision.raw_question, decision)

        assert answer.intent == "grounded_database_question"
        assert answer.warnings == ["Results were truncated at the configured row limit."]
        assert answer.sources[0].rows == [{"name": f"Player {index}"} for index in range(100)]
        assert answer.sources[0].columns == ["name"]
        assert answer.sources[0].sql == "SELECT name FROM people"
        assert answer.sources[0].data_manifest["dataset"]["name"] == "NeuML/baseballdata"

    @pytest.mark.parametrize(
        (
            "unsupported_reason",
            "columns",
            "expected_reason",
            "expected_review_reason",
            "expected_answer_text",
        ),
        [
            (
                "ambiguous",
                ["unsupported_reason"],
                "ambiguous",
                "ambiguous",
                "unsupported detail",
            ),
            (
                "unsupported",
                ["unsupported_reason"],
                "unsupported",
                "unsupported",
                "unsupported detail",
            ),
            (
                None,
                ["name"],
                "no_data",
                "unsupported",
                "Try rephrasing with a specific team, player, stat, or year.",
            ),
        ],
    )
    def test_grounded_database_zero_row_answer_preserves_unsupported_mapping(
        self,
        unsupported_reason: str | None,
        columns: list[str],
        expected_reason: str,
        expected_review_reason: str,
        expected_answer_text: str,
    ):
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult
        from baseball_rag.routing import GroundedDatabaseQuestionCase
        from baseball_rag.service import _answer_grounded_database_question

        decision = GroundedDatabaseQuestionCase(raw_question="who is in the 500 club")
        result = GroundedDatabaseResult(
            sql="SELECT ? AS unsupported_reason WHERE FALSE",
            rows=[],
            columns=columns,
            row_count=0,
            truncated=False,
            params=["unsupported detail"],
            source_label="Deterministic template query",
            source_detail="Matched local deterministic grounded database SQL template.",
            unsupported_reason=unsupported_reason,
        )

        with patch("baseball_rag.db.grounded_database_runtime.query", return_value=result):
            answer = _answer_grounded_database_question(decision.raw_question, decision)

        assert answer.unsupported is True
        assert answer.unsupported_reason == expected_reason
        assert answer.review_reason == expected_review_reason
        assert expected_answer_text in answer.answer
        assert answer.sources[0].label == "Deterministic template query"
        assert answer.sources[0].rows == []


class TestGroundedDatabaseResultFormatting:
    """Tests for display-quality grounded database answer formatting."""

    def test_player_roster_result_formats_names_without_python_tuples(self):
        from baseball_rag.db.grounded_database_runtime import format_result
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

        result = GroundedDatabaseResult(
            sql="select distinct p.nameFirst, p.nameLast from people p",
            rows=[
                ("Wally Berger",),
                ("Rabbit Warstler",),
                ("Mickey Haslin",),
            ],
            columns=["name"],
            row_count=37,
            truncated=False,
        )

        text = format_result(result, "Who played for the Braves in 1936?")

        assert text.startswith("37 players matched:")
        assert "- Wally Berger" in text
        assert "- Rabbit Warstler" in text
        assert "['name']" not in text
        assert "('Wally Berger',)" not in text

    def test_generic_result_formats_rows_as_labeled_values(self):
        from baseball_rag.db.grounded_database_runtime import format_result
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

        result = GroundedDatabaseResult(
            sql="select name, career_HR from leaders",
            rows=[("Babe Ruth", 714)],
            columns=["name", "career_HR"],
            row_count=1,
            truncated=False,
        )

        text = format_result(result, "500 home run club")

        assert text == "1 result matched:\n- name: Babe Ruth; career_HR: 714"
        assert "('Babe Ruth', 714)" not in text

    def test_triple_crown_result_formats_winners_for_reading(self):
        from baseball_rag.db.grounded_database_runtime import format_result
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

        result = GroundedDatabaseResult(
            sql="select name, yearID, lgID, HR, RBI, AVG from triple_crown",
            rows=[
                ("Nap Lajoie", 1901, "AL", 14, 125, 0.426),
                ("Rogers Hornsby", 1922, "NL", 42, 152, 0.401),
            ],
            columns=["name", "yearID", "lgID", "HR", "RBI", "AVG"],
            row_count=2,
            truncated=False,
            source_detail="Matched local Triple Crown template.",
        )

        text = format_result(result, "who won the Triple Crown and which years")

        assert text == (
            "2 Triple Crown seasons matched:\n"
            "- Nap Lajoie (AL, 1901): 14 HR, 125 RBI, .426 AVG\n"
            "- Rogers Hornsby (NL, 1922): 42 HR, 152 RBI, .401 AVG"
        )
        assert "yearID:" not in text

    def test_triple_crown_formatter_requires_question_or_source_context(self):
        from baseball_rag.db.grounded_database_runtime import format_result
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

        result = GroundedDatabaseResult(
            sql="select name, yearID, lgID, HR, RBI, AVG from batting",
            rows=[("Babe Ruth", 1921, "AL", 59, 168, 0.378)],
            columns=["name", "yearID", "lgID", "HR", "RBI", "AVG"],
            row_count=1,
            truncated=False,
            source_label="LLM-backed typed grounded database query",
            source_detail="Player batting season stats.",
        )

        text = format_result(result, "show Babe Ruth's stats during his Triple Crown chase")

        assert text == (
            "1 result matched:\n"
            "- name: Babe Ruth; yearID: 1921; lgID: AL; HR: 59; RBI: 168; AVG: 0.378"
        )
        assert "Triple Crown" not in text

    def test_large_result_notes_display_limit_even_when_not_runtime_truncated(self):
        from baseball_rag.db.grounded_database_runtime import format_result
        from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

        result = GroundedDatabaseResult(
            sql="select name from people",
            rows=[(f"First {index} Last {index}",) for index in range(150)],
            columns=["name"],
            row_count=150,
            truncated=False,
        )

        text = format_result(result, "show players")

        assert text.startswith("150 players matched, showing first 100:")
        assert "- First 99 Last 99" in text
        assert "- First 100 Last 100" not in text
