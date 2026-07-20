"""Provider-neutral public application composition behavior."""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import baseball_rag.api.server as api_server
import baseball_rag.public_app as public_app_module
from baseball_rag.public_admission import (
    AdmissionState,
    CasSnapshot,
    CasStore,
    InMemoryCasStore,
    MonthlyBudget,
)
from baseball_rag.public_app import PublicAppBindings, create_app
from baseball_rag.public_execution import ExecutionOutcome, ExecutionRequest

UNAVAILABLE = {
    "error": "provider_unavailable",
    "detail": "Ground Ball public service is unavailable.",
}


class SharedMemoryStore:
    """Deployment-shared contract double backed by process-local memory."""

    def __init__(self, state: AdmissionState | None = None) -> None:
        self.inner = InMemoryCasStore(state)

    @property
    def deployment_shared(self) -> bool:
        return True

    def read(self) -> CasSnapshot:
        return self.inner.read()

    def compare_and_swap(self, version, state: AdmissionState) -> bool:
        return self.inner.compare_and_swap(version, state)


class RecordingRunner:
    def __init__(self, outcome: ExecutionOutcome | None = None) -> None:
        self.outcome = outcome or ExecutionOutcome(
            "completed", payload={"kind": "rows", "rows": []}
        )
        self.requests: list[ExecutionRequest] = []
        self.timeouts: list[float] = []

    def run(self, request: ExecutionRequest, *, timeout_seconds: float) -> ExecutionOutcome:
        self.requests.append(request)
        self.timeouts.append(timeout_seconds)
        return self.outcome


def ready_store() -> SharedMemoryStore:
    period = datetime.now(UTC).strftime("%Y-%m")
    return SharedMemoryStore(
        AdmissionState(monthly_budget=MonthlyBudget(period=period, charged_starts=0))
    )


def bindings(
    *,
    store: SharedMemoryStore | None = None,
    initializer=None,
    runner: RecordingRunner | None = None,
) -> PublicAppBindings:
    return PublicAppBindings(
        store=store or ready_store(),
        digest_key=b"stable-public-visitor-digest-key",
        initializer=initializer or (lambda _coordinator: None),
        execution_runner=runner or RecordingRunner(),
    )


def test_local_factory_preserves_health_capabilities_and_direct_server_app() -> None:
    factory_client = TestClient(create_app())
    direct_client = TestClient(api_server.app)

    assert factory_client.get("/health").json() == {"status": "ok"}
    capabilities = factory_client.get("/api/capabilities")
    assert capabilities.status_code == 200
    assert capabilities.json()["mode"] == "local"
    assert direct_client.get("/health").json() == {"status": "ok"}
    assert direct_client.get("/api/capabilities").json()["mode"] == "local"


def test_local_factory_preserves_both_deterministic_post_routes() -> None:
    client = TestClient(create_app())

    query = client.post("/api/query-runs", json={})
    retrosheet = client.post(
        "/api/retrosheet/queries",
        json={"question": "not a published Retrosheet question"},
    )

    assert query.status_code == 422
    assert retrosheet.status_code == 422


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/api/capabilities", None),
        ("post", "/api/query-runs", {"question": "40-40"}),
        (
            "post",
            "/api/retrosheet/queries",
            {"question": "how many times did Nolan Ryan strike out the side"},
        ),
    ],
)
def test_explicit_public_mode_without_bindings_is_sanitized_and_fail_closed(
    method: str, path: str, payload: dict[str, str] | None
) -> None:
    client = TestClient(create_app(public=True))

    response = client.request(method, path, json=payload)

    assert client.get("/health").json() == {"status": "ok"}
    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


def test_unbound_public_gate_precedes_request_parsing_and_size_policy() -> None:
    response = TestClient(create_app(public=True)).post(
        "/api/query-runs",
        content=b"x" * 20_000,
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 503
    assert response.json() == UNAVAILABLE


def test_bindings_initialize_once_and_drive_both_public_post_routes() -> None:
    store = ready_store()
    runner = RecordingRunner()
    initialized_with = []
    app = create_app(
        bindings=bindings(
            store=store,
            runner=runner,
            initializer=lambda coordinator: initialized_with.append(coordinator),
        )
    )

    with TestClient(app, base_url="https://testserver") as client:
        query = client.post("/api/query-runs", json={"question": "40-40"})
        retrosheet = client.post(
            "/api/retrosheet/queries",
            json={"question": "how many times did Nolan Ryan strike out the side"},
        )
        assert client.get("/api/capabilities").json()["mode"] == "public"

    assert query.status_code == retrosheet.status_code == 200
    assert len(initialized_with) == 1
    assert [request.operation for request in runner.requests] == ["query", "retrosheet"]
    assert all(0 < timeout <= 10 for timeout in runner.timeouts)
    state = store.read().state
    assert state.running == ()
    assert state.monthly_budget == MonthlyBudget(
        period=datetime.now(UTC).strftime("%Y-%m"), charged_starts=2
    )


def test_health_never_waits_while_non_health_wait_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_initializer = threading.Event()
    initializer_started = threading.Event()
    gated_wait_started = threading.Event()
    original_wait_until_ready = public_app_module._InitializationGate.wait_until_ready

    def initialize(_coordinator) -> None:
        initializer_started.set()
        release_initializer.wait()

    def observe_gated_wait(gate) -> bool:
        gated_wait_started.set()
        return original_wait_until_ready(gate)

    monkeypatch.setattr(public_app_module, "INITIALIZATION_WAIT_SECONDS", 5.0)
    monkeypatch.setattr(
        public_app_module._InitializationGate,
        "wait_until_ready",
        observe_gated_wait,
    )
    app = create_app(bindings=bindings(initializer=initialize))
    with (
        TestClient(app) as gated_client,
        TestClient(app) as health_client,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        assert initializer_started.wait(1)
        gated_request = executor.submit(gated_client.get, "/api/capabilities")
        assert gated_wait_started.wait(1)
        try:
            assert health_client.get("/health").status_code == 200
            assert not gated_request.done()
        finally:
            release_initializer.set()

        gated = gated_request.result(timeout=1)
        assert gated.status_code == 200


def test_initializer_exception_is_sanitized_and_never_retried() -> None:
    calls = 0

    def fail(_coordinator) -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("sensitive provider initialization detail")

    with TestClient(create_app(bindings=bindings(initializer=fail))) as client:
        first = client.get("/api/capabilities")
        second = client.post("/api/query-runs", json={"question": "40-40"})

    assert calls == 1
    assert first.status_code == second.status_code == 503
    assert first.json() == second.json() == UNAVAILABLE
    assert "sensitive" not in first.text + second.text


def test_created_apps_keep_initialization_state_isolated() -> None:
    failed = create_app(
        bindings=bindings(initializer=lambda _coordinator: (_ for _ in ()).throw(OSError()))
    )
    ready = create_app(bindings=bindings())

    with TestClient(failed) as failed_client, TestClient(ready) as ready_client:
        assert failed_client.get("/api/capabilities").status_code == 503
        assert ready_client.get("/api/capabilities").status_code == 200


def test_execution_outcome_formatting_failure_still_releases_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = ready_store()
    app = create_app(bindings=bindings(store=store))

    def fail_formatting(_outcome: ExecutionOutcome):
        raise TypeError("serialization failed")

    monkeypatch.setattr(api_server, "_execution_outcome_response", fail_formatting)
    with TestClient(app) as client, pytest.raises(TypeError, match="serialization failed"):
        client.post("/api/query-runs", json={"question": "40-40"})

    assert store.read().state.running == ()


@pytest.mark.parametrize("hard_stop_offset", [None, 0.25])
def test_public_execution_uses_fallback_or_existing_monotonic_deadline(
    hard_stop_offset: float | None,
) -> None:
    runner = RecordingRunner()
    app = create_app(bindings=bindings(runner=runner))
    if hard_stop_offset is not None:

        @app.middleware("http")
        async def establish_earlier_deadline(request: Request, call_next):
            request.state.public_execution_deadline = time.monotonic() + hard_stop_offset
            return await call_next(request)

    with TestClient(app) as client:
        response = client.post("/api/query-runs", json={"question": "40-40"})

    assert response.status_code == 200
    assert 0 < runner.timeouts[0] <= (hard_stop_offset or 10)
    if hard_stop_offset is None:
        assert runner.timeouts[0] > 9


@pytest.mark.parametrize(
    "invalid_bindings",
    [
        PublicAppBindings(
            store=cast(CasStore, InMemoryCasStore()),
            digest_key=b"x" * 32,
            initializer=lambda _coordinator: None,
            execution_runner=RecordingRunner(),
        ),
        PublicAppBindings(
            store=ready_store(),
            digest_key=b"short",
            initializer=lambda _coordinator: None,
            execution_runner=RecordingRunner(),
        ),
    ],
)
def test_public_factory_rejects_unsafe_shared_state_bindings(
    invalid_bindings: PublicAppBindings,
) -> None:
    with pytest.raises(ValueError):
        create_app(bindings=invalid_bindings)
