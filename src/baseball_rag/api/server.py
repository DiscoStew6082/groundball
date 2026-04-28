"""FastAPI server for Baseball RAG."""

import logging
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Baseball RAG API")
logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    answer: str
    intent: str
    sources: list[dict[str, Any]]
    warnings: list[str]
    unsupported: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    from baseball_rag.arch.tracing import finish_trace, start_trace
    from baseball_rag.service import answer

    start_trace(req.question)
    result = answer(req.question)
    trace = finish_trace(route_type=result.intent)
    result.metadata.update(_query_metadata(result.to_dict(), trace=trace))
    _attach_review(req.question, result)
    logger.info("query_audit", extra={"audit": result.metadata})
    return QueryResponse(**result.to_dict())


def _attach_review(question: str, result: Any) -> None:
    from baseball_rag.review_queue import build_review_item, review_payload

    result.review = review_payload(build_review_item(question, result))


def _query_metadata(payload: dict[str, Any], *, trace: Any) -> dict[str, Any]:
    sources = payload.get("sources", [])
    source_types = [source.get("type") for source in sources if source.get("type")]
    sql_visible = any(bool(source.get("sql")) for source in sources)
    trace_payload = _trace_to_dict(trace)
    return {
        "route": payload.get("intent"),
        "unsupported": bool(payload.get("unsupported")),
        "warning_count": len(payload.get("warnings", [])),
        "source_count": len(sources),
        "source_types": source_types,
        "source_labels": [source.get("label") for source in sources if source.get("label")],
        "sql_visible": sql_visible,
        "latency_ms": trace_payload["total_ms"],
        "trace": trace_payload,
    }


def _trace_to_dict(trace: Any) -> dict[str, Any]:
    if trace is None:
        return {"route_type": "", "total_ms": 0.0, "stages": []}
    return {
        "route_type": trace.route_type,
        "total_ms": trace.total_ms,
        "stages": [
            {
                "component_id": stage.component_id,
                "label": stage.label,
                "elapsed_ms": stage.elapsed_ms,
                "output_summary": stage.output_summary,
                "error": stage.error,
            }
            for stage in trace.stages
        ],
    }


@app.get("/sources")
def sources():
    """Return dataset provenance used by DuckDB-backed answers."""
    from baseball_rag.provenance import load_data_manifest

    return load_data_manifest()
