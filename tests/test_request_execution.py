"""Tests for the shared request-to-answer execution spine."""

from unittest.mock import patch

from baseball_rag.arch.tracing import finish_trace, get_current_trace, traced
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.request_execution import execute_request


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
