"""FastAPI server for Groundball."""

import hashlib
import hmac
import html
import os
import secrets
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)

from baseball_rag.public_admission import (
    AdmissionAttempt,
    AdmissionOutcome,
    AdmissionState,
    CasCoordinator,
    CasStore,
    InMemoryCasStore,
    MonthlyBudget,
    visitor_digest,
)
from baseball_rag.public_admission_blob import HttpTransport
from baseball_rag.public_execution import (
    ExecutionOutcome,
    ExecutionRequest,
    SubprocessExecutionRunner,
)
from baseball_rag.public_release_config import (
    COMPLETE_REQUEST_BODY_BYTE_LIMIT,
    EXECUTION_DEADLINE_SECONDS,
    MINIMUM_VISITOR_DIGEST_KEY_BYTES,
    QUESTION_CHARACTER_LIMIT,
    VISITOR_COOKIE_HTTP_ONLY,
    VISITOR_COOKIE_NAME,
    VISITOR_COOKIE_SAME_SITE,
    VISITOR_COOKIE_SECURE,
    RuntimeConfiguration,
    load_runtime_configuration,
    validate_release_environment,
)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Refuse to serve a configured Release Bundle that is not fully ready."""
    public_demo = _public_demo_enabled()
    bundle_configured = bool(os.environ.get("GROUNDBALL_RELEASE_BUNDLE"))
    if public_demo != bundle_configured:
        raise RuntimeError(
            "Public release configuration requires both GROUNDBALL_PUBLIC_DEMO and "
            "GROUNDBALL_RELEASE_BUNDLE."
        )
    if public_demo:
        from baseball_rag.release_runtime import release_readiness

        release_readiness()
        _configure_release_runtime_if_declared()
        _configure_public_admission_if_declared()
        _require_shared_public_admission()
    yield


router = APIRouter()
_CORS_ORIGINS_ENV_VAR = "GROUNDBALL_CORS_ORIGINS"
_ORIGIN_PROXY_TOKEN_ENV_VAR = "GROUNDBALL_ORIGIN_PROXY_TOKEN"
_ORIGIN_PROXY_TOKEN_HEADER = "x-groundball-proxy-token"
_PUBLIC_HEALTH_PATH = "/health"
_CORS_QUERY_PATHS = {"/api/query-runs", "/api/retrosheet/queries"}
_CORS_ALLOWED_METHOD = "POST"
_CORS_ALLOWED_HEADERS = ("content-type",)
_PUBLIC_QUERY_REQUEST_BYTES = COMPLETE_REQUEST_BODY_BYTE_LIMIT
_DEFAULT_CORS_ORIGINS = (
    "https://discostew.dev",
    "http://localhost:4321",
    "http://127.0.0.1:4321",
)
_REPOSITORY_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"
_PACKAGE_WEB_DIST = Path(__file__).resolve().parents[1] / "web_dist"
_PUBLIC_VISITOR_COOKIE = VISITOR_COOKIE_NAME
_PUBLIC_EXECUTION_DEADLINE_SECONDS = float(EXECUTION_DEADLINE_SECONDS)
_BLOB_CONFIGURATION_ENV_VARS = frozenset(
    {
        "GROUNDBALL_BLOB_NAMESPACE",
        "GROUNDBALL_BLOB_PROOF_ID",
        "GROUNDBALL_BLOB_STORE_ID",
        "GROUNDBALL_BLOB_TOKEN",
        "GROUNDBALL_VISITOR_DIGEST_KEY",
    }
)

# Wave 3 installs the shared Blob Adapter from strict startup configuration.
# Import-time process state is intentionally never coordination authority.
_public_admission: CasCoordinator | None = None
_visitor_digest_key: bytes | None = None
_public_admission_is_shared = False
_public_runtime_configuration: RuntimeConfiguration | None = None
_public_execution_runner = SubprocessExecutionRunner()


def configure_public_admission(
    *,
    store: CasStore,
    digest_key: bytes,
    clock: Callable[[], datetime] | None = None,
) -> CasCoordinator:
    """Install a future shared-store Adapter without coupling it to FastAPI."""
    global _public_admission, _public_admission_is_shared, _visitor_digest_key

    shared_store = getattr(store, "deployment_shared", False) is True
    if isinstance(store, InMemoryCasStore) or not shared_store:
        raise ValueError("Public admission requires a deployment-shared CAS store.")
    if not isinstance(digest_key, bytes) or len(digest_key) < MINIMUM_VISITOR_DIGEST_KEY_BYTES:
        raise ValueError(
            f"The stable Visitor digest key must be at least "
            f"{MINIMUM_VISITOR_DIGEST_KEY_BYTES} bytes."
        )
    coordinator = CasCoordinator(store, clock=clock)
    _public_admission = coordinator
    _visitor_digest_key = bytes(digest_key)
    _public_admission_is_shared = True
    return coordinator


def configure_public_admission_from_environment(
    *,
    environment: Mapping[str, str] | None = None,
    transport: HttpTransport | None = None,
) -> CasCoordinator:
    """Build the Blob Adapter and install it through the provider-neutral seam."""
    from baseball_rag.public_admission_blob import load_blob_public_admission

    configured = load_blob_public_admission(
        os.environ if environment is None else environment,
        transport=transport,
    )
    return configure_public_admission(
        store=configured.store,
        digest_key=configured.digest_key,
    )


def _configure_release_runtime_if_declared() -> None:
    global _public_admission, _public_admission_is_shared, _public_runtime_configuration
    global _visitor_digest_key

    configured_path = os.environ.get("GROUNDBALL_RUNTIME_CONFIG")
    if configured_path is None:
        return
    validate_release_environment(os.environ)
    configuration = load_runtime_configuration(configured_path)
    _public_runtime_configuration = configuration
    if configuration.scope != "local_ci":
        return
    if any(name in os.environ for name in _BLOB_CONFIGURATION_ENV_VARS):
        raise RuntimeError("Local CI runtime cannot use provider coordination configuration.")
    now = datetime.now(UTC)
    store = InMemoryCasStore(
        AdmissionState(
            monthly_budget=MonthlyBudget(
                period=now.strftime("%Y-%m"),
                charged_starts=0,
            )
        )
    )
    _public_admission = CasCoordinator(store)
    _visitor_digest_key = hashlib.sha256(
        b"ground-ball-local-ci-ephemeral-visitor-identity"
    ).digest()
    _public_admission_is_shared = False


def _configure_public_admission_if_declared() -> None:
    if _public_admission is not None:
        return
    if not any(name in os.environ for name in _BLOB_CONFIGURATION_ENV_VARS):
        return
    try:
        configure_public_admission_from_environment()
    except ValueError:
        raise RuntimeError(
            "Public startup requires valid shared public admission configuration."
        ) from None


def _shared_public_admission_components() -> tuple[CasCoordinator, bytes]:
    local_ci = (
        _public_runtime_configuration is not None
        and _public_runtime_configuration.scope == "local_ci"
        and _public_runtime_configuration.provider_deployment is False
    )
    if (
        _public_admission is None
        or _visitor_digest_key is None
        or (not _public_admission_is_shared and not local_ci)
    ):
        raise RuntimeError("Public startup requires shared public admission configuration.")
    return _public_admission, _visitor_digest_key


def _require_shared_public_admission() -> tuple[CasCoordinator, bytes]:
    coordinator, digest_key = _shared_public_admission_components()
    readiness = coordinator.readiness()
    if readiness.kind == "provider_unavailable":
        raise RuntimeError("Public admission coordination store is unavailable.")
    if readiness.kind != "ready":
        raise RuntimeError("Public admission current monthly budget is invalid.")
    return coordinator, digest_key


def _public_demo_enabled() -> bool:
    return os.environ.get("GROUNDBALL_PUBLIC_DEMO", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _request_is_public(request: Request) -> bool:
    override = getattr(request.app.state, "public_mode_override", None)
    return _public_demo_enabled() if override is None else bool(override)


def _require_consistent_release_configuration(request: Request | None = None) -> None:
    if request is not None and getattr(request.app.state, "public_mode_override", None) is not None:
        return
    public_demo = _public_demo_enabled()
    bundle_configured = bool(os.environ.get("GROUNDBALL_RELEASE_BUNDLE"))
    if public_demo != bundle_configured:
        raise HTTPException(
            status_code=503,
            detail="Ground Ball public release configuration is incomplete.",
        )


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


def _ensure_public_execution_deadline(request: Request) -> float:
    fallback_deadline = time.monotonic() + _PUBLIC_EXECUTION_DEADLINE_SECONDS
    established_deadline = getattr(request.state, "public_execution_deadline", None)
    deadline = (
        min(established_deadline, fallback_deadline)
        if isinstance(established_deadline, (int, float))
        else fallback_deadline
    )
    request.state.public_execution_deadline = deadline
    return deadline


async def _origin_proxy_token_middleware(request: Request, call_next):
    configured_token = os.environ.get(_ORIGIN_PROXY_TOKEN_ENV_VAR)
    if not configured_token or request.url.path == _PUBLIC_HEALTH_PATH:
        return await call_next(request)

    if not _origin_proxy_token_is_valid(request, configured_token):
        return JSONResponse({"error": "groundball_origin_proxy_token_required"}, status_code=403)

    return await call_next(request)


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

    is_public_query_request = (
        _request_is_public(request)
        and request.url.path in _CORS_QUERY_PATHS
        and request.method == _CORS_ALLOWED_METHOD
    )
    if is_public_query_request:
        _ensure_public_execution_deadline(request)
    if is_public_query_request and len(await request.body()) > _PUBLIC_QUERY_REQUEST_BYTES:
        refusal = JSONResponse(
            {
                "error": "request_too_large",
                "detail": "Public Query Run requests may not exceed 16384 bytes.",
            },
            status_code=413,
        )
        if _cors_origin_is_allowed(origin):
            return _add_query_cors_headers(refusal, origin or "")
        return refusal

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

    question: str | None = Field(default=None, min_length=1, max_length=QUESTION_CHARACTER_LIMIT)
    recipe: dict[str, Any] | None = None
    previous_recipe: dict[str, Any] | None = None


class RetrosheetQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=QUESTION_CHARACTER_LIMIT)


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/api/capabilities")
def capabilities(request: Request):
    """Return the server-enforced feature set for the unified web app."""
    from baseball_rag.retrosheet_event_capabilities import (
        published_retrosheet_event_capabilities,
        retrosheet_event_capabilities,
    )

    _require_consistent_release_configuration(request)
    public_demo = _request_is_public(request)
    retrosheet_capabilities = (
        published_retrosheet_event_capabilities()
        if public_demo
        else retrosheet_event_capabilities()
    )
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
        "retrosheet_capabilities": [
            {
                "capability_id": capability.capability_id,
                "title": capability.title,
                "query_families": list(capability.supported_query_families),
            }
            for capability in retrosheet_capabilities
        ],
        "llm_required": False,
        "history": "browser_local",
    }


@router.post("/api/query-runs")
def query_run(req: QueryInputRequest, request: Request):
    """Plan and execute one natural-language or structured Query Recipe input."""
    _require_consistent_release_configuration(request)
    if (req.question is None) == (req.recipe is None):
        raise HTTPException(
            status_code=422,
            detail="Provide exactly one natural-language question or structured recipe.",
        )
    if req.previous_recipe is not None and req.question is None:
        raise HTTPException(
            status_code=422,
            detail="Previous recipe context is accepted only with a natural-language question.",
        )

    if _request_is_public(request):
        return _execute_public_request(
            request,
            ExecutionRequest(
                operation="query",
                question=req.question,
                recipe=req.recipe,
                previous_recipe=req.previous_recipe,
            ),
        )

    from baseball_rag.query.adapters import run_query_input

    try:
        return run_query_input(
            question=req.question,
            recipe=req.recipe,
            previous_recipe=req.previous_recipe,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _execute_public_request(request: Request, execution: ExecutionRequest) -> Response:
    try:
        configured = getattr(request.app.state, "public_components", None)
        if configured is None:
            coordinator, digest_key = _shared_public_admission_components()
            execution_runner = _public_execution_runner
        else:
            coordinator, digest_key, execution_runner = configured
    except RuntimeError:
        return JSONResponse(
            {
                "error": "provider_unavailable",
                "detail": "Ground Ball's public admission service is unavailable.",
            },
            status_code=503,
        )

    deadline = _ensure_public_execution_deadline(request)
    visitor_token = request.cookies.get(_PUBLIC_VISITOR_COOKIE)
    new_visitor = visitor_token is None
    if visitor_token is None:
        visitor_token = secrets.token_urlsafe(32)
    visitor = visitor_digest(visitor_token, digest_key=digest_key)
    run_id = secrets.token_hex(16)
    admission = coordinator.admit(
        AdmissionAttempt(visitor=visitor, run_id=run_id, now=datetime.now(UTC))
    )
    response: Response
    if admission.kind != "admitted":
        response = _admission_refusal_response(admission)
    else:
        remaining = deadline - time.monotonic()
        try:
            execution_outcome = (
                execution_runner.run(execution, timeout_seconds=remaining)
                if remaining > 0
                else ExecutionOutcome("timed_out")
            )
            response = _execution_outcome_response(execution_outcome)
        finally:
            coordinator.release(run_id)
    if new_visitor:
        _set_visitor_cookie(response, visitor_token)
    return response


def _execution_outcome_response(outcome: ExecutionOutcome) -> Response:
    if outcome.kind == "completed" and outcome.payload is not None:
        from baseball_rag.public_results import compact_json_bytes

        payload = jsonable_encoder(outcome.payload)
        status_code = 422 if payload.get("kind") == "export_too_large" else 200
        return Response(
            content=compact_json_bytes(payload),
            media_type="application/json",
            status_code=status_code,
        )
    if outcome.kind == "invalid":
        return JSONResponse({"detail": outcome.detail}, status_code=422)
    if outcome.kind == "timed_out":
        return JSONResponse(
            {
                "error": "timed_out",
                "detail": (
                    "The Query Run reached its 10-second deadline and was stopped. "
                    "Narrow the question before trying again."
                ),
            },
            status_code=503,
        )
    return JSONResponse(
        {
            "error": "provider_unavailable",
            "detail": "Public Query Run execution failed.",
        },
        status_code=503,
    )


def _set_visitor_cookie(response: Response, visitor_token: str) -> None:
    response.set_cookie(
        _PUBLIC_VISITOR_COOKIE,
        visitor_token,
        secure=VISITOR_COOKIE_SECURE,
        httponly=VISITOR_COOKIE_HTTP_ONLY,
        samesite=VISITOR_COOKIE_SAME_SITE,
        path="/",
    )


def _admission_refusal_response(outcome: AdmissionOutcome) -> JSONResponse:
    retry_at = outcome.retry_at.isoformat() if outcome.retry_at else None
    messages = {
        "visitor_run_active": "Another Query Run for this visitor is still running.",
        "deployment_capacity_occupied": "Ground Ball is busy serving other Query Runs.",
        "three_starts_per_minute": "This visitor reached three Query Runs per minute.",
        "twelve_starts_per_hour": "This visitor reached twelve Query Runs per hour.",
        "monthly_start_budget_exhausted": (
            "Ground Ball's monthly public Query Run allowance is paused."
        ),
        "monthly_budget_unavailable": (
            "Ground Ball's monthly public allowance state is unavailable."
        ),
        "monthly_budget_invalid": "Ground Ball's monthly public allowance state is invalid.",
        "coordination_store_unavailable": "Ground Ball's public admission service is unavailable.",
        "coordination_contention": "Ground Ball could not safely coordinate this Query Run.",
    }
    detail = messages.get(outcome.reason, "Ground Ball could not admit this Query Run.")
    if retry_at:
        detail = f"{detail} Retry at {retry_at}."
    status_code = 429 if outcome.kind in {"busy", "rate_limited"} else 503
    headers: dict[str, str] = {}
    if outcome.retry_after_seconds is not None:
        headers["Retry-After"] = str(outcome.retry_after_seconds)
    return JSONResponse(
        {
            "error": outcome.kind,
            "reason": outcome.reason,
            "detail": detail,
            "retry_at": retry_at,
        },
        status_code=status_code,
        headers=headers,
    )


@router.get("/api/query-catalog")
def query_catalog(
    request: Request,
    source: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int | None = None,
):
    """Return rendering-neutral source, raw-field, and promoted-value discovery."""
    _require_consistent_release_configuration(request)
    from baseball_rag.query.adapters import catalog_payload

    try:
        return catalog_payload(source=source, search=search, offset=offset, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/query-coverage")
def query_coverage(request: Request):
    """Return the canonical machine-readable Coverage Report."""
    _require_consistent_release_configuration(request)
    from baseball_rag.query.coverage import (
        CoverageProofUnavailableError,
        load_passing_coverage_report,
    )

    try:
        return load_passing_coverage_report()
    except CoverageProofUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/coverage-report", response_class=HTMLResponse)
def coverage_report(request: Request):
    """Render the human report from the canonical machine read model."""
    _require_consistent_release_configuration(request)
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


@router.post("/api/retrosheet/queries")
def retrosheet_query(req: RetrosheetQueryRequest, request: Request):
    """Execute only the separately governed deterministic Retrosheet capabilities."""
    _require_consistent_release_configuration(request)
    if _request_is_public(request):
        return _execute_public_request(
            request,
            ExecutionRequest(operation="retrosheet", question=req.question, recipe=None),
        )

    from baseball_rag.retrosheet_query import execute_retrosheet_query

    try:
        return execute_retrosheet_query(req.question)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/release-readiness")
def release_readiness(request: Request):
    """Return the checked public bundle, proof, and in-memory runtime identities."""
    _require_consistent_release_configuration(request)
    if not _request_is_public(request):
        raise HTTPException(status_code=404, detail="Not found.")
    try:
        configured = getattr(request.app.state, "public_components", None)
        if configured is None:
            _require_shared_public_admission()
        elif configured[0].readiness().kind != "ready":
            raise RuntimeError("Public admission is unavailable.")
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail="Ground Ball public admission is not ready.",
        ) from exc
    from baseball_rag.release_runtime import release_readiness as read_release_readiness

    payload = read_release_readiness().as_dict()
    if _public_runtime_configuration is not None:
        payload["runtime_configuration"] = {
            "digest": _public_runtime_configuration.digest,
            "provider_deployment": _public_runtime_configuration.provider_deployment,
            "scope": _public_runtime_configuration.scope,
        }
    return payload


def _web_dist_path() -> Path:
    configured = os.environ.get("GROUNDBALL_WEB_DIST")
    if configured:
        return Path(configured)
    if (_REPOSITORY_WEB_DIST / "index.html").is_file():
        return _REPOSITORY_WEB_DIST
    return _PACKAGE_WEB_DIST


@router.get("/{full_path:path}")
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


def create_server_app(
    *,
    public_mode: bool | None = None,
    public_components: tuple[CasCoordinator, bytes, Any] | None = None,
    public_gate: Any = None,
    lifespan: Any = _lifespan,
) -> FastAPI:
    """Install the existing server routes with app-scoped public composition."""
    created = FastAPI(title="Groundball API", lifespan=lifespan)
    created.state.public_mode_override = public_mode
    created.state.public_components = public_components
    created.middleware("http")(_origin_proxy_token_middleware)
    created.middleware("http")(_query_cors_middleware)
    if public_gate is not None:

        async def gated(request: Request, call_next):
            if request.url.path in _CORS_QUERY_PATHS and request.method == _CORS_ALLOWED_METHOD:
                _ensure_public_execution_deadline(request)
            return await public_gate(request, call_next)

        created.middleware("http")(gated)
    created.include_router(router)
    return created


# Preserve the historical direct-import ASGI application and environment startup.
app = create_server_app()
