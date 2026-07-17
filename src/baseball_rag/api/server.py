"""FastAPI server for Groundball."""

import hmac
import logging
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse, Response

from baseball_rag.answer_mode import AnswerMode

app = FastAPI(title="Groundball API")
logger = logging.getLogger(__name__)
_CORS_ORIGINS_ENV_VAR = "GROUNDBALL_CORS_ORIGINS"
_ORIGIN_PROXY_TOKEN_ENV_VAR = "GROUNDBALL_ORIGIN_PROXY_TOKEN"
_ORIGIN_PROXY_TOKEN_HEADER = "x-groundball-proxy-token"
_PUBLIC_HEALTH_PATH = "/health"
_CORS_QUERY_PATHS = {"/query", "/api/query"}
_CORS_ALLOWED_METHOD = "POST"
_CORS_ALLOWED_HEADERS = ("content-type",)
_DEFAULT_CORS_ORIGINS = (
    "https://discostew.dev",
    "http://localhost:4321",
    "http://127.0.0.1:4321",
)
_REPOSITORY_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
_PACKAGE_WEB_DIST = Path(__file__).resolve().parents[1] / "web_dist"


def _public_demo_enabled() -> bool:
    return os.environ.get("GROUNDBALL_PUBLIC_DEMO", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _local_feature_enabled(env_var: str) -> bool:
    if _public_demo_enabled():
        return False
    configured = os.environ.get(env_var)
    if configured is None:
        return True
    return configured.strip().lower() in {"1", "true", "yes", "on"}


def _architecture_enabled() -> bool:
    return _local_feature_enabled("GROUNDBALL_ARCHITECTURE_ENABLED")


def _developer_tools_enabled() -> bool:
    return _local_feature_enabled("GROUNDBALL_DEVELOPER_TOOLS_ENABLED")


def _cors_allowed_origins() -> list[str]:
    raw_origins = os.environ.get(_CORS_ORIGINS_ENV_VAR)
    if raw_origins is None:
        return list(_DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw_origins.split(",") if origin.strip()]


def _cors_origin_is_allowed(origin: str | None) -> bool:
    return bool(origin and origin in _cors_allowed_origins())


def _append_vary_origin(response: Response) -> None:
    vary = response.headers.get("vary")
    if vary is None:
        response.headers["vary"] = "Origin"
    elif "origin" not in {part.strip().lower() for part in vary.split(",")}:
        response.headers["vary"] = f"{vary}, Origin"


def _add_query_cors_headers(response: Response, origin: str) -> Response:
    response.headers["access-control-allow-origin"] = origin
    response.headers["access-control-allow-credentials"] = "true"
    _append_vary_origin(response)
    return response


def _preflight_headers(origin: str) -> dict[str, str]:
    return {
        "access-control-allow-origin": origin,
        "access-control-allow-credentials": "true",
        "access-control-allow-methods": _CORS_ALLOWED_METHOD,
        "access-control-allow-headers": ", ".join(_CORS_ALLOWED_HEADERS),
        "access-control-max-age": "600",
        "vary": "Origin, Access-Control-Request-Method, Access-Control-Request-Headers",
    }


def _requested_headers_are_allowed(raw_headers: str) -> bool:
    if not raw_headers:
        return True
    allowed_headers = set(_CORS_ALLOWED_HEADERS)
    requested_headers = {header.strip().lower() for header in raw_headers.split(",")}
    return requested_headers <= allowed_headers


def _origin_proxy_token_is_valid(request: Request, configured_token: str) -> bool:
    supplied_token = request.headers.get(_ORIGIN_PROXY_TOKEN_HEADER, "")
    return hmac.compare_digest(supplied_token, configured_token)


def _local_only_path(path: str) -> bool:
    return (
        path == "/review-queue"
        or path.startswith("/review-queue/")
        or path == "/evals/report"
        or path == "/evals/run"
        or path == "/api/architecture"
        or path.startswith("/api/architecture/")
        or path == "/api/developer/tests"
    )


@app.middleware("http")
async def _public_mode_route_guard(request: Request, call_next):
    if _public_demo_enabled() and _local_only_path(request.url.path):
        return JSONResponse({"detail": "Not found."}, status_code=404)
    return await call_next(request)


@app.middleware("http")
async def _origin_proxy_token_middleware(request: Request, call_next):
    configured_token = os.environ.get(_ORIGIN_PROXY_TOKEN_ENV_VAR)
    if not configured_token or request.url.path == _PUBLIC_HEALTH_PATH:
        return await call_next(request)

    if not _origin_proxy_token_is_valid(request, configured_token):
        return JSONResponse({"error": "groundball_origin_proxy_token_required"}, status_code=403)

    return await call_next(request)


@app.middleware("http")
async def _query_cors_middleware(request: Request, call_next):
    origin = request.headers.get("origin")
    is_preflight = (
        request.method == "OPTIONS" and "access-control-request-method" in request.headers
    )

    if is_preflight:
        requested_method = request.headers.get("access-control-request-method", "").upper()
        if (
            request.url.path not in _CORS_QUERY_PATHS
            or not _cors_origin_is_allowed(origin)
            or requested_method != _CORS_ALLOWED_METHOD
            or not _requested_headers_are_allowed(
                request.headers.get("access-control-request-headers", "")
            )
        ):
            return PlainTextResponse("Disallowed CORS request", status_code=400)
        return PlainTextResponse("OK", headers=_preflight_headers(origin or ""))

    response = await call_next(request)
    if (
        request.url.path in _CORS_QUERY_PATHS
        and request.method == _CORS_ALLOWED_METHOD
        and _cors_origin_is_allowed(origin)
    ):
        return _add_query_cors_headers(response, origin or "")
    return response


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)
    conversation: list[dict[str, Any]] | None = Field(default=None, max_length=20)
    answer_mode: AnswerMode = "stats_only"


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


class WebQueryResponse(QueryResponse):
    status: Literal["completed"]
    rows: Any
    sql: str
    conversation_turn: dict[str, Any]
    architecture_trace: dict[str, Any] | None


class EvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_live: bool = False


class ReviewUpdateRequest(BaseModel):
    status: Literal["resolved", "dismissed"]
    note: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/capabilities")
def capabilities():
    """Return the server-enforced feature set for the unified web app."""
    public_demo = _public_demo_enabled()
    return {
        "name": "Ground Ball",
        "mode": "public" if public_demo else "local",
        "query": True,
        "llm": not public_demo,
        "architecture": _architecture_enabled(),
        "developer_tools": _developer_tools_enabled(),
        "history": "browser_local",
    }


@app.get("/api/architecture")
def architecture_catalog():
    """Return the rendering-neutral architecture component catalog."""
    _require_local_capability(_architecture_enabled())

    from baseball_rag.arch.components import get_registry

    components = sorted(get_registry().all(), key=lambda component: component.id)
    return {"components": [component.to_catalog_dict() for component in components]}


@app.get("/api/architecture/{component_id}")
def architecture_component_detail(component_id: str):
    """Return source-backed component details only in the local runtime."""
    _require_local_capability(_architecture_enabled())

    from baseball_rag.arch.components import get_registry

    component = get_registry().get(component_id)
    if component is None:
        raise HTTPException(status_code=404, detail="Architecture component not found.")
    return {
        "component": component.to_detail_dict(),
        "source_excerpt": get_registry().get_source_snippet(component_id, n=10),
    }


def _require_local_mode() -> None:
    if _public_demo_enabled():
        raise HTTPException(status_code=404, detail="Not found.")


def _require_local_capability(enabled: bool) -> None:
    _require_local_mode()
    if not enabled:
        raise HTTPException(status_code=404, detail="Not found.")


@app.post("/api/developer/tests")
def developer_tests():
    """Run the fixed Architecture pytest command in the local runtime only."""
    _require_local_capability(_developer_tools_enabled())

    from baseball_rag.arch.components import get_registry
    from baseball_rag.arch.test_status import collect_and_apply_test_status

    result = collect_and_apply_test_status(get_registry())
    payload = asdict(result)
    payload["component_statuses"] = {
        component_id: status.value for component_id, status in result.component_statuses.items()
    }
    return payload


@app.get("/health/verification")
def verification_health():
    """Return operational readiness for deterministic verification surfaces."""
    from baseball_rag.verification_health import operational_verification_health

    return operational_verification_health()


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest):
    return QueryResponse(**_query_payload(req, adapter_component_id="api"))


@app.post("/api/query", response_model=WebQueryResponse)
def web_query(req: QueryRequest):
    """Answer one self-contained browser request with display and trace data."""
    return WebQueryResponse(**_query_payload(req, adapter_component_id="api-server"))


def _query_payload(req: QueryRequest, *, adapter_component_id: str) -> dict[str, Any]:
    from baseball_rag.audit import build_query_metadata, trace_to_dict
    from baseball_rag.request_execution import execute_public_demo_request, execute_request
    from baseball_rag.ui.presentation import AnswerPresenter

    if _public_demo_enabled():
        if req.answer_mode != "stats_only":
            raise HTTPException(
                status_code=422,
                detail="The public demo supports only answer_mode='stats_only'.",
            )
        execution = execute_public_demo_request(
            req.question,
            adapter_component_id=adapter_component_id,
            adapter_label="FastAPI Query",
            conversation=req.conversation,
        )
        execution.answer.metadata.update(
            build_query_metadata(req.question, execution.answer, trace=execution.trace)
        )
        execution.answer.metadata.pop("trace", None)
        logger.info("query_audit", extra={"audit": execution.answer.metadata})
    else:
        execution = execute_request(
            req.question,
            answer_mode=req.answer_mode,
            adapter_component_id=adapter_component_id,
            adapter_label="FastAPI Query",
            conversation=req.conversation,
            attach_audit=True,
            attach_review=True,
            audit_logger=logger,
        )

    presentation = AnswerPresenter().present(execution.answer)
    architecture_trace = (
        None if _public_demo_enabled() else trace_to_dict(getattr(execution, "trace", None))
    )
    return {
        **presentation.payload,
        "status": "completed",
        "rows": presentation.rows,
        "sources": presentation.sources,
        "sql": presentation.sql,
        "conversation_turn": presentation.conversation_turn(req.question),
        "architecture_trace": architecture_trace,
    }


@app.get("/review-queue")
def review_queue(status: Literal["open", "resolved", "dismissed", "all"] = "open"):
    """Return latest local human-review queue snapshots."""
    _require_local_mode()

    from baseball_rag.review_queue import list_review_items

    items = list_review_items(status=status)
    return {"count": len(items), "items": [asdict(item) for item in items]}


@app.patch("/review-queue/{item_id}")
def update_review_queue_item(item_id: str, req: ReviewUpdateRequest):
    """Resolve or dismiss a local human-review queue item."""
    _require_local_mode()

    from baseball_rag.review_queue import resolve_review_item

    try:
        item = resolve_review_item(item_id, req.status, note=req.note)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"item": asdict(item)}


@app.get("/evals/report")
def evals_report(include_live: bool = False):
    """Return the deterministic eval report without writing files."""
    _require_local_mode()
    return _run_eval_payload(include_live=include_live)


@app.post("/evals/run")
def evals_run(req: EvalRunRequest):
    """Run evals with explicit options, deterministic-only by default."""
    _require_local_mode()
    payload = _run_eval_payload(include_live=req.include_live)
    payload["options"] = req.model_dump()
    if req.include_live:
        payload.setdefault("warnings", []).append("include_live=true may require LM Studio.")
    return payload


@app.get("/guardrails/coverage")
def guardrails_coverage():
    """Return manifest-only guardrail coverage."""
    from baseball_rag.eval_manifest import default_guardrail_coverage_payload

    return default_guardrail_coverage_payload()


def _run_eval_payload(*, include_live: bool) -> dict[str, Any]:
    from evals.questions import (
        EvalReport,
        build_eval_report_payload,
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
    payload = build_eval_report_payload(report)
    payload["markdown"] = format_eval_report(report)
    return payload


@app.get("/sources")
def sources():
    """Return dataset provenance used by DuckDB-backed answers."""
    from baseball_rag.provenance import load_data_manifest

    return load_data_manifest()


def _web_dist_path() -> Path:
    configured = os.environ.get("GROUNDBALL_WEB_DIST")
    if configured:
        return Path(configured)
    if (_REPOSITORY_WEB_DIST / "index.html").is_file():
        return _REPOSITORY_WEB_DIST
    return _PACKAGE_WEB_DIST


@app.get("/{full_path:path}")
def web_shell(full_path: str):
    """Serve built Svelte assets with an index fallback for browser routes."""
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found.")

    web_dist = _web_dist_path()
    index_path = web_dist / "index.html"
    if not web_dist.is_dir() or not index_path.is_file():
        return JSONResponse(
            {
                "error": "groundball_web_assets_unavailable",
                "detail": "Build the Ground Ball web assets before starting the server.",
            },
            status_code=503,
        )

    resolved_dist = web_dist.resolve()
    requested_file = (web_dist / full_path).resolve()
    if requested_file.is_relative_to(resolved_dist) and requested_file.is_file():
        return FileResponse(requested_file)
    return FileResponse(index_path)
