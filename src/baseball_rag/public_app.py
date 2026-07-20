"""Provider-neutral composition for local and hosted Ground Ball applications."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse

from baseball_rag.public_admission import CasCoordinator, CasStore, InMemoryCasStore
from baseball_rag.public_execution import ExecutionOutcome, ExecutionRequest
from baseball_rag.public_release_config import MINIMUM_VISITOR_DIGEST_KEY_BYTES

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
    initializer: Callable[[CasCoordinator], None]
    execution_runner: PublicExecutionRunner


InitializationState = Literal["initializing", "ready", "failed"]


class _InitializationGate:
    def __init__(
        self,
        coordinator: CasCoordinator,
        initializer: Callable[[CasCoordinator], None],
    ) -> None:
        self._coordinator = coordinator
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
            self._initializer(self._coordinator)
            if self._coordinator.readiness().kind == "ready":
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
    async def middleware(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)
        return JSONResponse(_UNAVAILABLE_BODY, status_code=503)


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
    """Create one isolated local app or fail-closed public app lifecycle."""
    public_mode = bindings is not None if public is None else public
    if bindings is not None and not public_mode:
        raise ValueError("Public bindings require public mode.")

    from baseball_rag.api.server import create_server_app

    if not public_mode:
        return create_server_app(public_mode=False, lifespan=None)
    if bindings is None:
        closed_gate = _ClosedGate()
        return create_server_app(
            public_mode=True,
            public_gate=closed_gate.middleware,
            lifespan=None,
        )

    coordinator, digest_key, execution_runner = _validated_components(bindings)
    gate = _InitializationGate(coordinator, bindings.initializer)

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
