from baseball_rag.conversation import (
    ConversationResolution,
    attach_context_metadata,
    conversation_turn,
)
from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.routing import PlayerBiographyCase


def test_conversation_turn_preserves_only_followup_relevant_answer_fields():
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
                    {
                        "name": "Davis, Tommy",
                        "year": 1962,
                        "team": "LAN",
                        "stat_value": 153,
                        "extra": "drop",
                    }
                ],
            )
        ],
        metadata={
            "context_player_name": "Tommy Davis",
            "original_question": "who led RBI",
            "debug": "drop",
        },
    )

    assert conversation_turn("who led RBI in 1962", answer) == {
        "question": "who led RBI in 1962",
        "answer": {
            "answer": "Tommy Davis led MLB with 153 RBI.",
            "intent": "stat_query",
            "metadata": {
                "original_question": "who led RBI",
                "context_player_name": "Tommy Davis",
            },
            "sources": [
                {
                    "type": "duckdb",
                    "label": "RBI leaders",
                    "rows": [
                        {
                            "name": "Davis, Tommy",
                            "year": 1962,
                            "team": "LAN",
                            "stat_value": 153,
                        }
                    ],
                }
            ],
        },
    }


def test_conversation_turn_accepts_raw_answer_payload_dict():
    payload = {
        "answer": "All-time career HR leaders",
        "intent": "stat_query",
        "metadata": {"context_player_name": "Barry Bonds", "debug": "drop"},
        "sources": [
            {
                "type": "duckdb",
                "label": "Career HR leaders",
                "rows": [
                    {"name": "Bonds, Barry", "stat_value": 762, "extra": "drop"},
                ],
            }
        ],
    }

    turn = conversation_turn("career home run leaders", payload)

    assert turn["answer"]["metadata"] == {"context_player_name": "Barry Bonds"}
    assert turn["answer"]["sources"][0]["rows"] == [{"name": "Bonds, Barry", "stat_value": 762}]


def test_attach_context_metadata_preserves_resolved_player_context():
    answer = StructuredAnswer(answer="Hank Aaron biography", intent="player_biography")
    resolution = ConversationResolution(
        resolved_question="tell me about Hank Aaron",
        referenced_player_name="Hank Aaron",
        source_turn="career home run leaders",
        confidence="high",
    )

    attach_context_metadata(
        answer,
        original_question="tell me about the second player",
        resolution=resolution,
        decision=PlayerBiographyCase(player_name="Hank Aaron"),
    )

    assert answer.metadata == {
        "original_question": "tell me about the second player",
        "context_question": "tell me about Hank Aaron",
        "context_source": "career home run leaders",
        "context_player_name": "Hank Aaron",
    }


def test_attach_context_metadata_does_not_add_player_context_to_unsupported_answers():
    answer = StructuredAnswer(
        answer="Nope",
        intent="player_biography",
        unsupported=True,
    )
    resolution = ConversationResolution(
        resolved_question="tell me about Hank Aaron",
        referenced_player_name="Hank Aaron",
        source_turn="career home run leaders",
        confidence="high",
    )

    attach_context_metadata(
        answer,
        original_question="tell me about the second player",
        resolution=resolution,
        decision=PlayerBiographyCase(player_name="Hank Aaron"),
    )

    assert answer.metadata == {
        "original_question": "tell me about the second player",
        "context_question": "tell me about Hank Aaron",
        "context_source": "career home run leaders",
    }


def test_attach_context_metadata_omits_context_fields_without_source_turn():
    answer = StructuredAnswer(answer="Nope", intent="player_biography", unsupported=True)
    resolution = ConversationResolution(
        resolved_question="who was Babe Ruth",
        referenced_player_name="Babe Ruth",
        confidence="high",
    )

    attach_context_metadata(
        answer,
        original_question="who was he",
        resolution=resolution,
        decision=PlayerBiographyCase(player_name="Babe Ruth"),
    )

    assert answer.metadata == {}
