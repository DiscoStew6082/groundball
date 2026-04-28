"""Persistent vector store backed by ChromaDB."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import chromadb
import numpy as np

from baseball_rag import embedder as _embedder
from baseball_rag.arch.tracing import traced

COLLECTION_NAME = "baseball_corpus"
RELEVANCE_THRESHOLD = 0.7


@chromadb.api.collection_configuration.register_embedding_function
class LMStudioEmbeddingFunction(chromadb.EmbeddingFunction[chromadb.Documents]):
    def __init__(self) -> None:
        pass  # uses module-level defaults / env vars

    def __call__(self, input: chromadb.Documents) -> list[np.ndarray]:
        # ChromaDB protocol accepts str | list[str] | pre-computed embeddings.
        # We only support str | list[str]; the embedder returns vector floats.
        return [np.array(_embedder.embed(text)) for text in input]

    @staticmethod
    def name() -> str:
        return "lmstudio"

    @staticmethod
    def build_from_config(config: dict) -> "LMStudioEmbeddingFunction":
        return LMStudioEmbeddingFunction()

    def get_config(self) -> dict[str, object]:
        return {}


@dataclass
class RetrievedChunk:
    """A single retrieved document chunk."""

    text: str
    source: str
    title: str
    score: float
    id: str | None = None
    category: str | None = None
    player_id: str | None = None
    doc_kind: str | None = None


def _resolve_persist_dir(persist_dir: Path | None) -> Path:
    """Resolve the persist directory, checking CHROMA_PERSIST_DIR env var first."""
    if persist_dir is not None:
        return persist_dir
    import os

    env_path = os.environ.get("CHROMA_PERSIST_DIR")
    if env_path:
        return Path(env_path)
    from baseball_rag.db.duckdb_schema import DATA_DIR

    return DATA_DIR


@lru_cache(maxsize=1)
def _cached_collection(persist_dir: str) -> chromadb.Collection:
    """Cached collection — keyed by path string to prevent duplicate clients."""
    client = chromadb.PersistentClient(path=persist_dir)
    return client.get_or_create_collection(
        name=COLLECTION_NAME,
        embedding_function=LMStudioEmbeddingFunction(),  # type: ignore[arg-type]
    )


def get_store(persist_dir: Path) -> chromadb.Collection:
    """Open or create the baseball corpus collection.

    Returns a cached singleton per path to avoid ChromaDB creating multiple
    clients for the same location (which causes empty ephemeral collections).
    """
    return _cached_collection(str(persist_dir.resolve()))


def _retrieve_impl(
    query: str,
    top_k: int = 3,
    persist_dir: Path | None = None,
    where: dict | None = None,
) -> list[RetrievedChunk]:
    """Core retrieval implementation — no tracing overhead."""
    if persist_dir is None:
        persist_dir = _resolve_persist_dir(None)

    collection = get_store(persist_dir)

    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where=where,
        include=["documents", "metadatas", "distances"],
    )

    chunks = []
    if not results["ids"]:
        return []
    # ChromaDB type stubs over-approximate None; we already verified ids is non-empty above
    for i in range(len(results["ids"][0])):
        doc = results["documents"][0][i]  # type: ignore[index]
        meta = results["metadatas"][0][i]  # type: ignore[index]
        dist = results["distances"][0][i]  # type: ignore[index]
        # ChromaDB L2 distance — lower is better; convert to a 0-1 "score"
        score = max(0.0, 1.0 - dist / 2.0)
        chunks.append(
            RetrievedChunk(
                text=doc,
                source=str(meta.get("source", "")),
                title=str(meta.get("title", "")),
                score=score,
                id=str(results["ids"][0][i]),
                category=str(meta.get("category", "")) or None,
                player_id=str(meta.get("player_id", "")) or None,
                doc_kind=str(meta.get("doc_kind", "")) or None,
            )
        )

    # Reject low-scoring retrievals — scores ~0.49 in high-dimensional space are
    # essentially random; fall back to LLM without retrieved context instead.
    if chunks and where is None and chunks[0].score < RELEVANCE_THRESHOLD:
        return []

    return chunks


def get_chunks_by_ids(
    ids: list[str],
    *,
    persist_dir: Path | None = None,
) -> list[RetrievedChunk]:
    """Fetch known corpus documents by Chroma ID without semantic search."""
    if persist_dir is None:
        persist_dir = _resolve_persist_dir(None)

    collection = get_store(persist_dir)
    results = collection.get(ids=ids, include=["documents", "metadatas"])
    chunks: list[RetrievedChunk] = []
    for index, doc_id in enumerate(results.get("ids", [])):
        documents = results.get("documents") or []
        metadatas = results.get("metadatas") or []
        doc = documents[index] if index < len(documents) else ""
        meta = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
        chunks.append(
            RetrievedChunk(
                text=str(doc),
                source=str(meta.get("source", "")),
                title=str(meta.get("title", "")),
                score=1.0,
                id=str(doc_id),
                category=str(meta.get("category", "")) or None,
                player_id=str(meta.get("player_id", "")) or None,
                doc_kind=str(meta.get("doc_kind", "")) or None,
            )
        )
    return chunks


@traced(component_id="chroma-store", label="Vector Retrieval")
def retrieve(
    query: str,
    top_k: int = 3,
    persist_dir: Path | None = None,
    where: dict | None = None,
) -> list[RetrievedChunk]:
    """Embed query and retrieve top-K relevant chunks.

    Args:
        query: Natural language search query
        top_k: Number of results to return
        persist_dir: Where the ChromaDB is stored. Defaults to data/chroma_db/.

    Returns:
        List of RetrievedChunk objects sorted by relevance (best first).
    """
    return _retrieve_impl(query, top_k=top_k, persist_dir=persist_dir, where=where)


def corpus_diagnostics(persist_dir: Path | None = None) -> dict:
    """Return a dict describing what's available in the corpus and data layer."""
    from baseball_rag.corpus.diagnostics import corpus_diagnostics as _corpus_diagnostics

    return _corpus_diagnostics(persist_dir)
