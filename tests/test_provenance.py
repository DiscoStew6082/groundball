"""Tests for structured answer provenance payloads."""

from baseball_rag.provenance import StructuredAnswer


def test_structured_answer_serializes_metadata():
    answer = StructuredAnswer(
        answer="Tommy Davis led MLB with 153 RBI.",
        intent="stat_query",
        metadata={"route": "stat_query", "latency_ms": 12.5},
    )

    assert answer.to_dict()["metadata"] == {"route": "stat_query", "latency_ms": 12.5}
