"""Tests for human-in-the-loop review queue helpers."""

from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.review_queue import (
    build_review_item,
    list_review_items,
    load_review_items,
    persist_review_item,
    resolve_review_item,
    review_payload,
    write_review_item,
)


def test_build_review_item_for_unsupported_answer_is_deterministic():
    answer = StructuredAnswer(
        answer="No grounded result found.",
        intent="stat_query",
        unsupported=True,
        metadata={"trace": {"route_type": "stat_query"}},
    )

    first = build_review_item("who led MLB in vibes", answer)
    second = build_review_item("who led MLB in vibes", answer)

    assert first is not None
    assert first.reason == "unsupported"
    assert first.id == second.id
    assert first.audit["route"] == "stat_query"


def test_build_review_item_detects_ambiguous_warning():
    answer = StructuredAnswer(
        answer="'Johnson' is ambiguous in the local player registry.",
        intent="player_biography",
        warnings=["No biography was generated because the player name was ambiguous."],
        unsupported=True,
    )

    item = build_review_item("who was Johnson", answer)

    assert item is not None
    assert item.reason == "ambiguous"


def test_build_review_item_detects_low_confidence_chroma_source():
    answer = StructuredAnswer(
        answer="Possibly relevant context.",
        intent="general_explanation",
        sources=[SourceRecord(type="chroma", label="OPS", score=0.2)],
    )

    item = build_review_item("what is ops", answer, low_confidence_threshold=0.4)

    assert item is not None
    assert item.reason == "low_confidence"


def test_review_payload_and_jsonl_round_trip(tmp_path):
    answer = StructuredAnswer(
        answer="No grounded result found.",
        intent="stat_query",
        unsupported=True,
    )
    item = build_review_item("who led MLB in vibes", answer)
    path = tmp_path / "review.jsonl"

    write_review_item(path, item)

    assert review_payload(item) == {"queued": True, "reason": "unsupported", "item_id": item.id}
    assert load_review_items(path) == [item]


def test_review_id_ignores_volatile_trace_metadata():
    first = StructuredAnswer(
        answer="No grounded result found.",
        intent="stat_query",
        unsupported=True,
        metadata={"trace": {"total_ms": 1.0}, "latency_ms": 1.0},
    )
    second = StructuredAnswer(
        answer="No grounded result found.",
        intent="stat_query",
        unsupported=True,
        metadata={"trace": {"total_ms": 9.0}, "latency_ms": 9.0},
    )

    assert (
        build_review_item("who led MLB in vibes", first).id
        == build_review_item("who led MLB in vibes", second).id
    )


def test_persist_list_and_resolve_review_items(tmp_path):
    path = tmp_path / "review.jsonl"
    item = build_review_item(
        "who led MLB in vibes",
        StructuredAnswer(answer="No grounded result found.", intent="stat_query", unsupported=True),
    )

    persist_review_item(item, path=path)
    persist_review_item(item, path=path)

    assert list_review_items(path=path) == [item]
    resolved = resolve_review_item(item.id, "resolved", note="covered by guardrail", path=path)
    open_items = list_review_items(path=path, status="open")
    all_items = list_review_items(path=path, status="all")

    assert open_items == []
    assert all_items == [resolved]
    assert resolved.status == "resolved"
    assert resolved.resolution_note == "covered by guardrail"


def test_persist_skips_duplicate_open_snapshot_with_new_timestamp(tmp_path):
    path = tmp_path / "review.jsonl"
    answer = StructuredAnswer(
        answer="No grounded result found.",
        intent="stat_query",
        unsupported=True,
        metadata={"query_id": "q_same"},
    )
    first = build_review_item("who led MLB in vibes", answer)
    second = build_review_item("who led MLB in vibes", answer)

    assert first.id == second.id
    assert first.created_at != second.created_at

    persist_review_item(first, path=path)
    persist_review_item(second, path=path)

    assert load_review_items(path) == [first]


def test_resolve_unknown_review_item_raises(tmp_path):
    try:
        resolve_review_item("review_missing", "resolved", path=tmp_path / "review.jsonl")
    except KeyError as exc:
        assert "review_missing" in str(exc)
    else:
        raise AssertionError("expected KeyError")
