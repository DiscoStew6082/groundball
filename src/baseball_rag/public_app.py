"""Provider-neutral composition for local and hosted Ground Ball applications."""

from __future__ import annotations

import asyncio
import os
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from baseball_rag.public_admission import CasCoordinator, CasStore, InMemoryCasStore
from baseball_rag.public_execution import ExecutionOutcome, ExecutionRequest
from baseball_rag.public_release_config import (
    MINIMUM_VISITOR_DIGEST_KEY_BYTES,
    load_runtime_configuration,
)

INITIALIZATION_WAIT_SECONDS = 5.0
_UNAVAILABLE_BODY = {
    "error": "service_unavailable",
    "detail": "Ground Ball public service is unavailable.",
}


class PublicExecutionRunner(Protocol):
    """Hard-stop execution boundary installed for both public POST routes."""

    def run(self, request: ExecutionRequest, *, timeout_seconds: float) -> ExecutionOutcome: ...


@dataclass(frozen=True)
class PublicAppBindings:
    """Deployment-owned bindings required by provider-neutral public composition."""

    store: CasStore
    digest_key: bytes
    initializer: Callable[[], None]
    execution_runner: PublicExecutionRunner


InitializationState = Literal["initializing", "ready", "failed"]


class _InitializationGate:
    """One process-wide immutable release-runtime initialization."""

    def __init__(self, initializer: Callable[[], None]) -> None:
        self._initializer = initializer
        self._state: InitializationState = "initializing"
        self._started = False
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self._wait_seconds = INITIALIZATION_WAIT_SECONDS

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
        threading.Thread(target=self._initialize, daemon=True).start()

    def _initialize(self) -> None:
        state: InitializationState = "failed"
        try:
            self._initializer()
            state = "ready"
        except Exception:  # noqa: BLE001 - initialization details stay private
            pass
        with self._lock:
            self._state = state
        self._finished.set()

    def wait_until_ready(self) -> bool:
        self.start()
        self._finished.wait(self._wait_seconds)
        with self._lock:
            return self._state == "ready"

    async def middleware(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        if not await asyncio.to_thread(self.wait_until_ready):
            return JSONResponse(_UNAVAILABLE_BODY, status_code=503)
        return await call_next(request)


class _ClosedGate:
    def __init__(self, *, expose_capabilities: bool = False) -> None:
        self._expose_capabilities = expose_capabilities

    async def middleware(self, request: Request, call_next):
        if request.url.path == "/health" or (
            self._expose_capabilities and request.url.path == "/api/capabilities"
        ):
            return await call_next(request)
        return JSONResponse(_UNAVAILABLE_BODY, status_code=503)


_process_lock = threading.Lock()
_process_bindings: PublicAppBindings | None = None
_process_gate: _InitializationGate | None = None


def _process_initialization(bindings: PublicAppBindings) -> _InitializationGate | None:
    global _process_bindings, _process_gate
    with _process_lock:
        if _process_bindings is None:
            _process_bindings = bindings
            _process_gate = _InitializationGate(bindings.initializer)
        elif _process_bindings is not bindings:
            return None
        return _process_gate


def _reset_initialization_for_tests() -> None:
    """Reset process state for deterministic test isolation only."""
    global _process_bindings, _process_gate
    with _process_lock:
        _process_bindings = None
        _process_gate = None


def _validated_components(
    bindings: PublicAppBindings,
) -> tuple[CasCoordinator, bytes, PublicExecutionRunner]:
    if (
        isinstance(bindings.store, InMemoryCasStore)
        or getattr(bindings.store, "deployment_shared", False) is not True
    ):
        raise ValueError("Public admission requires a deployment-shared CAS store.")
    if (
        not isinstance(bindings.digest_key, bytes)
        or len(bindings.digest_key) < MINIMUM_VISITOR_DIGEST_KEY_BYTES
    ):
        raise ValueError(
            f"The stable Visitor digest key must be at least "
            f"{MINIMUM_VISITOR_DIGEST_KEY_BYTES} bytes."
        )
    return CasCoordinator(bindings.store), bytes(bindings.digest_key), bindings.execution_runner


def create_app(
    *,
    bindings: PublicAppBindings | None = None,
    public: bool | None = None,
) -> FastAPI:
    """Create one local app or a process-shared fail-closed public app."""
    runtime_configured_public = False
    configured_public = os.environ.get("GROUNDBALL_PUBLIC_DEMO", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if public is None and bindings is None:
        runtime_path = os.environ.get("GROUNDBALL_RUNTIME_CONFIG")
        if runtime_path is not None:
            runtime_configured_public = load_runtime_configuration(runtime_path).public_mode
            configured_public = runtime_configured_public
    public_mode = (bindings is not None or configured_public) if public is None else public
    if bindings is not None and not public_mode:
        raise ValueError("Public bindings require public mode.")

    from baseball_rag.api.server import create_server_app

    if not public_mode:
        return create_server_app(public_mode=False, lifespan=None)
    if bindings is None:
        closed_gate = _ClosedGate(expose_capabilities=runtime_configured_public)
        return create_server_app(
            public_mode=True,
            public_gate=closed_gate.middleware,
            lifespan=None,
        )

    coordinator, digest_key, execution_runner = _validated_components(bindings)
    gate = _process_initialization(bindings)
    if gate is None:
        closed_gate = _ClosedGate()
        return create_server_app(
            public_mode=True,
            public_gate=closed_gate.middleware,
            lifespan=None,
        )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        gate.start()
        yield

    return create_server_app(
        public_mode=True,
        public_components=(coordinator, digest_key, execution_runner),
        public_gate=gate.middleware,
        lifespan=lifespan,
    )
