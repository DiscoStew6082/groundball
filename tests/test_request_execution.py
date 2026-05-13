"""Tests for the shared request-to-answer execution spine."""

from unittest.mock import patch

from baseball_rag.arch.tracing import finish_trace, get_current_trace, traced
from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.request_execution import execute_request
from baseball_rag.routing import (
    FreeformQueryCase,
    GeneralExplanationCase,
    PlayerBiographyCase,
    RouteResult,
    StatQueryCase,
)


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
        patch("baseball_rag.review_queue.build_review_item") as build_review_item,
        patch("baseball_rag.review_queue.persist_review_item") as persist_review_item,
        patch("baseball_rag.review_queue.review_payload") as review_payload,
    ):
        structured = StructuredAnswer(answer="Nope", intent="stat_query", unsupported=True)
        answer.return_value = structured
        build_metadata.return_value = {"query_id": "q_test", "route": "stat_query"}
        build_review_item.return_value = object()
        review_payload.return_value = {"queued": True, "reason": "unsupported"}

        execution = execute_request(
            "who led MLB in vibes",
            adapter_component_id="api",
            attach_audit=True,
            attach_review=True,
        )

    assert execution.answer.metadata == {"query_id": "q_test", "route": "stat_query"}
    assert execution.answer.review == {"queued": True, "reason": "unsupported"}
    build_metadata.assert_called_once()
    build_review_item.assert_called_once_with("who led MLB in vibes", structured)
    persist_review_item.assert_called_once_with(build_review_item.return_value)
    review_payload.assert_called_once_with(build_review_item.return_value)


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
    answer.assert_called_once_with("tell me about the second player", conversation=prior_turns)


def test_execute_request_resolves_followup_dispatches_and_attaches_context(monkeypatch):
    """Follow-up context is resolved, answered, and annotated by the request path."""
    prior_turns = [
        {
            "question": "career home run leaders",
            "answer": StructuredAnswer(
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
        }
    ]
    routed_questions = []

    def fake_route(question: str) -> RouteResult:
        routed_questions.append(question)
        return RouteResult(
            intent="player_biography",
            stat=None,
            player_name="Hank Aaron",
            raw_question=question,
        )

    def fake_player_answer(question, decision, *, retrieval_strategy=None):
        assert question == "tell me about Hank Aaron"
        assert decision.raw_question == "tell me about Hank Aaron"
        return StructuredAnswer(answer="Hank Aaron biography", intent="player_biography")

    monkeypatch.setattr("baseball_rag.service.init_db", lambda: None)
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
        "context_question": "tell me about Hank Aaron",
        "context_source": "career home run leaders",
        "context_player_name": "Hank Aaron",
    }
    assert execution.trace is not None
    assert execution.trace.route_type == "player_biography"


def test_execute_request_answers_routed_stat_case_through_service(monkeypatch):
    """Validated stat cases answer through the normal request path."""
    seen_cases = []

    def fake_route(question: str) -> StatQueryCase:
        return StatQueryCase(stat="RBI", raw_question=question)

    def fake_stat_answer(decision: StatQueryCase) -> StructuredAnswer:
        seen_cases.append(decision)
        return StructuredAnswer(answer="Top RBI leaders", intent=decision.intent)

    monkeypatch.setattr("baseball_rag.service.init_db", lambda: None)
    monkeypatch.setattr("baseball_rag.service.route", fake_route)
    monkeypatch.setattr("baseball_rag.service.answer_stat_query", fake_stat_answer)

    execution = execute_request("career RBI leaders", adapter_component_id="api")

    assert execution.answer.answer == "Top RBI leaders"
    assert seen_cases == [StatQueryCase(stat="RBI", raw_question="career RBI leaders")]


def test_execute_request_dispatches_new_routed_case_types(monkeypatch):
    """The request path dispatches each validated routed case by type."""
    cases = [
        (
            PlayerBiographyCase(player_name="Hank Aaron", raw_question="who was Hank Aaron"),
            "_answer_player_biography",
            "bio",
        ),
        (
            FreeformQueryCase(raw_question="who won the Triple Crown"),
            "_answer_freeform",
            "freeform",
        ),
        (
            GeneralExplanationCase(raw_question="what is OPS", stat="OPS"),
            "_answer_general",
            "general",
        ),
    ]

    for routed, handler_name, expected in cases:
        monkeypatch.setattr("baseball_rag.service.init_db", lambda: None)
        monkeypatch.setattr("baseball_rag.service.route", lambda _question, routed=routed: routed)

        def fake_handler(*args, expected=expected, **kwargs):
            decision = args[1]
            assert decision is routed
            return StructuredAnswer(answer=expected, intent=decision.intent)

        monkeypatch.setattr(f"baseball_rag.service.{handler_name}", fake_handler)

        execution = execute_request(routed.raw_question, adapter_component_id="api")

        assert execution.answer.answer == expected


def test_execute_request_normalizes_legacy_stat_route_result(monkeypatch):
    """Legacy RouteResult compatibility is converted at the dispatch boundary."""
    seen_cases = []
    legacy = RouteResult(
        intent="stat_query",
        stat="HR",
        raw_question="career home run leaders",
    )

    monkeypatch.setattr("baseball_rag.service.init_db", lambda: None)
    monkeypatch.setattr("baseball_rag.service.route", lambda _question: legacy)

    def fake_stat_answer(decision: StatQueryCase) -> StructuredAnswer:
        seen_cases.append(decision)
        return StructuredAnswer(answer="Top HR leaders", intent=decision.intent)

    monkeypatch.setattr("baseball_rag.service.answer_stat_query", fake_stat_answer)

    execution = execute_request("career home run leaders", adapter_component_id="api")

    assert execution.answer.answer == "Top HR leaders"
    assert seen_cases == [StatQueryCase(stat="HR", raw_question="career home run leaders")]
