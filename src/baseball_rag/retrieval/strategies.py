"""Retrieval strategy objects for benchmarkable search tactics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from baseball_rag.retrieval.chroma_store import RetrievedChunk, get_chunks_by_ids, retrieve

RetrieveFn = Callable[..., list[RetrievedChunk]]


@dataclass(frozen=True)
class StrategyMetadata:
    """Static reporting and applicability metadata for a retrieval strategy."""

    name: str
    description: str
    categories: frozenset[str]
    requires_player_id: bool = False


class RetrievalStrategy(Protocol):
    """A benchmarkable retrieval tactic."""

    @property
    def name(self) -> str:
        """Stable strategy name for reporting."""
        ...

    @property
    def metadata(self) -> StrategyMetadata:
        """Static strategy metadata used by eval reporting."""
        ...

    def is_applicable(
        self,
        *,
        category: str,
        player_id: str | None = None,
    ) -> bool:
        """Return whether this strategy should be attempted for the routed case."""
        ...

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 3,
        persist_dir: Path | None = None,
        player_name: str | None = None,
        player_id: str | None = None,
    ) -> list[RetrievedChunk]:
        """Retrieve relevant chunks for a routed query."""


@dataclass(frozen=True)
class SemanticChromaStrategy:
    """Current vector search only."""

    retrieve_fn: RetrieveFn = retrieve
    name: str = "semantic_chroma"

    @property
    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            name=self.name,
            description="Unfiltered semantic Chroma retrieval.",
            categories=frozenset({"player_biography", "general_explanation"}),
        )

    def is_applicable(
        self,
        *,
        category: str,
        player_id: str | None = None,
    ) -> bool:
        return _is_applicable(self.metadata, category=category, player_id=player_id)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 3,
        persist_dir: Path | None = None,
        player_name: str | None = None,
        player_id: str | None = None,
    ) -> list[RetrievedChunk]:
        search_query = player_name or query
        chunks = _call_retrieve(
            self.retrieve_fn,
            search_query,
            top_k=top_k,
            persist_dir=persist_dir,
            where=None,
        )
        if chunks:
            return chunks

        exact_static = _static_doc_ids_for_query(search_query)
        if exact_static and self.retrieve_fn is retrieve:
            static_chunks = get_chunks_by_ids(exact_static, persist_dir=persist_dir)
            if static_chunks:
                return static_chunks

        for where in _fallback_filters_for_query(search_query):
            chunks = _call_retrieve(
                self.retrieve_fn,
                search_query,
                top_k=top_k,
                persist_dir=persist_dir,
                where=where,
            )
            if chunks:
                return chunks
        return []


@dataclass(frozen=True)
class ExactPlayerIdStrategy:
    """Resolve a player ID first, then use a Chroma metadata filter."""

    retrieve_fn: RetrieveFn = retrieve
    name: str = "exact_player_id"

    @property
    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            name=self.name,
            description="Chroma retrieval filtered to a resolved player_id.",
            categories=frozenset({"player_biography"}),
            requires_player_id=True,
        )

    def is_applicable(
        self,
        *,
        category: str,
        player_id: str | None = None,
    ) -> bool:
        return _is_applicable(self.metadata, category=category, player_id=player_id)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 3,
        persist_dir: Path | None = None,
        player_name: str | None = None,
        player_id: str | None = None,
    ) -> list[RetrievedChunk]:
        if not player_id:
            return []
        search_query = player_name or query
        return _call_retrieve(
            self.retrieve_fn,
            search_query,
            top_k=1,
            persist_dir=persist_dir,
            where={"player_id": player_id},
        )


@dataclass(frozen=True)
class HybridPlayerBioStrategy:
    """Exact player metadata lookup first, semantic player search fallback."""

    retrieve_fn: RetrieveFn = retrieve
    name: str = "hybrid_player_bio"

    @property
    def metadata(self) -> StrategyMetadata:
        return StrategyMetadata(
            name=self.name,
            description="Exact player_id lookup with semantic biography fallback.",
            categories=frozenset({"player_biography"}),
        )

    def is_applicable(
        self,
        *,
        category: str,
        player_id: str | None = None,
    ) -> bool:
        return _is_applicable(self.metadata, category=category, player_id=player_id)

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 3,
        persist_dir: Path | None = None,
        player_name: str | None = None,
        player_id: str | None = None,
    ) -> list[RetrievedChunk]:
        exact = ExactPlayerIdStrategy(retrieve_fn=self.retrieve_fn).retrieve(
            query,
            top_k=top_k,
            persist_dir=persist_dir,
            player_name=player_name,
            player_id=player_id,
        )
        if exact:
            return exact
        search_query = player_name or query
        player_chunks = _call_retrieve(
            self.retrieve_fn,
            search_query,
            top_k=top_k,
            persist_dir=persist_dir,
            where={"category": "player_biography"},
        )
        if player_chunks:
            return player_chunks
        return SemanticChromaStrategy(retrieve_fn=self.retrieve_fn).retrieve(
            query,
            top_k=top_k,
            persist_dir=persist_dir,
            player_name=player_name,
            player_id=player_id,
        )


def available_strategy_names() -> list[str]:
    """Return strategy names in stable benchmark display order."""
    return ["semantic_chroma", "exact_player_id", "hybrid_player_bio"]


def available_strategy_metadata() -> list[StrategyMetadata]:
    """Return metadata for all built-in strategies in display order."""
    return [get_strategy(name).metadata for name in available_strategy_names()]


def get_strategy(name: str, *, retrieve_fn: RetrieveFn = retrieve) -> RetrievalStrategy:
    """Build a retrieval strategy by name."""
    if name == "semantic_chroma":
        return SemanticChromaStrategy(retrieve_fn=retrieve_fn)
    if name == "exact_player_id":
        return ExactPlayerIdStrategy(retrieve_fn=retrieve_fn)
    if name == "hybrid_player_bio":
        return HybridPlayerBioStrategy(retrieve_fn=retrieve_fn)
    choices = ", ".join(available_strategy_names())
    raise ValueError(f"unknown retrieval strategy {name!r}; choose one of: {choices}")


def _is_applicable(
    metadata: StrategyMetadata,
    *,
    category: str,
    player_id: str | None,
) -> bool:
    if category not in metadata.categories:
        return False
    if metadata.requires_player_id and not player_id:
        return False
    return True


def _call_retrieve(
    retrieve_fn: RetrieveFn,
    query: str,
    *,
    top_k: int,
    persist_dir: Path | None,
    where: dict | None,
) -> list[RetrievedChunk]:
    if persist_dir is None:
        return retrieve_fn(query, top_k=top_k, where=where)
    return retrieve_fn(query, top_k=top_k, persist_dir=persist_dir, where=where)


_STATIC_STAT_DOC_IDS = {
    "2b": "2B",
    "avg": "AVG",
    "batting average": "AVG",
    "bb": "BB",
    "base on balls": "BB",
    "era": "ERA",
    "earned run average": "ERA",
    "hr": "HR",
    "home run": "HR",
    "home runs": "HR",
    "ops": "OPS",
    "on-base plus slugging": "OPS",
    "po": "PO",
    "putout": "PO",
    "putouts": "PO",
    "rbi": "RBI",
    "run batted in": "RBI",
    "runs batted in": "RBI",
    "sb": "SB",
    "stolen base": "SB",
    "stolen bases": "SB",
    "whip": "WHIP",
}

_STATIC_HOF_DOC_IDS = {
    "babe ruth": "Babe_Ruth",
    "hank aaron": "Hank_Aaron",
    "mickey mantle": "Mickey_Mantle",
    "ted williams": "Ted_Williams",
    "willie mays": "Willie_Mays",
}


def _static_doc_ids_for_query(query: str) -> list[str]:
    lower_query = query.lower()
    ids: list[str] = []
    for phrase, doc_id in {**_STATIC_STAT_DOC_IDS, **_STATIC_HOF_DOC_IDS}.items():
        if phrase in lower_query and doc_id not in ids:
            ids.append(doc_id)
    return ids


def _fallback_filters_for_query(query: str) -> list[dict]:
    lower_query = query.lower()
    filters: list[dict] = []
    if any(phrase in lower_query for phrase in _STATIC_STAT_DOC_IDS):
        filters.append({"category": "stat_definition"})
    filters.append({"category": "hof_bio"})
    return filters
