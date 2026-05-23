import pytest

from baseball_rag.conversation import (
    ConversationResolution,
    attach_context_metadata,
    conversation_turn,
    resolve_followup,
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


def test_conversation_turn_preserves_grounded_database_name_for_followups():
    answer = StructuredAnswer(
        answer="1936 Braves roster",
        intent="grounded_database_question",
        sources=[
            SourceRecord(
                type="duckdb",
                label="Roster",
                rows=[
                    {
                        "name": "Wally Berger",
                        "teamName": "Boston Braves",
                        "yearID": 1936,
                        "extra": "drop",
                    }
                ],
            )
        ],
    )

    turn = conversation_turn("who played for the Braves in 1936", answer)

    assert turn["answer"]["sources"][0]["rows"] == [{"name": "Wally Berger"}]
    resolution = resolve_followup("tell me about the first player", [turn])
    assert resolution.resolved_question == "tell me about Wally Berger"
    assert resolution.referenced_player_name == "Wally Berger"


def test_conversation_turn_requires_structured_answer():
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

    with pytest.raises(TypeError, match="StructuredAnswer"):
        conversation_turn("career home run leaders", payload)


def test_raw_api_transcript_resolves_fifth_player_followup():
    prior_turns = [
        {
            "question": "career home run leaders",
            "answer": {
                "answer": "Career home run leaders",
                "intent": "stat_query",
                "sources": [
                    {
                        "type": "duckdb",
                        "label": "Career HR leaders",
                        "rows": [
                            {"name": "Bonds, Barry", "stat_value": 762},
                            {"name": "Aaron, Hank", "stat_value": 755},
                            {"name": "Ruth, Babe", "stat_value": 714},
                            {"name": "Pujols, Albert", "stat_value": 703},
                            {"name": "Rodriguez, Alex", "stat_value": 696},
                        ],
                    }
                ],
            },
        }
    ]

    resolution = resolve_followup("tell me about the fifth player", prior_turns)

    assert resolution.resolved_question == "tell me about Alex Rodriguez"
    assert resolution.referenced_player_name == "Alex Rodriguez"
    assert resolution.reference_kind == "ordinal_row"
    assert resolution.confidence == "high"


def test_pronoun_resolution_prefers_explicit_active_player_metadata():
    prior_turns = [
        {
            "question": "career home run leaders",
            "answer": {
                "metadata": {"context_player_name": "Hank Aaron"},
                "sources": [
                    {
                        "rows": [
                            {"name": "Bonds, Barry", "stat_value": 762},
                        ]
                    }
                ],
            },
        }
    ]

    resolution = resolve_followup("what about his RBI?", prior_turns)

    assert resolution.resolved_question == "what about Hank Aaron's RBI?"
    assert resolution.referenced_player_name == "Hank Aaron"
    assert resolution.reference_kind == "pronoun"


def test_malformed_transcript_entries_are_ignored_without_crashing():
    prior_turns = [
        {"question": "bad", "answer": None},
        {"question": 123, "answer": {"sources": "not rows"}},
        {
            "question": "career home run leaders",
            "answer": {
                "sources": [
                    {"rows": [None, {"name": "Ruth, Babe"}]},
                ],
            },
        },
    ]

    resolution = resolve_followup("tell me about the first player", prior_turns)

    assert resolution.resolved_question == "tell me about Babe Ruth"
    assert resolution.referenced_player_name == "Babe Ruth"


def test_unsupported_row_shape_preserves_ordinal_position():
    prior_turns = [
        {
            "question": "mixed row shapes",
            "answer": {
                "sources": [
                    {
                        "type": "duckdb",
                        "rows": [
                            {"full_name": "Babe Ruth"},
                            {"name": "Aaron, Hank"},
                        ],
                    }
                ]
            },
        },
    ]

    first_resolution = resolve_followup("tell me about the first player", prior_turns)
    second_resolution = resolve_followup("tell me about the second player", prior_turns)

    assert first_resolution.resolved_question == "tell me about the first player"
    assert first_resolution.referenced_player_name is None
    assert first_resolution.unsupported_reason == "player_name_not_found"
    assert second_resolution.resolved_question == "tell me about Hank Aaron"
    assert second_resolution.referenced_player_name == "Hank Aaron"


def test_raw_api_transcript_resolves_name_rows():
    prior_turns = [
        {
            "question": "who played for the Braves in 1936",
            "answer": {
                "sources": [
                    {
                        "type": "duckdb",
                        "rows": [
                            {
                                "name": "Wally Berger",
                                "teamName": "Boston Braves",
                            }
                        ],
                    }
                ]
            },
        }
    ]

    resolution = resolve_followup("tell me about the first player", prior_turns)

    assert resolution.resolved_question == "tell me about Wally Berger"


def test_recent_unsupported_row_shape_blocks_stale_followup_resolution():
    prior_turns = [
        {
            "question": "career home run leaders",
            "answer": {
                "sources": [
                    {
                        "type": "duckdb",
                        "rows": [{"name": "Bonds, Barry"}],
                    }
                ]
            },
        },
        {
            "question": "old client row shape",
            "answer": {
                "sources": [
                    {
                        "type": "duckdb",
                        "rows": [{"full_name": "Babe Ruth"}],
                    }
                ]
            },
        },
    ]

    resolution = resolve_followup("tell me about the first player", prior_turns)

    assert resolution.resolved_question == "tell me about the first player"
    assert resolution.referenced_player_name is None
    assert resolution.unsupported_reason == "player_name_not_found"


def test_compact_turn_with_recent_unsupported_row_shape_blocks_stale_resolution():
    older_turn = conversation_turn(
        "career home run leaders",
        StructuredAnswer(
            answer="Career leaders",
            intent="stat_query",
            sources=[
                SourceRecord(
                    type="duckdb",
                    label="Career HR leaders",
                    rows=[{"name": "Bonds, Barry"}],
                )
            ],
        ),
    )
    recent_turn = conversation_turn(
        "old client answer shape",
        StructuredAnswer(
            answer="Legacy answer",
            intent="stat_query",
            sources=[
                SourceRecord(
                    type="duckdb",
                    label="Legacy rows",
                    rows=[{"full_name": "Babe Ruth"}],
                )
            ],
        ),
    )

    resolution = resolve_followup("tell me about the first player", [older_turn, recent_turn])

    assert recent_turn["answer"]["sources"][0]["rows"] == [{}]
    assert resolution.resolved_question == "tell me about the first player"
    assert resolution.referenced_player_name is None
    assert resolution.unsupported_reason == "player_name_not_found"


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
