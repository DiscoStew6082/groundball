"""Tests for UI-facing answer presentation policy."""

from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.ui.presentation import AnswerPresenter


def test_presenter_builds_gradio_payload_and_compact_conversation_turn():
    """A StructuredAnswer becomes display panels plus compact follow-up context."""
    answer = StructuredAnswer(
        answer="Tommy Davis led MLB with 153 RBI.",
        intent="stat_query",
        sources=[
            SourceRecord(
                type="duckdb",
                label="RBI leaders",
                sql="select * from batting",
                columns=["name", "year", "stat_value"],
                rows=[
                    {"name": "Davis, Tommy", "year": 1962, "stat_value": 153, "extra": "drop"},
                ],
                data_manifest={"files": [{"path": "data/Batting.csv", "table": "batting"}]},
            )
        ],
        warnings=["Results were truncated."],
        metadata={"context_player_name": "Tommy Davis", "debug": "drop"},
    )

    presentation = AnswerPresenter().present(answer)

    assert presentation.answer_text == "Tommy Davis led MLB with 153 RBI."
    assert presentation.rows == {
        "headers": ["name", "year", "stat_value"],
        "data": [["Davis, Tommy", 1962, 153]],
    }
    assert presentation.sources[0]["data_manifest"]["files"] == [
        {"file_path": "data/Batting.csv", "table": "batting"}
    ]
    assert presentation.sql == "select * from batting"
    assert presentation.chat_message == (
        "Tommy Davis led MLB with 153 RBI.\n\nWarning: Results were truncated."
    )

    assert presentation.conversation_turn("who led RBI in 1962") == {
        "question": "who led RBI in 1962",
        "answer": {
            "answer": "Tommy Davis led MLB with 153 RBI.",
            "intent": "stat_query",
            "metadata": {"context_player_name": "Tommy Davis"},
            "sources": [
                {
                    "type": "duckdb",
                    "label": "RBI leaders",
                    "rows": [
                        {"name": "Davis, Tommy", "year": 1962, "stat_value": 153},
                    ],
                }
            ],
        },
    }


def test_presenter_uses_biography_verification_rows_when_first_source_is_identity():
    """Biography answers show consensus evidence even when identity is the first source."""
    answer = StructuredAnswer(
        answer="Babe Ruth biography.",
        intent="player_biography",
        sources=[
            SourceRecord(
                type="duckdb",
                label="DuckDB biography resolution",
                columns=["player_id", "name"],
                rows=[{"player_id": "ruthba01", "name": "Babe Ruth"}],
            ),
            SourceRecord(
                type="duckdb",
                label="DuckDB Lahman + Retrosheet biography stat consensus",
                sql="select consensus evidence",
                columns=["stat", "claimed_value", "consensus_status"],
                rows=[
                    {
                        "stat": "HR",
                        "claimed_value": 714,
                        "consensus_status": "verified_by_all",
                    }
                ],
            ),
        ],
    )

    presentation = AnswerPresenter().present(answer)

    assert presentation.rows == {
        "headers": ["stat", "claimed_value", "consensus_status"],
        "data": [["HR", 714, "verified_by_all"]],
    }
    assert presentation.sql == "select consensus evidence"
    assert [source["label"] for source in presentation.sources] == [
        "DuckDB biography resolution",
        "DuckDB Lahman + Retrosheet biography stat consensus",
    ]
