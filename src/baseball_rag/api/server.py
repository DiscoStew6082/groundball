"""FastAPI server for Groundball."""

import hmac
import html
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)

app = FastAPI(title="Groundball API")
_CORS_ORIGINS_ENV_VAR = "GROUNDBALL_CORS_ORIGINS"
_ORIGIN_PROXY_TOKEN_ENV_VAR = "GROUNDBALL_ORIGIN_PROXY_TOKEN"
_ORIGIN_PROXY_TOKEN_HEADER = "x-groundball-proxy-token"
_PUBLIC_HEALTH_PATH = "/health"
_CORS_QUERY_PATHS = {"/api/query-runs"}
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


class QueryInputRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str | None = Field(default=None, min_length=1, max_length=500)
    recipe: dict[str, Any] | None = None


class RetrosheetQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=500)


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
        "query": {
            "endpoint": "/api/query-runs",
            "catalog_endpoint": "/api/query-catalog",
            "coverage_endpoint": "/api/query-coverage",
            "coverage_report": "/coverage-report",
            "natural_language": True,
            "structured_recipe": True,
        },
        "retrosheet_endpoint": "/api/retrosheet/queries",
        "llm_required": False,
        "history": "browser_local",
    }


@app.post("/api/query-runs")
def query_run(req: QueryInputRequest):
    """Plan and execute one natural-language or structured Query Recipe input."""
    from baseball_rag.query.adapters import run_query_input

    if (req.question is None) == (req.recipe is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one natural-language question or structured recipe.",
        )
    try:
        return run_query_input(question=req.question, recipe=req.recipe)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/query-catalog")
def query_catalog(
    source: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int | None = None,
):
    """Return rendering-neutral source, raw-field, and promoted-value discovery."""
    from baseball_rag.query.adapters import catalog_payload

    try:
        return catalog_payload(source=source, search=search, offset=offset, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/query-coverage")
def query_coverage():
    """Return the canonical machine-readable Coverage Report."""
    from baseball_rag.query.coverage import (
        CoverageProofUnavailableError,
        load_passing_coverage_report,
    )

    try:
        return load_passing_coverage_report()
    except CoverageProofUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/coverage-report", response_class=HTMLResponse)
def coverage_report():
    """Render the human report from the canonical machine read model."""
    from baseball_rag.query.coverage import (
        CoverageProofUnavailableError,
        load_passing_coverage_report,
        render_coverage_markdown,
    )

    try:
        report = load_passing_coverage_report()
    except CoverageProofUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    readable = html.escape(render_coverage_markdown(report))
    return HTMLResponse(
        "<!doctype html><html lang='en'><meta name='viewport' "
        "content='width=device-width,initial-scale=1'><title>Ground Ball Coverage</title>"
        "<style>html{color-scheme:dark;background:#10100f;color:#f5f1e8;font:16px/1.5 "
        "ui-monospace,monospace}body{margin:0 auto;max-width:900px;padding:clamp(20px,5vw,64px)}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}a{color:#f4d21f}</style>"
        f"<body><pre>{readable}</pre></body></html>"
    )


@app.post("/api/retrosheet/queries")
def retrosheet_query(req: RetrosheetQueryRequest):
    """Execute only the separately governed deterministic Retrosheet capabilities."""
    from baseball_rag.retrosheet_query import execute_retrosheet_query

    try:
        return execute_retrosheet_query(req.question)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
