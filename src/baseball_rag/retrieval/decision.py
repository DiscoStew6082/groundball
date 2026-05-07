"""Routed retrieval decisions for grounded answer generation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from baseball_rag.retrieval.chroma_store import RetrievedChunk, get_chunks_by_ids, retrieve
from baseball_rag.retrieval.static_vocab import (
    query_asks_for_explanation,
    query_mentions_stat_definition,
    stat_definition_doc_ids_for_query,
)
from baseball_rag.retrieval.strategies import RetrievalStrategy, get_strategy


@dataclass(frozen=True)
class RetrievalRequest:
    """A routed request for grounded corpus chunks."""

    question: str
    intent: str
    top_k: int = 3
    persist_dir: Path | None = None
    player_name: str | None = None
    player_id: str | None = None
    retrieval_strategy: str | RetrievalStrategy | None = None


def retrieve_grounded_chunks(request: RetrievalRequest) -> list[RetrievedChunk]:
    """Retrieve grounded chunks for one routed case."""
    if request.intent == "player_biography":
        strategy = _resolve_retrieval_strategy(
            request.retrieval_strategy,
            default="hybrid_player_bio",
        )
        return strategy.retrieve(
            request.question,
            top_k=request.top_k,
            persist_dir=request.persist_dir,
            player_name=request.player_name,
            player_id=request.player_id,
        )

    strategy = _resolve_retrieval_strategy(
        request.retrieval_strategy,
        default="semantic_chroma",
    )
    chunks = _exact_static_explanation_chunks(request)
    if chunks:
        return chunks
    chunks = strategy.retrieve(
        request.question,
        top_k=request.top_k,
        persist_dir=request.persist_dir,
        player_name=request.player_name,
        player_id=request.player_id,
    )
    if chunks:
        return chunks
    return _fallback_filtered_chunks(request)


def _resolve_retrieval_strategy(
    strategy: str | RetrievalStrategy | None,
    *,
    default: str,
) -> RetrievalStrategy:
    if strategy is None:
        return get_strategy(default, retrieve_fn=retrieve)
    if isinstance(strategy, str):
        return get_strategy(strategy, retrieve_fn=retrieve)
    return strategy


def _exact_static_explanation_chunks(request: RetrievalRequest) -> list[RetrievedChunk]:
    if not query_asks_for_explanation(request.question):
        return []

    doc_ids = stat_definition_doc_ids_for_query(request.question)
    if not doc_ids:
        return []
    return get_chunks_by_ids(doc_ids, persist_dir=request.persist_dir)


def _fallback_filtered_chunks(request: RetrievalRequest) -> list[RetrievedChunk]:
    for where in _fallback_filters_for_query(request.question):
        chunks = retrieve(
            request.question,
            top_k=request.top_k,
            persist_dir=request.persist_dir,
            where=where,
        )
        if chunks:
            return chunks
    return []


def _fallback_filters_for_query(query: str) -> list[dict[str, str]]:
    filters: list[dict[str, str]] = []
    if query_mentions_stat_definition(query):
        filters.append({"category": "stat_definition"})
    filters.append({"category": "hof_bio"})
    return filters
