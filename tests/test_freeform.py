"""Tests for freeform query -- intent-based SQL generation (deterministic by design)."""

from unittest.mock import MagicMock, patch

import pytest


class TestAssembleSQL:
    """Unit tests for the deterministic SQL assembler.

    _assemble_sql(intent) must always produce the same SQL for the same intent,
    regardless of what the LLM might have returned. No LLM calls -- pure function.
    """

    def test_assembles_batting_only(self):
        from baseball_rag.db.freeform import QueryIntent, _assemble_sql

        intent = QueryIntent(
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
        from baseball_rag.db.freeform import QueryIntent, _assemble_sql

        intent = QueryIntent(
            stat_tables=["batting", "pitching"],
            team_name_pattern="Yankees",
            year_value=1950,
        )
        sql = _assemble_sql(intent)

        assert "union" in sql.sql.lower()
        assert "batting" in sql.sql.lower()
        assert "pitching" in sql.sql.lower()

    def test_assembles_without_year(self):
        from baseball_rag.db.freeform import QueryIntent, _assemble_sql

        intent = QueryIntent(stat_tables=["batting"], team_name_pattern="Cubs")
        sql = _assemble_sql(intent)

        assert sql.params == ["%Cubs%"]
        # No year filter means no 1936 etc.
        assert "yearid" not in sql.sql.lower() or "BETWEEN" not in sql.sql.upper()

    def test_always_distinct(self):
        from baseball_rag.db.freeform import QueryIntent, _assemble_sql

        intent = QueryIntent(
            stat_tables=["batting", "pitching"],
            team_name_pattern="Dodgers",
            year_value=1955,
        )
        sql = _assemble_sql(intent)

        # DISTINCT must be present to avoid duplicate players appearing twice
        assert "distinct" in sql.sql.lower()


class TestDeterministicTemplates:
    """Tests for common freeform patterns that should bypass the LLM."""

    def _run_query(self, question: str):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.freeform import query

        return query(question, get_duckdb())

    def test_triple_crown_template_bypasses_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("who won the Triple Crown and which years")

        assert mock_call.call_count == 0
        assert result.params == [300]
        assert {"nameFirst", "nameLast", "yearID", "HR", "RBI", "AVG"} <= set(result.columns)
        assert ("Rogers", "Hornsby", 1922, "NL", 42, 152, 0.401) in result.rows
        assert all(row[3] in ("AL", "NL") for row in result.rows)

    def test_thirty_thirty_template_bypasses_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("show me 30-30 club seasons")

        assert mock_call.call_count == 0
        assert result.params == [30, 30]
        assert ("Hank", "Aaron", 1963, 44, 31) in result.rows

    def test_500_home_run_club_template_bypasses_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("500 home run club")

        assert mock_call.call_count == 0
        assert result.params == [500]
        assert result.rows[0] == ("Barry", "Bonds", 762)
        assert ("Babe", "Ruth", 714) in result.rows

    def test_career_pitching_wins_template_bypasses_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("career pitching wins leaders with at least 500 wins")

        assert mock_call.call_count == 0
        assert result.params == [500]
        assert result.rows == [("Cy", "Young", 511)]

    def test_career_pitching_wins_leaders_without_threshold(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("career pitching wins leaders")

        assert mock_call.call_count == 0
        assert result.params == [25]
        assert result.rows[:3] == [
            ("Cy", "Young", 511),
            ("Walter", "Johnson", 417),
            ("Pete", "Alexander", 373),
        ]

    def test_career_pitching_wins_template_is_planned_before_execution(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.freeform import can_plan_deterministically, plan_query
        from baseball_rag.routing import FreeformQueryCase, route

        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            planned = plan_query("career pitching wins leaders", get_duckdb())

        assert can_plan_deterministically("career pitching wins leaders") is True
        assert isinstance(route("career pitching wins leaders"), FreeformQueryCase)
        assert mock_call.call_count == 0
        assert planned.planning_path == "deterministic_template"
        assert planned.params == [25]
        assert planned.source_label == "Deterministic template query"
        assert "career pitching wins leaders template" in planned.source_detail
        assert "SUM(pi.W) AS career_W" in planned.sql

    def test_plain_batting_leaderboard_stays_on_stat_route(self):
        from baseball_rag.db.freeform import can_plan_deterministically
        from baseball_rag.routing import StatQueryCase, route

        assert can_plan_deterministically("career home run leaders") is True
        assert isinstance(route("career home run leaders"), StatQueryCase)

    def test_plain_season_era_leaderboard_stays_on_stat_route(self):
        from baseball_rag.db.freeform import can_plan_deterministically
        from baseball_rag.routing import StatQueryCase, route

        assert can_plan_deterministically("who had the best ERA in 1968") is True
        assert isinstance(route("who had the best ERA in 1968"), StatQueryCase)
        assert isinstance(route("best ERA in 1968"), StatQueryCase)

    def test_runtime_executes_planned_query_without_result_shape_changes(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.freeform import execute_plan, plan_query, query

        conn = get_duckdb()
        planned = plan_query("career pitching wins leaders", conn)
        planned_result = execute_plan(planned, conn)
        direct_result = query("career pitching wins leaders", conn)

        assert planned_result == direct_result
        assert planned_result.params == [25]
        assert planned_result.source_label == "Deterministic template query"
        assert planned_result.rows[:3] == [
            ("Cy", "Young", 511),
            ("Walter", "Johnson", 417),
            ("Pete", "Alexander", 373),
        ]

    def test_qualified_season_era_template_bypasses_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("who had the lowest ERA in 1968 with enough innings")

        assert mock_call.call_count == 0
        assert result.params == [1968, 300, 300]
        assert ("Luis", "Tiant", 1968, "AL", 1.6, 775) in result.rows
        assert ("Bob", "Gibson", 1968, "NL", 1.12, 914) in result.rows

    def test_qualified_career_era_template_bypasses_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("career ERA leaders qualified by enough innings")

        assert mock_call.call_count == 0
        assert result.params == [3000]
        assert result.rows[0] == ("Ed", "Walsh", 1.82, 8893)

    def test_career_era_accepts_explicit_innings_guard(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("career ERA leaders with at least 1000 innings")

        assert mock_call.call_count == 0
        assert result.params == [3000]
        assert result.rows[0] == ("Ed", "Walsh", 1.82, 8893)

    def test_ambiguous_500_club_is_unsupported_without_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("who is in the 500 club")

        assert mock_call.call_count == 0
        assert result.row_count == 0
        assert result.columns == ["unsupported_reason"]
        assert result.unsupported_reason == "ambiguous"

    def test_underqualified_era_is_unsupported_without_llm(self):
        with patch("baseball_rag.db.freeform.make_request") as mock_call:
            result = self._run_query("career ERA leaders")

        assert mock_call.call_count == 0
        assert result.row_count == 0
        assert result.columns == ["unsupported_reason"]
        assert result.unsupported_reason == "unsupported"


class TestParseIntent:
    """Tests for the intent parser -- LLM output -> Intent dataclass."""

    def test_parses_valid_intent_json(self):
        from baseball_rag.db.freeform import _parse_intent

        raw = (
            '{"stat_tables": ["batting", "pitching"], '
            '"team_name_pattern": "Braves", "year_value": 1936}'
        )
        intent = _parse_intent(raw)

        assert intent.stat_tables == ["batting", "pitching"]
        assert intent.team_name_pattern == "Braves"
        assert intent.year_value == 1936

    def test_parses_minimal_intent(self):
        from baseball_rag.db.freeform import _parse_intent

        raw = '{"stat_tables": ["batting"]}'
        intent = _parse_intent(raw)

        assert intent.stat_tables == ["batting"]
        assert intent.team_name_pattern is None
        assert intent.year_value is None

    def test_strips_markdown_fences(self):
        from baseball_rag.db.freeform import _parse_intent

        raw = '```json\n{"stat_tables": ["fielding"], "team_name_pattern": "Giants"}\n```'
        intent = _parse_intent(raw)

        assert intent.stat_tables == ["fielding"]
        assert intent.team_name_pattern == "Giants"

    def test_raises_on_malformed_json(self):
        from baseball_rag.db.freeform import _parse_intent

        with pytest.raises(ValueError, match="Could not determine"):
            _parse_intent("not valid json at all")

    def test_raises_when_stat_tables_missing(self):
        from baseball_rag.db.freeform import _parse_intent

        with pytest.raises(ValueError, match="stat_tables"):
            _parse_intent('{"team_name_pattern": "Braves"}')


class TestDeterminismSmokeSuite:
    """Smoke tests verifying deterministic output across semantically identical inputs.

    The property under test: equivalent question phrasings must produce identical
    row counts (same players, same SQL). This is the core guarantee of our
    intent-decomposition design -- if this fails, model variance has crept back in.
    """

    def _run_query(self, question: str) -> tuple[int, list[tuple]]:
        from baseball_rag.db.freeform import query

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


class TestGenerateSQLDeterminism:
    """Integration-style tests verifying deterministic output for the same inputs."""

    def test_same_prompt_produces_same_sql_twice(self):
        """Identical calls with same intent should produce byte-for-byte identical SQL."""
        import json

        from baseball_rag.db.freeform import _generate_sql

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

        with patch("baseball_rag.db.freeform.make_request", return_value=mock_resp):
            sql1 = _generate_sql("Who played for the Braves in 1936?", "schema")
            sql2 = _generate_sql("Who played for the Braves in 1936?", "schema")

        assert sql1 == sql2, f"Non-deterministic SQL: {sql1!r} != {sql2!r}"

    def test_generate_sql_calls_llm_once(self):
        """_generate_sql should make exactly one LLM call per invocation."""
        from baseball_rag.db.freeform import _generate_sql

        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Braves", "year_value": 1936}'
        )

        with patch("baseball_rag.db.freeform.make_request", return_value=mock_resp) as mock_call:
            _generate_sql("Who played for the Braves in 1936?", "schema")
            assert mock_call.call_count == 1

    def test_llm_intent_is_planned_before_execution(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.freeform import can_plan_deterministically, plan_query

        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Yankees", "year_value": 1950}'
        )

        with patch("baseball_rag.db.freeform.make_request", return_value=mock_resp) as mock_call:
            planned = plan_query("Who played for the Yankees in 1950?", get_duckdb())

        assert can_plan_deterministically("Who played for the Yankees in 1950?") is False
        assert mock_call.call_count == 1
        assert planned.planning_path == "llm_intent"
        assert planned.params == ["%Yankees%", 1950]
        assert planned.source_label == "LLM-backed typed freeform query"
        assert "typed intent" in planned.source_detail
        assert planned.query_spec is not None
        assert planned.query_spec.stat_tables == ["batting"]

    def test_historical_team_identity_is_typed_before_sql_assembly(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.freeform import plan_query

        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Braves", "year_value": 1936}'
        )

        with patch("baseball_rag.db.freeform.make_request", return_value=mock_resp):
            planned = plan_query("Who played for the Braves in 1936?", get_duckdb())

        assert planned.query_spec is not None
        assert planned.query_spec.team_identity is not None
        assert planned.query_spec.team_identity.team_id == "BSN"
        assert planned.query_spec.team_identity.year == 1936
        assert planned.params == ["BSN", 1936]
        assert "batting.teamID = ?" in planned.sql

    def test_router_year_can_feed_historical_team_identity_when_llm_omits_year(self):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.freeform import plan_query

        mock_resp = MagicMock()
        mock_resp.content = '{"stat_tables": ["batting"], "team_name_pattern": "Braves"}'

        with patch("baseball_rag.db.freeform.make_request", return_value=mock_resp):
            planned = plan_query("Who played for the Braves?", get_duckdb(), year=1936)

        assert planned.query_spec is not None
        assert planned.query_spec.year_value == 1936
        assert planned.query_spec.team_identity is not None
        assert planned.query_spec.team_identity.team_id == "BSN"
        assert planned.params == ["BSN", 1936]

    @pytest.mark.parametrize(
        ("question", "team_pattern", "year", "team_id"),
        [
            ("Who played for the Braves in 1953?", "Braves", 1953, "ML1"),
            ("Who played for the Athletics in 1955?", "Athletics", 1955, "KC1"),
            ("Who played for the Marlins in 1993?", "Marlins", 1993, "FLO"),
            ("Who played for the Angels in 2005?", "Angels", 2005, "LAA"),
        ],
    )
    def test_historical_team_identity_matches_loaded_stat_team_ids(
        self, question: str, team_pattern: str, year: int, team_id: str
    ):
        from baseball_rag.db.duckdb_schema import get_duckdb
        from baseball_rag.db.freeform import execute_plan, plan_query

        conn = get_duckdb()
        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], '
            f'"team_name_pattern": "{team_pattern}", "year_value": {year}}}'
        )

        with patch("baseball_rag.db.freeform.make_request", return_value=mock_resp):
            planned = plan_query(question, conn)
            result = execute_plan(planned, conn)

        assert planned.query_spec is not None
        assert planned.query_spec.team_identity is not None
        assert planned.query_spec.team_identity.team_id == team_id
        assert planned.params == [team_id, year]
        assert result.row_count > 0


class TestFreeformProvenance:
    """Focused tests for source labels on freeform query paths."""

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
        from types import SimpleNamespace

        from baseball_rag.service import _answer_freeform

        decision = SimpleNamespace(
            intent="freeform_query",
            raw_question=question,
        )

        with patch(
            "baseball_rag.db.freeform.make_request",
            side_effect=AssertionError("deterministic template should not call the LLM"),
        ):
            result = _answer_freeform(decision.raw_question, decision)

        assert result.sources[0].label == "Deterministic template query"
        assert detail in (result.sources[0].detail or "")

    def test_llm_backed_freeform_source_label(self):
        from types import SimpleNamespace

        from baseball_rag.service import _answer_freeform

        decision = SimpleNamespace(
            intent="freeform_query",
            raw_question="Who played for the Braves in 1936?",
        )
        mock_resp = MagicMock()
        mock_resp.content = (
            '{"stat_tables": ["batting"], "team_name_pattern": "Braves", "year_value": 1936}'
        )

        with patch("baseball_rag.db.freeform.make_request", return_value=mock_resp):
            result = _answer_freeform(decision.raw_question, decision)

        assert result.sources[0].label == "LLM-backed typed freeform query"
        assert "typed intent" in (result.sources[0].detail or "")


class TestFreeformResultFormatting:
    """Tests for display-quality freeform answer formatting."""

    def test_player_roster_result_formats_names_without_python_tuples(self):
        from baseball_rag.db.freeform import format_result
        from baseball_rag.db.freeform_types import FreeformResult

        result = FreeformResult(
            sql="select distinct p.nameFirst, p.nameLast from people p",
            rows=[
                ("Wally", "Berger"),
                ("Rabbit", "Warstler"),
                ("Mickey", "Haslin"),
            ],
            columns=["nameFirst", "nameLast"],
            row_count=37,
            truncated=False,
        )

        text = format_result(result, "Who played for the Braves in 1936?")

        assert text.startswith("37 players matched:")
        assert "- Wally Berger" in text
        assert "- Rabbit Warstler" in text
        assert "['nameFirst', 'nameLast']" not in text
        assert "('Wally', 'Berger')" not in text

    def test_generic_result_formats_rows_as_labeled_values(self):
        from baseball_rag.db.freeform import format_result
        from baseball_rag.db.freeform_types import FreeformResult

        result = FreeformResult(
            sql="select nameFirst, nameLast, career_HR from leaders",
            rows=[("Babe", "Ruth", 714)],
            columns=["nameFirst", "nameLast", "career_HR"],
            row_count=1,
            truncated=False,
        )

        text = format_result(result, "500 home run club")

        assert text == "1 result matched:\n- nameFirst: Babe; nameLast: Ruth; career_HR: 714"
        assert "('Babe', 'Ruth', 714)" not in text

    def test_large_result_notes_display_limit_even_when_not_runtime_truncated(self):
        from baseball_rag.db.freeform import format_result
        from baseball_rag.db.freeform_types import FreeformResult

        result = FreeformResult(
            sql="select nameFirst, nameLast from people",
            rows=[(f"First {index}", f"Last {index}") for index in range(150)],
            columns=["nameFirst", "nameLast"],
            row_count=150,
            truncated=False,
        )

        text = format_result(result, "show players")

        assert text.startswith("150 players matched, showing first 100:")
        assert "- First 99 Last 99" in text
        assert "- First 100 Last 100" not in text
