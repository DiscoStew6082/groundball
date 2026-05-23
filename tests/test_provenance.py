"""Tests for structured answer provenance payloads."""

from baseball_rag.audit import unsupported_reason
from baseball_rag.outcomes import (
    ambiguous_outcome,
    local_request_failure_outcome,
    no_data_outcome,
    timeout_outcome,
)
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.review_queue import build_review_item


def test_structured_answer_serializes_metadata():
    answer = StructuredAnswer(
        answer="Tommy Davis led MLB with 153 RBI.",
        intent="stat_query",
        metadata={"route": "stat_query", "latency_ms": 12.5},
        review={"queued": True, "reason": "unsupported", "item_id": "review_abc"},
    )

    assert answer.to_dict()["metadata"] == {"route": "stat_query", "latency_ms": 12.5}
    assert answer.to_dict()["review"] == {
        "queued": True,
        "reason": "unsupported",
        "item_id": "review_abc",
    }


def test_ambiguous_outcome_sets_audit_and_review_reason_without_prose_sniffing():
    answer = ambiguous_outcome(
        answer="Multiple matching players were found.",
        intent="player_biography",
        warnings=["Choose a fuller name."],
    )

    assert answer.unsupported is True
    assert answer.unsupported_reason == "ambiguous"
    assert answer.review_reason == "ambiguous"
    assert unsupported_reason(answer) == "ambiguous"

    item = build_review_item("who was Johnson", answer)

    assert item is not None
    assert item.reason == "ambiguous"


def test_no_data_outcome_is_unsupported_but_reviews_as_unsupported():
    answer = no_data_outcome(
        answer="No results found.",
        intent="stat_query",
        warnings=["No alternate answer was returned."],
    )

    assert answer.unsupported is True
    assert answer.unsupported_reason == "no_data"
    assert answer.review_reason is None
    assert build_review_item("who led MLB in vibes", answer).reason == "unsupported"


def test_timeout_and_local_request_failures_share_llm_unavailable_reason():
    timeout = timeout_outcome(TimeoutError("slow"))
    failure = local_request_failure_outcome(ValueError("bad shape"))

    assert timeout.unsupported_reason == "llm_unavailable"
    assert failure.unsupported_reason == "llm_unavailable"
    assert timeout.warnings == ["slow"]
    assert failure.warnings == ["bad shape"]
