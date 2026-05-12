"""FastAPI server for Baseball RAG."""

import logging
from dataclasses import asdict
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(title="Baseball RAG API")
logger = logging.getLogger(__name__)


class QueryRequest(BaseModel):
    question: str
    conversation: list[dict[str, Any]] | None = None


class QueryResponse(BaseModel):
    answer: str
    intent: str
    sources: list[dict[str, Any]]
    warnings: list[str]
    unsupported: bool
    unsupported_reason: str | None = None
    review_reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    review: dict[str, Any] | None = None


class EvalRunRequest(BaseModel):
    include_live: bool = False
    strategy: str | None = None
    all_strategies: bool = False
    retrieval_only: bool = False


class ReviewUpdateRequest(BaseModel):
    status: Literal["resolved", "dismissed"]
    note: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    from baseball_rag.request_execution import execute_request

    result = execute_request(
        req.question,
        adapter_component_id="api",
        adapter_label="FastAPI Query",
        conversation=req.conversation,
        attach_audit=True,
        attach_review=True,
        audit_logger=logger,
    ).answer
    return QueryResponse(**result.to_dict())


@app.get("/review-queue")
def review_queue(status: Literal["open", "resolved", "dismissed", "all"] = "open"):
    """Return latest local human-review queue snapshots."""
    from baseball_rag.review_queue import list_review_items

    items = list_review_items(status=status)
    return {"count": len(items), "items": [asdict(item) for item in items]}


@app.patch("/review-queue/{item_id}")
def update_review_queue_item(item_id: str, req: ReviewUpdateRequest):
    """Resolve or dismiss a local human-review queue item."""
    from baseball_rag.review_queue import resolve_review_item

    try:
        item = resolve_review_item(item_id, req.status, note=req.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": asdict(item)}


@app.get("/evals/report")
def evals_report(include_live: bool = False):
    """Return the deterministic eval report without writing files."""
    return _run_eval_payload(include_live=include_live)


@app.post("/evals/run")
def evals_run(req: EvalRunRequest):
    """Run evals with explicit options, deterministic-only by default."""
    live_options = req.strategy or req.all_strategies or req.retrieval_only
    if live_options and not req.include_live:
        raise HTTPException(
            status_code=400,
            detail=(
                "Retrieval strategy and retrieval-only eval options may require Chroma or "
                "LM Studio; set include_live=true to run them."
            ),
        )
    if req.strategy or req.all_strategies or req.retrieval_only:
        raise HTTPException(
            status_code=400,
            detail="Live strategy evals are supported by the CLI, not this deterministic API.",
        )
    payload = _run_eval_payload(include_live=req.include_live)
    payload["options"] = req.model_dump()
    if req.include_live:
        payload.setdefault("warnings", []).append(
            "include_live=true may require Chroma, corpus, and LM Studio services."
        )
    return payload


@app.get("/guardrails/coverage")
def guardrails_coverage():
    """Return manifest-only guardrail coverage."""
    from evals.questions import guardrail_coverage_payload, load_cases

    return guardrail_coverage_payload(load_cases())


def _run_eval_payload(*, include_live: bool) -> dict[str, Any]:
    from evals.questions import (
        EvalReport,
        build_eval_artifact,
        format_eval_report,
        load_cases,
        run_cases,
    )

    cases = load_cases()
    result = run_cases(cases, include_live=include_live)
    report = EvalReport(
        command="api:/evals/report",
        cases=cases,
        include_live=include_live,
        result=result,
        mode="answer",
    )
    artifact = build_eval_artifact(report)
    return {
        "ok": artifact["summary"]["recommendation"] != "BLOCK",
        "mode": artifact["mode"],
        "include_live": include_live,
        "minimum_pass_rate": artifact["minimum_pass_rate"],
        "summary": artifact["summary"],
        "results": {
            "passed": [case for case in artifact["cases"] if case["status"] == "passed"],
            "failed": [case for case in artifact["cases"] if case["status"] == "failed"],
            "skipped": [case for case in artifact["cases"] if case["status"] == "skipped"],
        },
        "failed": [case for case in artifact["cases"] if case["status"] == "failed"],
        "skipped": [case for case in artifact["cases"] if case["status"] == "skipped"],
        "markdown": format_eval_report(report),
        "warnings": [],
    }


@app.get("/sources")
def sources():
    """Return dataset provenance used by DuckDB-backed answers."""
    from baseball_rag.provenance import load_data_manifest

    return load_data_manifest()
