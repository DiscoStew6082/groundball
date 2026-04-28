"""Tests for audit-ready query metadata."""

from baseball_rag.audit import build_query_metadata, eval_category_for_question, sql_template_hash
from baseball_rag.provenance import SourceRecord, StructuredAnswer


def test_sql_template_hash_uses_normalized_parameterized_sql():
    first = "SELECT *\nFROM batting WHERE yearID = ?;"
    second = " SELECT * FROM batting WHERE yearID = ? "

    assert sql_template_hash(first) == sql_template_hash(second)
    assert sql_template_hash(first).startswith("sha256:")


def test_eval_category_matches_exact_manifest_question():
    match = eval_category_for_question("who had the most RBIs in 1962")

    assert match == {"matched": True, "case_id": "stat_rbi_1962", "category": "stat_query"}
    assert eval_category_for_question("who had the most RBIs in 1962 please") == {
        "matched": False,
        "case_id": None,
        "category": None,
    }


def test_build_query_metadata_is_deterministic_except_timestamp_and_latency():
    answer = StructuredAnswer(
        answer="Davis, Tommy: 153 RBI",
        intent="stat_query",
        sources=[
            SourceRecord(
                type="duckdb",
                label="RBI leaderboard",
                sql="SELECT * FROM batting WHERE yearID = ?",
                rows=[{"name": "Davis, Tommy"}],
            )
        ],
    )

    first = build_query_metadata("who had the most RBIs in 1962", answer, trace=None)
    second = build_query_metadata("who had the most RBIs in 1962", answer, trace=None)

    assert first["query_id"] == second["query_id"]
    assert first["sql"]["template_hash"] == second["sql"]["template_hash"]
    assert first["sql"]["row_count"] == 1
    assert first["dataset"]["name"] == "NeuML/baseballdata"
    assert first["model"]["prompt_version"] == "grounded-answer-v1"
    assert first["eval"]["case_id"] == "stat_rbi_1962"
    assert first["timestamp"]
