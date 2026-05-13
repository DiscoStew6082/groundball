"""Tests for retrieval strategy selection and call behavior."""

from pathlib import Path
from unittest.mock import patch

from baseball_rag.corpus.lifecycle import (
    HOF_BIO_CATEGORY,
    PLAYER_BIOGRAPHY_CATEGORY,
    STAT_DEFINITION_CATEGORY,
    category_filter,
    player_id_filter,
)
from baseball_rag.retrieval.chroma_store import RetrievedChunk
from baseball_rag.retrieval.decision import RetrievalRequest, retrieve_grounded_chunks
from baseball_rag.retrieval.strategies import (
    ExactPlayerIdStrategy,
    HybridPlayerBioStrategy,
    SemanticChromaStrategy,
    available_strategy_metadata,
    available_strategy_names,
    get_strategy,
)
from baseball_rag.routing.query_router import GeneralExplanationCase, PlayerBiographyCase


def _chunk(title: str = "Babe Ruth") -> RetrievedChunk:
    return RetrievedChunk(text=f"{title} profile", source="test.md", title=title, score=0.95)


def test_available_strategy_names_includes_initial_benchmarks():
    assert available_strategy_names() == [
        "semantic_chroma",
        "exact_player_id",
        "hybrid_player_bio",
    ]


def test_strategy_metadata_declares_applicability_categories():
    metadata_items = available_strategy_metadata()
    assert [item.name for item in metadata_items] == available_strategy_names()
    metadata = {item.name: item for item in metadata_items}

    assert metadata["semantic_chroma"].categories == frozenset(
        {"player_biography", "general_explanation"}
    )
    assert metadata["exact_player_id"].categories == frozenset({"player_biography"})
    assert metadata["exact_player_id"].requires_player_id is True
    assert metadata["hybrid_player_bio"].categories == frozenset({"player_biography"})


def test_strategy_metadata_descriptions_are_stable_for_eval_reporting():
    metadata = {item.name: item for item in available_strategy_metadata()}

    assert metadata["semantic_chroma"].description == "Unfiltered semantic Chroma retrieval."
    assert (
        metadata["exact_player_id"].description
        == "Chroma retrieval filtered to a resolved player_id."
    )
    assert (
        metadata["hybrid_player_bio"].description
        == "Exact player_id lookup with semantic biography fallback."
    )


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
            "where": player_id_filter("ruthba01"),
        }
    ]


def test_hybrid_player_bio_does_not_fallback_when_resolved_player_id_misses():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        return []

    strategy = HybridPlayerBioStrategy(retrieve_fn=fake_retrieve)

    result = strategy.retrieve(
        "who was Babe Ruth",
        top_k=3,
        persist_dir=Path("store"),
        player_name="Babe Ruth",
        player_id="ruthba01",
    )

    assert result == []
    assert calls == [
        {
            "query": "Babe Ruth",
            "top_k": 1,
            "persist_dir": Path("store"),
            "where": player_id_filter("ruthba01"),
        }
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
            "where": category_filter(PLAYER_BIOGRAPHY_CATEGORY),
        }
    ]


def test_retrieval_request_can_be_built_from_routed_case():
    request = RetrievalRequest.from_routed_case(
        PlayerBiographyCase(player_name="Babe Ruth", raw_question="who was Babe Ruth"),
        player_id="ruthba01",
        retrieval_strategy="exact_player_id",
    )

    assert request.question == "who was Babe Ruth"
    assert request.intent == "player_biography"
    assert request.player_name == "Babe Ruth"
    assert request.player_id == "ruthba01"
    assert request.top_k == 3
    assert request.retrieval_strategy == "exact_player_id"


def test_retrieval_request_uses_query_when_routed_case_has_no_raw_question():
    request = RetrievalRequest.from_routed_case(
        GeneralExplanationCase(),
        question="what is OPS",
    )

    assert request.question == "what is OPS"
    assert request.intent == "general_explanation"


def test_semantic_chroma_does_not_own_filtered_fallback_policy():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        return []

    strategy = SemanticChromaStrategy(retrieve_fn=fake_retrieve)

    result = strategy.retrieve("what is OPS", top_k=3, persist_dir=Path("store"))

    assert result == []
    assert calls == [
        {
            "query": "what is OPS",
            "top_k": 3,
            "persist_dir": Path("store"),
            "where": None,
        }
    ]


def test_get_strategy_rejects_unknown_strategy_name():
    try:
        get_strategy("unknown")
    except ValueError as exc:
        assert "unknown retrieval strategy" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_retrieval_decision_uses_player_id_strategy_before_semantic_fallback():
    calls: list[dict] = []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        calls.append({"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where})
        if where == player_id_filter("ruthba01"):
            return [_chunk("Babe Ruth")]
        return []

    result = retrieve_grounded_chunks(
        RetrievalRequest(
            question="who was Babe Ruth",
            intent="player_biography",
            player_name="Babe Ruth",
            player_id="ruthba01",
            retrieval_strategy=HybridPlayerBioStrategy(retrieve_fn=fake_retrieve),
        )
    )

    assert result
    assert calls == [
        {
            "query": "Babe Ruth",
            "top_k": 1,
            "persist_dir": None,
            "where": player_id_filter("ruthba01"),
        }
    ]


def test_retrieval_decision_uses_exact_static_stat_definition_before_chroma_search():
    searched = False

    def fake_strategy_search(*_args, **_kwargs):
        nonlocal searched
        searched = True
        return []

    with patch("baseball_rag.retrieval.decision.get_chunks_by_ids") as get_by_ids:
        get_by_ids.return_value = [_chunk("OPS")]
        chunks = retrieve_grounded_chunks(
            RetrievalRequest(
                question="what is OPS",
                intent="general_explanation",
                retrieval_strategy=SemanticChromaStrategy(retrieve_fn=fake_strategy_search),
            )
        )

    assert chunks[0].title == "OPS"
    get_by_ids.assert_called_once_with(["OPS"], persist_dir=None)
    assert searched is False


def test_retrieval_decision_owns_filtered_stat_definition_fallback_when_exact_misses():
    semantic_calls: list[dict] = []
    fallback_calls: list[dict] = []

    def fake_strategy_search(query, *, top_k=3, persist_dir=None, where=None):
        semantic_calls.append(
            {"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where}
        )
        return []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        fallback_calls.append(
            {"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where}
        )
        if where == category_filter(STAT_DEFINITION_CATEGORY):
            return [_chunk("OPS")]
        return []

    with (
        patch("baseball_rag.retrieval.decision.get_chunks_by_ids", return_value=[]),
        patch("baseball_rag.retrieval.decision.retrieve", side_effect=fake_retrieve),
    ):
        chunks = retrieve_grounded_chunks(
            RetrievalRequest(
                question="what is OPS",
                intent="general_explanation",
                retrieval_strategy=SemanticChromaStrategy(retrieve_fn=fake_strategy_search),
            )
        )

    assert chunks[0].title == "OPS"
    assert semantic_calls == [
        {"query": "what is OPS", "top_k": 3, "persist_dir": None, "where": None}
    ]
    assert fallback_calls == [
        {
            "query": "what is OPS",
            "top_k": 3,
            "persist_dir": None,
            "where": category_filter(STAT_DEFINITION_CATEGORY),
        }
    ]


def test_retrieval_decision_falls_back_to_hof_bio_category_for_general_explanations():
    fallback_calls: list[dict] = []

    def fake_strategy_search(*_args, **_kwargs):
        return []

    def fake_retrieve(query, *, top_k=3, persist_dir=None, where=None):
        fallback_calls.append(
            {"query": query, "top_k": top_k, "persist_dir": persist_dir, "where": where}
        )
        if where == category_filter(HOF_BIO_CATEGORY):
            return [_chunk("Babe Ruth")]
        return []

    with patch("baseball_rag.retrieval.decision.retrieve", side_effect=fake_retrieve):
        chunks = retrieve_grounded_chunks(
            RetrievalRequest(
                question="tell me about great early sluggers",
                intent="general_explanation",
                retrieval_strategy=SemanticChromaStrategy(retrieve_fn=fake_strategy_search),
            )
        )

    assert chunks[0].title == "Babe Ruth"
    assert fallback_calls == [
        {
            "query": "tell me about great early sluggers",
            "top_k": 3,
            "persist_dir": None,
            "where": category_filter(HOF_BIO_CATEGORY),
        }
    ]
