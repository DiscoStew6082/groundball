"""Provider startup admission state machine contracts."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest
from fastapi.testclient import TestClient

import baseball_rag.api.server as api_server
from baseball_rag.api.server import app
from baseball_rag.public_admission_blob import OidcBlobCredentialProvider
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
        startup_credential_references=("VERCEL_OIDC_TOKEN",),
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
        response = client.get("/health")
        assert startup_seconds < 1
        assert response.status_code == 503
        assert response.json() == {"status": "initializing"}


def test_every_non_health_public_surface_is_fixed_503_before_provider_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()

    def blocked_initializer() -> ReleaseReadiness:
        started.set()
        assert release.wait(timeout=30)
        return readiness()

    configure_provider_lifespan(monkeypatch, blocked_initializer)

    class ForbiddenRunner:
        def run(self, *_args, **_kwargs):
            raise AssertionError("query execution started before readiness")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("admission or public data access started before readiness")

    monkeypatch.setattr(api_server, "_public_execution_runner", ForbiddenRunner())
    monkeypatch.setattr(api_server, "_shared_public_admission_components", forbidden)
    monkeypatch.setattr(api_server, "_web_dist_path", forbidden)
    monkeypatch.setattr("baseball_rag.query.adapters.catalog_payload", forbidden)
    monkeypatch.setattr("baseball_rag.query.coverage.load_passing_coverage_report", forbidden)

    expected = {
        "error": "service_unavailable",
        "detail": "Ground Ball is not ready.",
    }
    requests = (
        ("POST", "/health", None),
        ("GET", "/", None),
        ("GET", "/api/capabilities", None),
        ("GET", "/api/query-catalog", None),
        ("GET", "/api/query-coverage", None),
        ("GET", "/coverage-report", None),
        ("GET", "/api/release-readiness", None),
        ("POST", "/api/query-runs", {"question": "who had the most RBIs in 1962"}),
        (
            "POST",
            "/api/query-runs",
            {
                "recipe": {
                    "source": "TeamReference",
                    "grain": "raw_rows",
                    "selections": ["TeamReference.name"],
                    "output": {"kind": "export", "format": "json"},
                }
            },
        ),
        ("POST", "/api/retrosheet/queries", {"question": "any question"}),
    )

    with TestClient(app) as client:
        try:
            assert started.wait(timeout=1)
            for method, path, body in requests:
                response = client.request(method, path, json=body)
                assert response.status_code == 503, path
                assert response.json() == expected, path
        finally:
            release.set()


def test_provider_background_initialization_uses_startup_oidc_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_oidc = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzdGFydHVwIn0.startup-signature"
    provider = OidcBlobCredentialProvider(startup_token=startup_oidc)
    observed: list[str] = []

    def initializer() -> ReleaseReadiness:
        observed.append(provider.resolve())
        return readiness()

    configure_provider_lifespan(monkeypatch, initializer)

    with TestClient(app) as client:
        for _ in range(100):
            response = client.get("/health")
            if response.status_code == 200:
                break
            time.sleep(0.01)

    assert response.status_code == 200
    assert observed == [startup_oidc]


def test_provider_initialization_transitions_once_to_ready_and_caches_exact_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_readiness = readiness()
    calls = {"heavy": 0, "admission": 0}
    calls_lock = Lock()

    def heavy_readiness() -> ReleaseReadiness:
        with calls_lock:
            calls["heavy"] += 1
        return expected_readiness

    def admission_readiness():
        with calls_lock:
            calls["admission"] += 1
        return object(), b"x" * 32

    configure_provider_lifespan(monkeypatch, api_server._provider_runtime_initializer)
    monkeypatch.setattr("baseball_rag.release_runtime.release_readiness", heavy_readiness)
    monkeypatch.setattr(api_server, "_require_shared_public_admission", admission_readiness)

    with TestClient(app) as client:
        for _ in range(100):
            health = client.get("/health")
            if health.status_code == 200:
                break
            time.sleep(0.01)
        assert health.status_code == 200
        assert health.json() == {"status": "ok"}

        first = client.get("/api/release-readiness")
        second = client.get("/api/release-readiness")

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["release_bundle_digest"] == "a" * 64
    assert second.json() == first.json()
    assert calls == {"heavy": 1, "admission": 3}


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


def test_provider_initialization_failure_is_permanent_fixed_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    secret = "super-secret-token /private/release/bundle"

    def failing_initializer() -> ReleaseReadiness:
        nonlocal calls
        calls += 1
        raise RuntimeError(secret)

    configure_provider_lifespan(monkeypatch, failing_initializer)

    with TestClient(app) as client:
        for _ in range(100):
            health = client.get("/health")
            if health.json() == {"status": "failed"}:
                break
            time.sleep(0.01)
        public_response = client.get("/api/release-readiness")
        repeated_health = tuple(client.get("/health") for _ in range(10))

    assert health.status_code == 503
    assert health.json() == {"status": "failed"}
    assert public_response.status_code == 503
    assert public_response.json() == {
        "error": "service_unavailable",
        "detail": "Ground Ball is not ready.",
    }
    rendered = public_response.text + health.text + "".join(item.text for item in repeated_health)
    assert secret not in rendered
    assert "token" not in rendered
    assert "/private" not in rendered
    assert calls == 1
    assert all(item.status_code == 503 for item in repeated_health)


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
