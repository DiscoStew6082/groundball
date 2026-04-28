"""Tests for retrieval strategy selection and call behavior."""

from pathlib import Path

from baseball_rag.retrieval.chroma_store import RetrievedChunk
from baseball_rag.retrieval.strategies import (
    ExactPlayerIdStrategy,
    HybridPlayerBioStrategy,
    SemanticChromaStrategy,
    available_strategy_metadata,
    available_strategy_names,
    get_strategy,
)


def _chunk(title: str = "Babe Ruth") -> RetrievedChunk:
    return RetrievedChunk(text=f"{title} profile", source="test.md", title=title, score=0.95)


def test_available_strategy_names_includes_initial_benchmarks():
    assert available_strategy_names() == [
        "semantic_chroma",
        "exact_player_id",
        "hybrid_player_bio",
    ]


def test_strategy_metadata_declares_applicability_categories():
    metadata = {item.name: item for item in available_strategy_metadata()}

    assert metadata["semantic_chroma"].categories == frozenset(
        {"player_biography", "general_explanation"}
    )
    assert metadata["exact_player_id"].categories == frozenset({"player_biography"})
    assert metadata["exact_player_id"].requires_player_id is True
    assert metadata["hybrid_player_bio"].categories == frozenset({"player_biography"})


def test_strategy_applicability_uses_category_and_player_id_requirements():
    assert SemanticChromaStrategy().is_applicable(category="general_explanation")
    assert ExactPlayerIdStrategy().is_applicable(
        category="player_biography",
        player_id="ruthba01",
    )
    assert not ExactPlayerIdStrategy().is_applicable(category="player_biography")
    assert not HybridPlayerBioStrategy().is_applicable(category="general_explanation")


def test_semantic_chroma_uses_unfiltered_vector_search():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        return [_chunk()]

    strategy = SemanticChromaStrategy(retrieve_fn=fake_retrieve)

    result = strategy.retrieve("who was Babe Ruth", top_k=5, persist_dir=Path("store"))

    assert result
    assert calls == [
        {
            "query": "who was Babe Ruth",
            "top_k": 5,
            "persist_dir": Path("store"),
            "where": None,
        }
    ]


def test_exact_player_id_requires_a_resolved_player_id():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        return [_chunk()]

    strategy = ExactPlayerIdStrategy(retrieve_fn=fake_retrieve)

    assert strategy.retrieve("who was Babe Ruth", player_name="Babe Ruth") == []
    result = strategy.retrieve(
        "who was Babe Ruth",
        top_k=3,
        persist_dir=Path("store"),
        player_name="Babe Ruth",
        player_id="ruthba01",
    )

    assert result
    assert calls == [
        {
            "query": "Babe Ruth",
            "top_k": 1,
            "persist_dir": Path("store"),
            "where": {"player_id": "ruthba01"},
        }
    ]


def test_hybrid_player_bio_falls_back_to_semantic_search_when_exact_misses():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        if where:
            return []
        return [_chunk()]

    strategy = HybridPlayerBioStrategy(retrieve_fn=fake_retrieve)

    result = strategy.retrieve(
        "who was Babe Ruth",
        top_k=3,
        persist_dir=Path("store"),
        player_name="Babe Ruth",
        player_id="ruthba01",
    )

    assert result
    assert calls == [
        {
            "query": "Babe Ruth",
            "top_k": 1,
            "persist_dir": Path("store"),
            "where": {"player_id": "ruthba01"},
        },
        {
            "query": "Babe Ruth",
            "top_k": 3,
            "persist_dir": Path("store"),
            "where": {"category": "player_biography"},
        },
        {
            "query": "Babe Ruth",
            "top_k": 3,
            "persist_dir": Path("store"),
            "where": None,
        },
    ]


def test_hybrid_player_bio_with_no_player_id_falls_back_explicitly_to_semantic_search():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        return [_chunk("Smith")]

    strategy = HybridPlayerBioStrategy(retrieve_fn=fake_retrieve)

    result = strategy.retrieve("who was Smith", top_k=3, player_name="Smith")

    assert result
    assert calls == [
        {
            "query": "Smith",
            "top_k": 3,
            "persist_dir": None,
            "where": {"category": "player_biography"},
        }
    ]


def test_semantic_chroma_falls_back_to_stat_definition_filter_when_broad_search_misses():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        if where == {"category": "stat_definition"}:
            return [_chunk("On-Base Plus Slugging (OPS)")]
        return []

    strategy = SemanticChromaStrategy(retrieve_fn=fake_retrieve)

    result = strategy.retrieve("what is OPS", top_k=3, persist_dir=Path("store"))

    assert result
    assert calls == [
        {
            "query": "what is OPS",
            "top_k": 3,
            "persist_dir": Path("store"),
            "where": None,
        },
        {
            "query": "what is OPS",
            "top_k": 3,
            "persist_dir": Path("store"),
            "where": {"category": "stat_definition"},
        },
    ]


def test_get_strategy_rejects_unknown_strategy_name():
    try:
        get_strategy("unknown")
    except ValueError as exc:
        assert "unknown retrieval strategy" in str(exc)
    else:
        raise AssertionError("expected ValueError")
