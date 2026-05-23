"""Tests for the shared request-to-answer execution spine."""

from unittest.mock import patch

import pytest

from baseball_rag.arch.tracing import finish_trace, get_current_trace, traced
from baseball_rag.conversation import conversation_turn
from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.request_execution import execute_request
from baseball_rag.routing import (
    GeneralExplanationCase,
    GroundedDatabaseQuestionCase,
    PlayerBiographyCase,
    StatQueryCase,
)


def test_execute_request_rejects_policy_unsupported_question_before_routing(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

    execution = execute_request(
        "who won the NBA finals in 2020",
        adapter_component_id="api",
        attach_review=True,
    )

    assert execution.answer.unsupported is True
    assert execution.answer.unsupported_reason == "unsupported"
    assert execution.answer.review["queued"] is True
    assert execution.answer.review["reason"] == "unsupported"


def test_execute_request_rejects_unknown_answer_mode():
    with pytest.raises(ValueError, match="Unsupported answer_mode"):
        execute_request(
            "who had the most RBIs in 1962",
            answer_mode="box_score_poetry",  # type: ignore[arg-type]
        )


def test_execute_request_allows_grounded_greatest_metric_question(tmp_path, monkeypatch):
    monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

    execution = execute_request("who had the greatest number of home runs in 1998")

    assert execution.answer.unsupported is False
    assert execution.answer.intent == "stat_query"
    assert "Mark" in execution.answer.answer
    assert "McGwire" in execution.answer.answer


def test_execute_request_replaces_stale_empty_trace_with_request_trace():
    """A stale internal trace must not contaminate the next adapter request."""
    with traced(component_id="orphan", label="Orphan Stage"):
        pass
    assert get_current_trace() is not None
    assert get_current_trace().query == ""

    with patch("baseball_rag.request_execution.answer") as answer:
        answer.return_value = StructuredAnswer(answer="OK", intent="general_explanation")

        execution = execute_request("what is OPS", adapter_component_id="api")

    assert execution.trace is not None
    assert execution.trace.query == "what is OPS"
    assert execution.trace.route_type == "general_explanation"
    assert get_current_trace() is None


def test_execute_request_preserves_caller_owned_trace():
    """Callers that started tracing explicitly keep ownership of finish_trace()."""
    from baseball_rag.arch.tracing import start_trace

    start_trace("outer question")

    with patch("baseball_rag.request_execution.answer") as answer:
        answer.return_value = StructuredAnswer(answer="OK", intent="stat_query")

        execution = execute_request("inner question", adapter_component_id="cli")

    assert execution.trace is get_current_trace()
    assert get_current_trace().query == "outer question"
    trace = finish_trace(route_type="stat_query")
    assert trace is not None
    assert trace.query == "outer question"


def test_execute_request_attaches_audit_and_review_once():
    """Audit metadata and review payload are attached once by the request spine."""
    with (
        patch("baseball_rag.request_execution.answer") as answer,
        patch("baseball_rag.audit.build_query_metadata") as build_metadata,
        patch("baseball_rag.review_queue.enqueue_review_item") as enqueue_review_item,
    ):
        structured = StructuredAnswer(answer="Nope", intent="stat_query", unsupported=True)
        answer.return_value = structured
        build_metadata.return_value = {"query_id": "q_test", "route": "stat_query"}
        enqueue_review_item.return_value = {"queued": True, "reason": "unsupported"}

        execution = execute_request(
            "who led MLB in vibes",
            adapter_component_id="api",
            attach_audit=True,
            attach_review=True,
        )

    assert execution.answer.metadata == {
        "answer_mode": "stats_only",
        "query_id": "q_test",
        "route": "stat_query",
    }
    assert execution.answer.review == {"queued": True, "reason": "unsupported"}
    build_metadata.assert_called_once()
    enqueue_review_item.assert_called_once_with("who led MLB in vibes", structured)


def test_execute_request_uses_governance_observation_after_answer_trace():
    calls = []

    with patch("baseball_rag.request_execution.answer") as answer:
        structured = StructuredAnswer(answer="Nope", intent="stat_query", unsupported=True)
        answer.return_value = structured

        def observe(self, question, observed_answer, *, trace):
            calls.append((self.mode, question, observed_answer, trace.route_type))
            observed_answer.metadata["observed"] = True
            return observed_answer

        with patch("baseball_rag.query_governance.QueryGovernance.observe", observe):
            execution = execute_request(
                "who led MLB in vibes",
                adapter_component_id="api",
                attach_audit=True,
                attach_review=True,
            )

    assert calls == [("audit_review", "who led MLB in vibes", structured, "stat_query")]
    assert execution.answer.metadata == {"answer_mode": "stats_only", "observed": True}


def test_execute_request_passes_conversation_to_answer_service():
    """Adapters can pass prior turns without changing trace ownership."""
    prior_turns = [
        {
            "question": "career home run leaders",
            "answer": {
                "answer": "All-time career HR leaders",
                "intent": "stat_query",
                "sources": [
                    {
                        "type": "duckdb",
                        "label": "Career HR leaders",
                        "rows": [
                            {"name": "Bonds, Barry", "stat_value": 762},
                            {"name": "Aaron, Hank", "stat_value": 755},
                        ],
                    }
                ],
            },
        }
    ]

    with patch("baseball_rag.request_execution.answer") as answer:
        answer.return_value = StructuredAnswer(answer="OK", intent="player_biography")

        execution = execute_request(
            "tell me about the second player",
            adapter_component_id="gradio",
            conversation=prior_turns,
        )

    assert execution.trace is not None
    assert execution.trace.query == "tell me about the second player"
    answer.assert_called_once_with(
        "tell me about the second player",
        conversation=prior_turns,
        answer_mode="stats_only",
    )


def test_execute_request_resolves_followup_dispatches_and_attaches_context(monkeypatch):
    """Follow-up context is resolved, answered, and annotated by the request path."""
    prior_turns = [
        conversation_turn(
            "career home run leaders",
            StructuredAnswer(
                answer="Career home run leaders",
                intent="stat_query",
                sources=[
                    SourceRecord(
                        type="duckdb",
                        label="Career HR leaders",
                        rows=[
                            {"name": "Bonds, Barry", "stat_value": 762},
                            {"name": "Aaron, Hank", "stat_value": 755},
                        ],
                    )
                ],
            ),
        )
    ]
    routed_questions = []

    def fake_route(question: str) -> PlayerBiographyCase:
        routed_questions.append(question)
        return PlayerBiographyCase(
            player_name="Hank Aaron",
            raw_question=question,
        )

    def fake_player_answer(question, decision):
        assert question == "tell me about Hank Aaron"
        assert decision.raw_question == "tell me about Hank Aaron"
        return StructuredAnswer(answer="Hank Aaron biography", intent="player_biography")

    monkeypatch.setattr("baseball_rag.service.route", fake_route)
    monkeypatch.setattr("baseball_rag.service._answer_player_biography", fake_player_answer)

    execution = execute_request(
        "tell me about the second player",
        adapter_component_id="gradio",
        conversation=prior_turns,
    )

    assert routed_questions == ["tell me about Hank Aaron"]
    assert execution.answer.answer == "Hank Aaron biography"
    assert execution.answer.metadata == {
        "original_question": "tell me about the second player",
        "answer_mode": "stats_only",
        "context_question": "tell me about Hank Aaron",
        "context_source": "career home run leaders",
        "context_player_name": "Hank Aaron",
    }
    assert execution.trace is not None
    assert execution.trace.route_type == "player_biography"


def test_execute_request_resolves_fifth_player_followup_from_prior_leaderboard(monkeypatch):
    """Ordinal follow-ups can reference the fifth row from a previous leaderboard."""
    prior_turns = [
        conversation_turn(
            "career home run leaders",
            StructuredAnswer(
                answer="Career home run leaders",
                intent="stat_query",
                sources=[
                    SourceRecord(
                        type="duckdb",
                        label="Career HR leaders",
                        rows=[
                            {"name": "Bonds, Barry", "stat_value": 762},
                            {"name": "Aaron, Hank", "stat_value": 755},
                            {"name": "Ruth, Babe", "stat_value": 714},
                            {"name": "Pujols, Albert", "stat_value": 703},
                            {"name": "Rodriguez, Alex", "stat_value": 696},
                        ],
                    )
                ],
            ),
        )
    ]
    routed_questions = []

    def fake_route(question: str) -> PlayerBiographyCase:
        routed_questions.append(question)
        return PlayerBiographyCase(
            player_name="Alex Rodriguez",
            raw_question=question,
        )

    def fake_player_answer(question, decision):
        assert question == "Tell me more about Alex Rodriguez in the list"
        assert decision.raw_question == "Tell me more about Alex Rodriguez in the list"
        return StructuredAnswer(answer="Alex Rodriguez biography", intent="player_biography")

    monkeypatch.setattr("baseball_rag.service.route", fake_route)
    monkeypatch.setattr("baseball_rag.service._answer_player_biography", fake_player_answer)

    execution = execute_request(
        "Tell me more about the fifth player in the list",
        adapter_component_id="gradio",
        conversation=prior_turns,
    )

    assert routed_questions == ["Tell me more about Alex Rodriguez in the list"]
    assert execution.answer.answer == "Alex Rodriguez biography"
    assert execution.answer.metadata == {
        "original_question": "Tell me more about the fifth player in the list",
        "answer_mode": "stats_only",
        "context_question": "Tell me more about Alex Rodriguez in the list",
        "context_source": "career home run leaders",
        "context_player_name": "Alex Rodriguez",
    }


def test_execute_request_does_not_rewrite_fifth_player_achievement_question(monkeypatch):
    """Ordinal achievement questions are routed as asked, not as row follow-ups."""
    prior_turns = [
        conversation_turn(
            "career home run leaders",
            StructuredAnswer(
                answer="Career home run leaders",
                intent="stat_query",
                sources=[
                    SourceRecord(
                        type="duckdb",
                        label="Career HR leaders",
                        rows=[
                            {"name": "Bonds, Barry", "stat_value": 762},
                            {"name": "Aaron, Hank", "stat_value": 755},
                            {"name": "Ruth, Babe", "stat_value": 714},
                            {"name": "Pujols, Albert", "stat_value": 703},
                            {"name": "Rodriguez, Alex", "stat_value": 696},
                        ],
                    )
                ],
            ),
        )
    ]
    routed_questions = []

    def fake_route(question: str) -> GeneralExplanationCase:
        routed_questions.append(question)
        return GeneralExplanationCase(raw_question=question)

    monkeypatch.setattr("baseball_rag.service.route", fake_route)
    monkeypatch.setattr(
        "baseball_rag.service._answer_general",
        lambda question, decision: StructuredAnswer(
            answer="General answer",
            intent=decision.intent,
        ),
    )

    execution = execute_request(
        "Tell me about the fifth player to hit 500 home runs",
        adapter_component_id="gradio",
        conversation=prior_turns,
    )

    assert routed_questions == ["Tell me about the fifth player to hit 500 home runs"]
    assert execution.answer.metadata == {"answer_mode": "stats_only"}


def test_execute_request_answers_routed_stat_case_through_service(monkeypatch):
    """Validated stat cases answer through the normal request path."""
    seen_cases = []

    def fake_route(question: str) -> StatQueryCase:
        return StatQueryCase(stat="RBI", raw_question=question)

    def fake_stat_answer(decision: StatQueryCase) -> StructuredAnswer:
        seen_cases.append(decision)
        return StructuredAnswer(answer="Top RBI leaders", intent=decision.intent)

    monkeypatch.setattr("baseball_rag.service.route", fake_route)
    monkeypatch.setattr("baseball_rag.service.answer_stat_query", fake_stat_answer)

    execution = execute_request("career RBI leaders", adapter_component_id="api")

    assert execution.answer.answer == "Top RBI leaders"
    assert seen_cases == [StatQueryCase(stat="RBI", raw_question="career RBI leaders")]


def test_execute_request_answers_fielding_putouts_through_stat_path():
    """Fielding PO requests answer through the public request execution path."""
    execution = execute_request("outfield putouts leaders in 1983", adapter_component_id="api")

    assert execution.answer.intent == "stat_query"
    assert "Top PO leaders (1983-1983):" in execution.answer.answer
    assert "Manning, Rick: 471 PO" in execution.answer.answer
    assert execution.answer.sources
    assert execution.answer.sources[0].type == "duckdb"
    assert execution.answer.sources[0].sql is not None
    assert "FROM fielding f" in execution.answer.sources[0].sql


def test_execute_request_grounds_player_stat_question_without_possessive():
    """Player stat questions without possessive wording still use DuckDB."""
    execution = execute_request(
        "What was Ted Williams batting average in 1941",
        adapter_component_id="api",
    )

    assert execution.answer.intent == "stat_query"
    assert "Williams, Ted" in execution.answer.answer
    assert "0.4057017543859649 AVG" in execution.answer.answer
    assert execution.answer.sources
    assert execution.answer.sources[0].type == "duckdb"
    assert execution.answer.sources[0].rows[0]["name"] == "Williams, Ted"


def test_execute_request_dispatches_new_routed_case_types(monkeypatch):
    """The request path dispatches each validated routed case by type."""
    player_case = PlayerBiographyCase(
        player_name="Hank Aaron",
        raw_question="who was Hank Aaron",
    )
    grounded_case = GroundedDatabaseQuestionCase(raw_question="who won the Triple Crown")
    general_case = GeneralExplanationCase(raw_question="what is OPS", stat="OPS")

    def fake_player_handler(
        _question: str,
        decision: PlayerBiographyCase,
    ) -> StructuredAnswer:
        assert decision is player_case
        return StructuredAnswer(answer="bio", intent=decision.intent)

    def fake_grounded_handler(
        _question: str,
        decision: GroundedDatabaseQuestionCase,
    ) -> StructuredAnswer:
        assert decision is grounded_case
        return StructuredAnswer(answer="grounded database", intent=decision.intent)

    def fake_general_handler(
        _question: str,
        decision: GeneralExplanationCase,
    ) -> StructuredAnswer:
        assert decision is general_case
        return StructuredAnswer(answer="general", intent=decision.intent)

    cases = [
        (player_case, "_answer_player_biography", fake_player_handler, "bio"),
        (
            grounded_case,
            "_answer_grounded_database_question",
            fake_grounded_handler,
            "grounded database",
        ),
        (general_case, "_answer_general", fake_general_handler, "general"),
    ]

    for routed, handler_name, fake_handler, expected in cases:
        monkeypatch.setattr("baseball_rag.service.route", lambda _question, routed=routed: routed)
        monkeypatch.setattr(f"baseball_rag.service.{handler_name}", fake_handler)

        execution = execute_request(routed.raw_question, adapter_component_id="api")

        assert execution.answer.answer == expected


def test_execute_request_rejects_unsupported_routed_case_type(monkeypatch):
    """The request path requires typed route cases."""
    monkeypatch.setattr("baseball_rag.service.route", lambda _question: object())

    with pytest.raises(TypeError, match="Unsupported routed case type"):
        execute_request("career home run leaders", adapter_component_id="api")
