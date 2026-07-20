"""Provider startup admission state machine contracts."""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Event, Lock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

import baseball_rag.api.server as api_server
from baseball_rag.api.server import app
from baseball_rag.public_admission import AdmissionOutcome
from baseball_rag.public_admission_blob import BlobProviderError, OidcBlobCredentialProvider
from baseball_rag.public_execution import ExecutionOutcome
from baseball_rag.public_release_config import RuntimeConfiguration
from baseball_rag.release_runtime import ReleaseReadiness


def provider_configuration() -> RuntimeConfiguration:
    return RuntimeConfiguration(
        scope="protected_preview",
        provider_deployment=True,
        public_mode=True,
        network_policy="provider_coordination_only",
        admission_adapter="vercel_blob",
        release_bundle="ground-ball-release-bundle",
        resource_references=("BLOB_STORE_ID",),
        startup_credential_references=(),
        request_credential_headers=("x-vercel-oidc-token",),
        secret_references=("GROUNDBALL_VISITOR_DIGEST_KEY",),
    )


def readiness() -> ReleaseReadiness:
    return ReleaseReadiness(
        release_bundle_digest="a" * 64,
        source_commit="b" * 40,
        data_release="lahman-test",
        coverage_report={"status": "pass"},
        relations=("people",),
    )


def configure_provider_lifespan(
    monkeypatch: pytest.MonkeyPatch,
    initializer,
) -> None:
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", "/private/release/bundle")
    monkeypatch.setattr(api_server, "_public_runtime_configuration", provider_configuration())
    monkeypatch.setattr(api_server, "_configure_release_runtime_if_declared", lambda: None)
    monkeypatch.setattr(api_server, "_configure_public_admission_if_declared", lambda: None)
    monkeypatch.setattr(api_server, "_provider_runtime_initializer", initializer)
    monkeypatch.setattr(
        api_server,
        "_provider_initialization",
        api_server._ProviderInitialization(),
    )


def test_provider_lifespan_yields_while_initializer_is_blocked_beyond_fifteen_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()

    def blocked_initializer() -> ReleaseReadiness:
        started.set()
        time.sleep(15.1)
        return readiness()

    configure_provider_lifespan(monkeypatch, blocked_initializer)

    before = time.monotonic()
    with TestClient(app) as client:
        startup_seconds = time.monotonic() - before
        assert started.wait(timeout=1)
        before_health = time.monotonic()
        response = client.get("/health")
        health_seconds = time.monotonic() - before_health
        assert startup_seconds < 1
        assert health_seconds < 1
        assert response.status_code == 503
        assert response.json() == {"status": "initializing"}


def test_provider_lifespan_without_startup_oidc_constructs_admission_and_yields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()

    def blocked_bundle_initializer() -> ReleaseReadiness:
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", "/private/release/bundle")
    monkeypatch.setenv("BLOB_STORE_ID", "store_ProofStore123")
    monkeypatch.setenv("GROUNDBALL_BLOB_NAMESPACE", "protected_preview")
    monkeypatch.setenv(
        "GROUNDBALL_VISITOR_DIGEST_KEY",
        "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s=",
    )
    monkeypatch.delenv("VERCEL_OIDC_TOKEN", raising=False)
    monkeypatch.setattr(api_server, "_public_runtime_configuration", provider_configuration())
    monkeypatch.setattr(api_server, "_configure_release_runtime_if_declared", lambda: None)
    monkeypatch.setattr(api_server, "_public_admission", None)
    monkeypatch.setattr(api_server, "_visitor_digest_key", None)
    monkeypatch.setattr(api_server, "_public_admission_is_shared", False)
    monkeypatch.setattr(api_server, "_provider_runtime_initializer", blocked_bundle_initializer)
    monkeypatch.setattr(
        api_server,
        "_provider_initialization",
        api_server._ProviderInitialization(),
    )

    with TestClient(app) as client:
        try:
            assert started.wait(timeout=1)
            assert client.get("/health").json() == {"status": "initializing"}
        finally:
            release.set()


def test_direct_browser_request_waits_for_local_readiness_then_serves_html(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    request_started = Event()

    def blocked_initializer() -> ReleaseReadiness:
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    configure_provider_lifespan(monkeypatch, blocked_initializer)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        assert started.wait(timeout=1)

        def get_root():
            request_started.set()
            return client.get("/")

        pending_response = executor.submit(get_root)
        try:
            assert request_started.wait(timeout=1)
            with pytest.raises(FutureTimeoutError):
                pending_response.result(timeout=0.1)
        finally:
            release.set()
        response = pending_response.result(timeout=2)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Ground Ball" in response.text


def test_direct_api_request_waits_for_local_readiness_then_serves_capabilities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    request_started = Event()

    def blocked_initializer() -> ReleaseReadiness:
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    configure_provider_lifespan(monkeypatch, blocked_initializer)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        assert started.wait(timeout=1)

        def get_capabilities():
            request_started.set()
            return client.get("/api/capabilities")

        pending_response = executor.submit(get_capabilities)
        try:
            assert request_started.wait(timeout=1)
            with pytest.raises(FutureTimeoutError):
                pending_response.result(timeout=0.1)
        finally:
            release.set()
        response = pending_response.result(timeout=2)

    assert response.status_code == 200
    assert response.json()["name"] == "Ground Ball"
    assert response.json()["mode"] == "public"


def test_concurrent_cold_requests_coalesce_behind_one_initializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    calls = 0
    calls_lock = Lock()

    def blocked_initializer() -> ReleaseReadiness:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    configure_provider_lifespan(monkeypatch, blocked_initializer)

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=8) as executor:
        assert started.wait(timeout=1)
        requests = tuple(
            executor.submit(client.get, "/" if index % 2 == 0 else "/api/capabilities")
            for index in range(8)
        )
        try:
            for pending_response in requests:
                with pytest.raises(FutureTimeoutError):
                    pending_response.result(timeout=0.05)
            assert calls == 1
        finally:
            release.set()
        responses = tuple(pending.result(timeout=2) for pending in requests)

    assert calls == 1
    assert all(response.status_code == 200 for response in responses)


def test_provider_background_initialization_fully_verifies_then_publishes_cache_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = readiness()
    canonical_runtime = object()
    calls: list[object] = []

    def clear_reference() -> None:
        calls.append("clear")

    def heavy_readiness() -> ReleaseReadiness:
        calls.append("readiness")
        return expected

    def loaded_runtime():
        calls.append("runtime")
        return canonical_runtime

    def prepare(runtime, **identities) -> None:
        calls.append((runtime, identities))

    def forbidden_provider_io():
        raise AssertionError("background initialization must not perform provider I/O")

    monkeypatch.setattr(api_server, "_public_runtime_configuration", provider_configuration())
    monkeypatch.setattr(
        "baseball_rag.provider_runtime_cache.clear_provider_runtime_cache_reference",
        clear_reference,
    )
    monkeypatch.setattr("baseball_rag.release_runtime.release_readiness", heavy_readiness)
    monkeypatch.setattr("baseball_rag.query.runtime.published_data_runtime", loaded_runtime)
    monkeypatch.setattr(
        "baseball_rag.provider_runtime_cache.prepare_provider_runtime_cache", prepare
    )
    monkeypatch.setattr(api_server, "_require_shared_public_admission", forbidden_provider_io)

    assert api_server._provider_runtime_initializer() is expected
    assert calls == [
        "clear",
        "readiness",
        "runtime",
        (
            canonical_runtime,
            {
                "source_commit": "b" * 40,
                "release_bundle_digest": "a" * 64,
                "runtime_configuration_digest": provider_configuration().digest,
            },
        ),
    ]


def test_provider_initialization_transitions_once_to_ready_and_request_readiness_proves_blob(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_readiness = readiness()
    request_oidc = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJyZXF1ZXN0In0.request-signature"
    provider = OidcBlobCredentialProvider()
    calls = {"heavy": 0, "cache": 0, "admission": 0}
    calls_lock = Lock()

    def heavy_readiness() -> ReleaseReadiness:
        with calls_lock:
            calls["heavy"] += 1
        return expected_readiness

    def admission_readiness():
        try:
            assert provider.resolve() == request_oidc
        except BlobProviderError:
            raise RuntimeError("request-scoped Blob credential unavailable") from None
        with calls_lock:
            calls["admission"] += 1
        return object(), b"x" * 32

    def prepare_cache(*_args, **_kwargs) -> None:
        with calls_lock:
            calls["cache"] += 1

    configure_provider_lifespan(monkeypatch, api_server._provider_runtime_initializer)
    monkeypatch.setattr("baseball_rag.release_runtime.release_readiness", heavy_readiness)
    monkeypatch.setattr("baseball_rag.query.runtime.published_data_runtime", lambda: object())
    monkeypatch.setattr(
        "baseball_rag.provider_runtime_cache.prepare_provider_runtime_cache", prepare_cache
    )
    monkeypatch.setattr(api_server, "_require_shared_public_admission", admission_readiness)

    with TestClient(app) as client:
        for _ in range(100):
            health = client.get("/health")
            if health.status_code == 200:
                break
            time.sleep(0.01)
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        first = client.get("/api/release-readiness", headers={"x-vercel-oidc-token": request_oidc})
        second = client.get("/api/release-readiness", headers={"x-vercel-oidc-token": request_oidc})
        missing = client.get("/api/release-readiness")
        invalid = client.get("/api/release-readiness", headers={"x-vercel-oidc-token": "not-a-jwt"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["release_bundle_digest"] == "a" * 64
    assert second.json() == first.json()
    assert missing.status_code == 503
    assert invalid.status_code == 503
    assert (
        missing.json() == invalid.json() == {"detail": "Ground Ball public admission is not ready."}
    )
    assert calls == {"heavy": 1, "cache": 1, "admission": 2}


def test_provider_initializer_cannot_mark_an_invalid_readiness_object_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_provider_lifespan(monkeypatch, lambda: object())

    with TestClient(app) as client:
        for _ in range(100):
            health = client.get("/health")
            if health.json() == {"status": "failed"}:
                break
            time.sleep(0.01)

    assert health.status_code == 503
    assert health.json() == {"status": "failed"}


def test_provider_initialization_failure_wakes_all_waiters_with_fixed_secret_safe_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    fail = Event()
    calls = 0
    secret = "super-secret-token /private/release/bundle"

    def failing_initializer() -> ReleaseReadiness:
        nonlocal calls
        calls += 1
        started.set()
        assert fail.wait(timeout=30)
        raise RuntimeError(secret)

    configure_provider_lifespan(monkeypatch, failing_initializer)
    expected = {
        "error": "service_unavailable",
        "detail": "Ground Ball is not ready.",
    }

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=6) as executor:
        assert started.wait(timeout=1)
        waiters = tuple(executor.submit(client.get, "/api/capabilities") for _ in range(6))
        try:
            for waiter in waiters:
                with pytest.raises(FutureTimeoutError):
                    waiter.result(timeout=0.05)
        finally:
            fail.set()
        responses = tuple(waiter.result(timeout=2) for waiter in waiters)
        health = client.get("/health")
        repeated = tuple(client.get("/api/release-readiness") for _ in range(3))

    assert health.status_code == 503
    assert health.json() == {"status": "failed"}
    assert all(response.status_code == 503 for response in responses + repeated)
    assert all(response.json() == expected for response in responses + repeated)
    rendered = health.text + "".join(response.text for response in responses + repeated)
    assert secret not in rendered
    assert "token" not in rendered
    assert "/private" not in rendered
    assert calls == 1


def test_cold_request_timeout_does_not_cancel_or_restart_initializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    calls = 0

    def blocked_initializer() -> ReleaseReadiness:
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    configure_provider_lifespan(monkeypatch, blocked_initializer)
    monkeypatch.setattr(api_server, "_PROVIDER_READINESS_WAIT_SECONDS", 0.05)

    with TestClient(app) as client:
        try:
            assert started.wait(timeout=1)
            timed_out = client.get("/")
            assert timed_out.status_code == 503
            assert timed_out.json() == {
                "error": "service_unavailable",
                "detail": "Ground Ball is not ready.",
            }
            assert client.get("/health").json() == {"status": "initializing"}
            assert calls == 1
        finally:
            release.set()

        for _ in range(100):
            health = client.get("/health")
            if health.status_code == 200:
                break
            time.sleep(0.01)
        later = client.get("/")

    assert health.status_code == 200
    assert later.status_code == 200
    assert calls == 1


def test_query_body_admission_oidc_and_execution_deadline_begin_only_after_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    request_oidc = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJjb2xkIn0.request-signature"
    provider = OidcBlobCredentialProvider()
    admission_calls: list[float] = []
    execution_timeouts: list[float] = []

    def blocked_initializer() -> ReleaseReadiness:
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    class RecordingCoordinator:
        def admit(self, _attempt):
            admission_calls.append(time.monotonic())
            return AdmissionOutcome("admitted", "admitted")

        def release(self, _run_id):
            return None

    class RecordingRunner:
        def run(self, _execution, *, timeout_seconds: float):
            execution_timeouts.append(timeout_seconds)
            return ExecutionOutcome("completed", payload={"kind": "rows", "rows": []})

    coordinator = RecordingCoordinator()

    def request_scoped_components():
        try:
            assert provider.resolve() == request_oidc
        except BlobProviderError:
            raise RuntimeError("request-scoped Blob credential unavailable") from None
        return coordinator, b"x" * 32

    configure_provider_lifespan(monkeypatch, blocked_initializer)
    monkeypatch.setattr(
        api_server, "_shared_public_admission_components", request_scoped_components
    )
    monkeypatch.setattr(api_server, "_public_execution_runner", RecordingRunner())

    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as executor:
        assert started.wait(timeout=1)
        query = executor.submit(
            client.post,
            "/api/query-runs",
            json={"question": "who had the most RBIs in 1962"},
            headers={"x-vercel-oidc-token": request_oidc},
        )
        oversized = executor.submit(
            client.post,
            "/api/query-runs",
            content=b"{" + b"x" * 16_384,
            headers={"content-type": "application/json"},
        )
        try:
            with pytest.raises(FutureTimeoutError):
                query.result(timeout=0.1)
            with pytest.raises(FutureTimeoutError):
                oversized.result(timeout=0.1)
            assert admission_calls == []
            assert execution_timeouts == []
        finally:
            release.set()

        query_response = query.result(timeout=2)
        oversized_response = oversized.result(timeout=2)
        missing = client.post("/api/query-runs", json={"question": "who had the most RBIs in 1962"})
        invalid = client.post(
            "/api/query-runs",
            json={"question": "who had the most RBIs in 1962"},
            headers={"x-vercel-oidc-token": "not-a-jwt"},
        )

    assert query_response.status_code == 200
    assert oversized_response.status_code == 413
    assert oversized_response.json()["error"] == "request_too_large"
    assert len(admission_calls) == 1
    assert len(execution_timeouts) == 1
    assert 9.5 < execution_timeouts[0] <= 10
    assert missing.status_code == 503
    assert invalid.status_code == 503
    assert missing.json() == {
        "error": "provider_unavailable",
        "detail": "Ground Ball's public admission service is unavailable.",
    }
    assert invalid.json() == missing.json()
    with pytest.raises(BlobProviderError):
        provider.resolve()


def test_concurrent_initializing_health_checks_never_start_a_second_initializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    calls = 0
    calls_lock = Lock()

    def blocked_initializer() -> ReleaseReadiness:
        nonlocal calls
        with calls_lock:
            calls += 1
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    configure_provider_lifespan(monkeypatch, blocked_initializer)

    with TestClient(app) as client:
        try:
            assert started.wait(timeout=1)
            with ThreadPoolExecutor(max_workers=8) as executor:
                responses = tuple(executor.map(lambda _index: client.get("/health"), range(24)))
            assert all(response.status_code == 503 for response in responses)
            assert all(response.json() == {"status": "initializing"} for response in responses)
            assert calls == 1
        finally:
            release.set()


def test_cancelled_cold_request_returns_fixed_503_and_shutdown_leaks_no_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    initialization = api_server._ProviderInitialization()

    def blocked_initializer() -> ReleaseReadiness:
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    monkeypatch.setattr(api_server, "_public_runtime_configuration", provider_configuration())
    monkeypatch.setattr(api_server, "_provider_initialization", initialization)

    async def scenario() -> None:
        initialization.start(blocked_initializer)
        assert await asyncio.to_thread(started.wait, 1)
        request = Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "https",
                "path": "/",
                "root_path": "",
                "query_string": b"",
                "headers": [],
                "client": ("test", 1),
                "server": ("testserver", 443),
            }
        )

        async def forbidden_call_next(_request):
            raise AssertionError("cancelled cold request must not reach the application")

        pending = asyncio.create_task(
            api_server._provider_readiness_middleware(request, forbidden_call_next)
        )
        await asyncio.sleep(0)
        pending.cancel()
        response = await pending

        assert response.status_code == 503
        assert response.body == (
            b'{"error":"service_unavailable","detail":"Ground Ball is not ready."}'
        )
        assert initialization.snapshot()[0] == "initializing"

        release.set()
        await initialization.shutdown()
        assert initialization.snapshot() == ("ready", readiness())
        current = asyncio.current_task()
        assert all(task is current or task.done() for task in asyncio.all_tasks())

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_local_ci_release_startup_remains_synchronous_and_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = RuntimeConfiguration(
        scope="local_ci",
        provider_deployment=False,
        public_mode=True,
        network_policy="none",
        admission_adapter="local_ci_ephemeral",
        release_bundle="ground-ball-release-bundle",
        resource_references=(),
        startup_credential_references=(),
        request_credential_headers=(),
        secret_references=(),
    )
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", "/private/local-ci/bundle")
    monkeypatch.setattr(api_server, "_public_runtime_configuration", configuration)
    monkeypatch.setattr(api_server, "_configure_release_runtime_if_declared", lambda: None)
    monkeypatch.setattr(api_server, "_configure_public_admission_if_declared", lambda: None)
    monkeypatch.setattr(
        api_server,
        "_provider_runtime_initializer",
        lambda: pytest.fail("local CI must not use provider background initialization"),
    )

    def fail_closed() -> ReleaseReadiness:
        raise RuntimeError("deterministic local readiness failure")

    monkeypatch.setattr("baseball_rag.release_runtime.release_readiness", fail_closed)

    with pytest.raises(RuntimeError, match="deterministic local readiness failure"):
        with TestClient(app):
            pass
