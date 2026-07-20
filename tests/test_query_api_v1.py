"""FastAPI Adapter for the clean Query Recipe and Query Run contracts."""

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from fastapi.testclient import TestClient

import baseball_rag.api.server as api_server
from baseball_rag.api.server import app
from baseball_rag.public_admission import (
    AdmissionState,
    CasCoordinator,
    CasStore,
    InMemoryCasStore,
    MonthlyBudget,
    RunLease,
    visitor_digest,
)
from baseball_rag.public_admission_blob import BlobProviderError, OidcBlobCredentialProvider
from baseball_rag.public_execution import (
    ExecutionOutcome,
    ExecutionRequest,
    SubprocessExecutionRunner,
)
from baseball_rag.public_results import compact_json_bytes

client = TestClient(app)
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
STARTUP_OIDC = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzdGFydHVwIn0.startup-signature"
REQUEST_OIDC = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJyZXF1ZXN0In0.request-signature"


class RecordingRunner:
    def __init__(self, outcome: ExecutionOutcome) -> None:
        self.outcome = outcome
        self.requests: list[ExecutionRequest] = []

    def run(
        self,
        request: ExecutionRequest,
        *,
        timeout_seconds: float,
    ) -> ExecutionOutcome:
        assert 0 < timeout_seconds <= 10
        self.requests.append(request)
        return self.outcome


class SharedMemoryStore:
    """Shared-store contract double; not production authority."""

    def __init__(self, state: AdmissionState) -> None:
        self.inner = InMemoryCasStore(state)

    @property
    def deployment_shared(self) -> bool:
        return True

    def read(self) -> tuple[AdmissionState, int]:
        return self.inner.read()

    def compare_and_swap(self, version: int, state: AdmissionState) -> bool:
        return self.inner.compare_and_swap(version, state)


def configure_public_proof(
    monkeypatch: pytest.MonkeyPatch,
    *,
    budget: int = 0,
    state: AdmissionState | None = None,
    runner: RecordingRunner | None = None,
) -> tuple[InMemoryCasStore, RecordingRunner]:
    store = InMemoryCasStore(
        state
        or AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=budget))
    )
    configured_runner = runner or RecordingRunner(
        ExecutionOutcome("completed", payload={"kind": "rows", "rows": []})
    )
    monkeypatch.setattr(
        api_server,
        "_public_admission",
        CasCoordinator(store, clock=lambda: NOW),
    )
    monkeypatch.setattr(api_server, "_visitor_digest_key", b"test-visitor-digest-key" * 2)
    monkeypatch.setattr(api_server, "_public_admission_is_shared", True)
    monkeypatch.setattr(api_server, "_public_execution_runner", configured_runner)
    monkeypatch.setattr(api_server, "_public_demo_enabled", lambda: True)
    monkeypatch.setattr(api_server, "_require_consistent_release_configuration", lambda: None)
    return store, configured_runner


def test_query_run_endpoint_accepts_natural_language_and_structured_recipe():
    natural = client.post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
    )
    assert natural.status_code == 200
    natural_payload = natural.json()
    assert natural_payload["kind"] == "rows"
    assert natural_payload["rows"] == [
        {"player.name": "Tommy Davis", "season": 1962, "batting.RBI": 153}
    ]

    structured = client.post(
        "/api/query-runs",
        json={"recipe": natural_payload["recipe"]},
    )
    assert structured.status_code == 200
    assert structured.json()["plan"] == natural_payload["plan"]


def test_local_api_accepts_recipe_only_context_for_natural_follow_ups():
    first = client.post(
        "/api/query-runs",
        json={"question": "how many RBIs did Shohei Ohtani have in 2022"},
    )
    assert first.status_code == 200

    follow_up = client.post(
        "/api/query-runs",
        json={
            "question": "what about his home runs in 2022?",
            "previous_recipe": first.json()["recipe"],
        },
    )

    assert follow_up.status_code == 200
    assert follow_up.json()["recipe"]["selections"] == [
        "player.name",
        "season",
        "batting.HR",
    ]
    invalid = client.post(
        "/api/query-runs",
        json={
            "recipe": first.json()["recipe"],
            "previous_recipe": first.json()["recipe"],
        },
    )
    assert invalid.status_code == 422


def test_query_run_request_requires_exactly_one_clean_input():
    assert client.post("/api/query-runs", json={}).status_code == 422
    assert (
        client.post(
            "/api/query-runs",
            json={"question": "40-40", "recipe": {"source": "Batting"}},
        ).status_code
        == 422
    )
    malformed = client.post(
        "/api/query-runs",
        json={
            "recipe": {
                "source": "Batting",
                "selections": ["Batting.GIDP"],
                "sql": "DROP TABLE batting",
            }
        },
    )
    assert malformed.status_code == 422
    assert "Unknown Query Recipe fields" in malformed.json()["detail"]

    nested = client.post(
        "/api/query-runs",
        json={
            "recipe": {
                "source": "Batting",
                "selections": ["Batting.playerID"],
                "predicate": {
                    "kind": "compare",
                    "value": "Batting.playerID",
                    "operator": "equals",
                    "literal": "aaronha01",
                    "sql": "DROP TABLE batting",
                },
            }
        },
    )
    assert nested.status_code == 422
    assert "Unknown Query Recipe predicate fields" in nested.json()["detail"]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_query_run_rejects_non_finite_recipe_literals(literal: str):
    response = client.post(
        "/api/query-runs",
        content=(
            '{"recipe":{"source":"Batting","grain":"player-season",'
            '"selections":["batting.AVG"],"predicate":{"kind":"compare",'
            f'"value":"batting.AVG","operator":"greater_than","literal":{literal}'
            "}}}"
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert "finite" in response.json()["detail"].lower()


def test_catalog_endpoint_discovers_raw_gidp_and_old_query_routes_are_absent():
    response = client.get("/api/query-catalog", params={"source": "Batting", "search": "GIDP"})

    assert response.status_code == 200
    assert [field["identity"] for field in response.json()["fields"]] == ["Batting.GIDP"]
    assert client.post("/query", json={"question": "40-40"}).status_code == 405
    assert client.post("/api/query", json={"question": "40-40"}).status_code == 405


def test_coverage_report_has_machine_and_dark_human_representations():
    machine = client.get("/api/query-coverage")
    human = client.get("/coverage-report")

    assert machine.status_code == 200
    assert machine.json()["status"] == "passing"
    assert machine.json()["summary"] == {"covered": 5253, "total": 5253, "uncovered": 0}
    assert human.status_code == 200
    assert "Verified for this data release" in human.text
    assert "color-scheme:dark" in human.text


def test_coverage_routes_reject_stale_or_tampered_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from baseball_rag.query.coverage import CoverageProofUnavailableError

    def reject_stale_report():
        raise CoverageProofUnavailableError("Coverage Report proof hash is invalid.")

    monkeypatch.setattr(
        "baseball_rag.query.coverage.load_passing_coverage_report",
        reject_stale_report,
    )

    machine = client.get("/api/query-coverage")
    human = client.get("/coverage-report")

    assert machine.status_code == 503
    assert human.status_code == 503
    assert "proof hash is invalid" in machine.json()["detail"]


def test_capabilities_publish_the_new_composition_root_only():
    payload = client.get("/api/capabilities").json()

    assert payload["query"] == {
        "endpoint": "/api/query-runs",
        "catalog_endpoint": "/api/query-catalog",
        "coverage_endpoint": "/api/query-coverage",
        "coverage_report": "/coverage-report",
        "natural_language": True,
        "structured_recipe": True,
    }
    assert payload["llm_required"] is False
    assert payload["retrosheet_endpoint"] == "/api/retrosheet/queries"
    assert {item["capability_id"] for item in payload["retrosheet_capabilities"]} == {
        "pitcher_strikeout_side",
        "batting_stat_streak",
        "pitcher_daily_strikeout_game_log",
        "player_batting_game_log",
    }


def test_public_mode_fails_closed_when_release_bundle_is_missing(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.delenv("GROUNDBALL_RELEASE_BUNDLE", raising=False)

    capabilities_response = client.get("/api/capabilities")
    query_response = client.post(
        "/api/retrosheet/queries",
        json={"question": "how many times did Nolan Ryan strike out the side in his career"},
    )

    assert capabilities_response.status_code == 503
    assert query_response.status_code == 503


def test_retrosheet_queries_remain_separate_and_never_fallback_from_primary_questions():
    response = client.post(
        "/api/retrosheet/queries",
        json={"question": "how many times did Nolan Ryan strike out the side in his career"},
    )

    assert response.status_code == 200
    assert response.json()["capability"] == "retrosheet"
    assert response.json()["rows"][0]["career_strikeout_side_count"] == 324
    assert (
        "retrosheet_pitcher_strikeout_side_events"
        in response.json()["evidence"]["parameterized_sql"]
    )
    assert (
        client.post(
            "/api/retrosheet/queries",
            json={"question": "who had the most RBIs in 1962"},
        ).status_code
        == 422
    )


def test_public_query_run_is_admitted_once_and_releases_only_its_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner(
        ExecutionOutcome(
            "completed",
            payload={"kind": "rows", "rows": [{"batting.RBI": 153}]},
        )
    )
    store, _ = configure_public_proof(monkeypatch, runner=runner)

    response = TestClient(app, base_url="https://testserver").post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
    )

    assert response.status_code == 200
    assert runner.requests == [
        ExecutionRequest(
            operation="query",
            question="who had the most RBIs in 1962",
            recipe=None,
        )
    ]
    cookie = response.headers["set-cookie"]
    assert "groundball_visitor=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    state, _ = store.read()
    assert state.running == ()
    assert state.monthly_budget.charged_starts == 1
    token = response.cookies["groundball_visitor"]
    assert [item[0] for item in state.starts_by_visitor] == [
        visitor_digest(token, digest_key=b"test-visitor-digest-key" * 2)
    ]


def test_public_api_runs_the_real_result_policy_in_the_hard_stop_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_public_proof(monkeypatch)
    monkeypatch.setattr(api_server, "_public_execution_runner", SubprocessExecutionRunner())
    public_client = TestClient(app)

    page = public_client.post("/api/query-runs", json={"question": "40-40"})
    invalid = public_client.post(
        "/api/query-runs",
        json={
            "recipe": {
                "source": "Batting",
                "grain": "raw_rows",
                "selections": ["Batting.playerID"],
                "output": {"kind": "interactive_page", "size": 101, "offset": 0},
            }
        },
    )
    refused_export = public_client.post(
        "/api/query-runs",
        json={
            "recipe": {
                "source": "TeamReference",
                "grain": "raw_rows",
                "selections": ["TeamReference.name"],
                "output": {"kind": "export", "format": "json"},
            }
        },
    )

    assert page.status_code == 200
    assert page.json()["pagination"] == {"size": 25, "offset": 0, "has_more": False}
    assert invalid.status_code == 422
    assert "25, 50, or 100" in invalid.json()["detail"]
    assert refused_export.status_code == 422
    assert refused_export.json()["error"] == "export_too_large"
    assert "rows" not in refused_export.json()
    assert "export" not in refused_export.json()


def test_public_api_two_turn_follow_up_runs_in_the_same_isolated_child_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_public_proof(monkeypatch)
    monkeypatch.setattr(api_server, "_public_execution_runner", SubprocessExecutionRunner())
    public_client = TestClient(app)

    first = public_client.post(
        "/api/query-runs",
        json={"question": "how many RBIs did Shohei Ohtani have in 2022"},
    )
    follow_up = public_client.post(
        "/api/query-runs",
        json={
            "question": "what about his home runs in 2022?",
            "previous_recipe": first.json()["recipe"],
        },
    )

    assert first.status_code == 200
    assert first.json()["rows"] == [
        {"player.name": "Shohei Ohtani", "season": 2022, "batting.RBI": 95}
    ]
    assert follow_up.status_code == 200
    assert follow_up.json()["rows"] == [
        {"player.name": "Shohei Ohtani", "season": 2022, "batting.HR": 34}
    ]
    assert follow_up.json()["verification"]["status"] == "verified"


def test_public_export_refusal_is_structured_422_compact_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refusal = {
        "kind": "export_too_large",
        "error": "export_too_large",
        "total_matched_count": 3_001,
        "ceiling": {"name": "matched_rows", "maximum": 3_000, "observed": 3_001},
        "detail": "The complete export exceeds the public matched rows ceiling.",
        "guidance": "Add filters to narrow the result, then export again.",
    }
    configure_public_proof(
        monkeypatch,
        runner=RecordingRunner(ExecutionOutcome("completed", payload=refusal)),
    )

    response = TestClient(app).post(
        "/api/query-runs",
        json={"recipe": {"source": "TeamReference", "selections": ["TeamReference.name"]}},
    )

    assert response.status_code == 422
    assert response.content == compact_json_bytes(refusal)
    assert response.json() == refusal


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"x-vercel-oidc-token": "not-a-jwt"},
        {"x-vercel-oidc-token": "a.b." + "x" * 8191},
    ],
)
def test_public_request_oidc_missing_malformed_or_oversized_fails_before_execution_and_resets(
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
) -> None:
    provider = OidcBlobCredentialProvider()
    inner = InMemoryCasStore(
        AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))
    )

    class CredentialCheckingStore:
        deployment_shared = True

        def read(self):
            provider.resolve()
            return inner.read()

        def compare_and_swap(self, version: int, state: AdmissionState) -> bool:
            provider.resolve()
            return inner.compare_and_swap(version, state)

    runner = RecordingRunner(ExecutionOutcome("completed", payload={"kind": "rows", "rows": []}))
    monkeypatch.setattr(
        api_server,
        "_public_admission",
        CasCoordinator(cast(CasStore, CredentialCheckingStore()), clock=lambda: NOW),
    )
    monkeypatch.setattr(api_server, "_visitor_digest_key", b"test-visitor-digest-key" * 2)
    monkeypatch.setattr(api_server, "_public_admission_is_shared", True)
    monkeypatch.setattr(api_server, "_public_execution_runner", runner)
    monkeypatch.setattr(api_server, "_public_demo_enabled", lambda: True)
    monkeypatch.setattr(api_server, "_require_consistent_release_configuration", lambda: None)

    refused = TestClient(app).post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
        headers=headers,
    )

    assert refused.status_code == 503
    assert refused.json() == {
        "error": "provider_unavailable",
        "reason": "coordination_store_unavailable",
        "detail": "Ground Ball's public admission service is unavailable.",
        "retry_at": None,
    }
    assert runner.requests == []
    with pytest.raises(BlobProviderError):
        provider.resolve()
    assert STARTUP_OIDC not in refused.text
    assert all(value not in refused.text for value in headers.values())

    admitted = TestClient(app).post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
        headers={"x-vercel-oidc-token": REQUEST_OIDC},
    )
    assert admitted.status_code == 200
    assert len(runner.requests) == 1
    with pytest.raises(BlobProviderError):
        provider.resolve()


def test_public_allowance_pause_never_enters_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, runner = configure_public_proof(monkeypatch, budget=100)

    response = TestClient(app, base_url="https://testserver").post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "error": "allowance_paused",
        "reason": "monthly_start_budget_exhausted",
        "detail": (
            "Ground Ball's monthly public Query Run allowance is paused. "
            "Retry at 2026-08-01T00:00:00+00:00."
        ),
        "retry_at": "2026-08-01T00:00:00+00:00",
    }
    assert response.headers["retry-after"] == "1080000"
    assert "groundball_visitor=" in response.headers["set-cookie"]
    assert runner.requests == []
    state, _ = store.read()
    assert state.monthly_budget.charged_starts == 100


def test_public_request_body_boundary_and_early_cors_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_public_proof(monkeypatch)
    exact = b'{"question":"x"}' + b" " * (16_384 - len(b'{"question":"x"}'))
    headers = {
        "content-type": "application/json",
        "origin": "https://discostew.dev",
    }

    accepted = TestClient(app).post("/api/query-runs", content=exact, headers=headers)
    refused = TestClient(app).post(
        "/api/query-runs",
        content=exact + b" ",
        headers=headers,
    )
    malformed = TestClient(app).post(
        "/api/query-runs",
        content=b"{" + b"x" * 16_384,
        headers=headers,
    )

    assert accepted.status_code == 200
    assert refused.status_code == 413
    assert malformed.status_code == 413
    assert refused.json() == {
        "error": "request_too_large",
        "detail": "Public Query Run requests may not exceed 16384 bytes.",
    }
    assert refused.headers["access-control-allow-origin"] == "https://discostew.dev"
    assert refused.headers["access-control-allow-credentials"] == "true"


def test_natural_language_question_has_an_exact_500_character_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, runner = configure_public_proof(monkeypatch)

    accepted = TestClient(app).post("/api/query-runs", json={"question": "x" * 500})
    refused = TestClient(app).post("/api/query-runs", json={"question": "x" * 501})

    assert accepted.status_code == 200
    assert refused.status_code == 422
    assert len(runner.requests) == 1


def test_public_retrosheet_route_uses_the_same_admission_and_execution_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, runner = configure_public_proof(monkeypatch)

    response = TestClient(app, base_url="https://testserver").post(
        "/api/retrosheet/queries",
        json={"question": "how many times did Nolan Ryan strike out the side"},
    )

    assert response.status_code == 200
    assert runner.requests[0].operation == "retrosheet"
    state, _ = store.read()
    assert state.running == ()
    assert state.monthly_budget.charged_starts == 1


def test_public_query_run_success_exposes_safe_phase_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_public_proof(monkeypatch)
    ticks = iter((50.0, 50.1, 50.2, 50.3, 52.8, 52.9, 53.1, 53.2))
    monkeypatch.setattr(api_server, "_monotonic", lambda: next(ticks), raising=False)

    response = TestClient(app).post("/api/query-runs", json={"question": "question"})

    assert response.status_code == 200
    assert response.json() == {"kind": "rows", "rows": []}
    assert response.headers["server-timing"] == (
        "admission;dur=100.000, execution;dur=2500.000, release;dur=200.000, total;dur=3100.000"
    )


def test_timing_failure_does_not_change_response_or_skip_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _runner = configure_public_proof(monkeypatch)
    ticks = iter((80.0, 80.1, 80.2, 80.3, 80.4, RuntimeError("clock failed"), 80.6, 80.7))

    def monotonic() -> float:
        tick = next(ticks)
        if isinstance(tick, Exception):
            raise tick
        return tick

    monkeypatch.setattr(api_server, "_monotonic", monotonic, raising=False)

    response = TestClient(app).post("/api/query-runs", json={"question": "question"})

    assert response.status_code == 200
    assert response.json() == {"kind": "rows", "rows": []}
    assert "release" not in response.headers["server-timing"]
    state, _version = store.read()
    assert state.running == ()


def test_public_timing_omits_nonfinite_and_negative_phase_durations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _runner = configure_public_proof(monkeypatch)
    ticks = iter((90.0, 90.1, 90.0, 90.2, float("inf"), float("nan"), 90.4, 90.5))
    monkeypatch.setattr(api_server, "_monotonic", lambda: next(ticks), raising=False)

    response = TestClient(app).post("/api/query-runs", json={"question": "question"})

    assert response.status_code == 200
    assert response.headers["server-timing"] == "total;dur=400.000"
    state, _version = store.read()
    assert state.running == ()


def test_public_admission_refusal_exposes_only_measured_phase_timing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_public_proof(monkeypatch, budget=100)
    ticks = iter((70.0, 70.1, 70.6, 70.7))
    monkeypatch.setattr(api_server, "_monotonic", lambda: next(ticks), raising=False)

    response = TestClient(app).post("/api/query-runs", json={"question": "question"})

    assert response.status_code == 503
    assert response.json()["reason"] == "monthly_start_budget_exhausted"
    assert response.headers["server-timing"] == ("admission;dur=500.000, total;dur=600.000")
    assert "execution" not in response.headers["server-timing"]
    assert "release" not in response.headers["server-timing"]


def test_public_busy_and_rate_refusals_expose_exact_retry_times(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "existing-opaque-token"
    digest_key = b"test-visitor-digest-key" * 2
    visitor = visitor_digest(token, digest_key=digest_key)
    runner = RecordingRunner(ExecutionOutcome("completed", payload={"kind": "rows"}))
    busy_state = AdmissionState(
        running=(
            RunLease(
                visitor=visitor,
                run_id="active",
                expires_at=NOW + timedelta(seconds=15),
            ),
        ),
        monthly_budget=MonthlyBudget(period="2026-07", charged_starts=1),
    )
    configure_public_proof(monkeypatch, state=busy_state, runner=runner)

    public_client = TestClient(app, base_url="https://testserver")
    public_client.cookies.set("groundball_visitor", token)
    busy = public_client.post(
        "/api/query-runs",
        json={"question": "question"},
    )

    assert busy.status_code == 429
    assert busy.json()["reason"] == "visitor_run_active"
    assert busy.json()["retry_at"] == "2026-07-19T12:00:15+00:00"
    assert busy.headers["retry-after"] == "15"
    assert runner.requests == []

    rate_state = AdmissionState(
        starts_by_visitor=(
            (
                visitor,
                (
                    NOW - timedelta(seconds=50),
                    NOW - timedelta(seconds=30),
                    NOW - timedelta(seconds=10),
                ),
            ),
        ),
        monthly_budget=MonthlyBudget(period="2026-07", charged_starts=3),
    )
    configure_public_proof(monkeypatch, state=rate_state, runner=runner)
    limited = public_client.post(
        "/api/query-runs",
        json={"question": "question"},
    )

    assert limited.status_code == 429
    assert limited.json()["reason"] == "three_starts_per_minute"
    assert limited.json()["retry_at"] == "2026-07-19T12:00:10+00:00"
    assert limited.headers["retry-after"] == "10"


def test_public_malformed_budget_and_store_failure_have_distinct_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    malformed = AdmissionState(
        monthly_budget=cast(
            MonthlyBudget,
            {"period": "2026-07", "charged_starts": 0},
        )
    )
    configure_public_proof(monkeypatch, state=malformed)

    allowance = TestClient(app).post("/api/query-runs", json={"question": "question"})

    assert allowance.status_code == 503
    assert allowance.json()["error"] == "allowance_paused"
    assert allowance.json()["reason"] == "monthly_budget_invalid"

    class UnavailableStore:
        def read(self):
            raise OSError("sensitive internal provider detail")

        def compare_and_swap(self, version: int, state: AdmissionState) -> bool:
            raise AssertionError("unreachable")

    monkeypatch.setattr(
        api_server,
        "_public_admission",
        CasCoordinator(cast(CasStore, UnavailableStore()), clock=lambda: NOW),
    )
    unavailable = TestClient(app).post("/api/query-runs", json={"question": "question"})

    assert unavailable.status_code == 503
    assert unavailable.json()["error"] == "provider_unavailable"
    assert unavailable.json()["reason"] == "coordination_store_unavailable"
    assert "sensitive" not in unavailable.text


def test_public_timeout_is_honest_and_never_refunds_the_charged_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner(ExecutionOutcome("timed_out"))
    store, _ = configure_public_proof(monkeypatch, runner=runner)

    response = TestClient(app).post("/api/query-runs", json={"question": "slow question"})

    assert response.status_code == 503
    assert response.json() == {
        "error": "timed_out",
        "detail": (
            "The Query Run reached its 10-second deadline and was stopped. "
            "Narrow the question before trying again."
        ),
    }
    state, _ = store.read()
    assert state.running == ()
    assert state.monthly_budget.charged_starts == 1


def test_public_execution_failure_releases_lease_but_keeps_charge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner(
        ExecutionOutcome("failed", detail="Public Query Run execution failed.")
    )
    store, _ = configure_public_proof(monkeypatch, runner=runner)

    response = TestClient(app).post("/api/query-runs", json={"question": "failing question"})

    assert response.status_code == 503
    assert response.json()["error"] == "provider_unavailable"
    state, _ = store.read()
    assert state.running == ()
    assert state.monthly_budget.charged_starts == 1


def test_public_configuration_rejects_process_local_store_and_unstable_key() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))

    with pytest.raises(ValueError, match="shared"):
        api_server.configure_public_admission(
            store=InMemoryCasStore(state),
            digest_key=b"x" * 32,
        )
    with pytest.raises(ValueError, match="32 bytes"):
        api_server.configure_public_admission(
            store=SharedMemoryStore(state),
            digest_key=b"short",
        )


def test_public_startup_fails_closed_without_shared_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", "/proof/bundle")
    monkeypatch.setattr("baseball_rag.release_runtime.release_readiness", lambda: object())
    monkeypatch.setattr(api_server, "_public_admission", None)
    monkeypatch.setattr(api_server, "_visitor_digest_key", None)
    monkeypatch.setattr(api_server, "_public_admission_is_shared", False)

    with pytest.raises(RuntimeError, match="shared public admission"):
        with TestClient(app):
            pass


def test_public_startup_fails_closed_for_invalid_current_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", "/proof/bundle")
    monkeypatch.setattr("baseball_rag.release_runtime.release_readiness", lambda: object())
    store = SharedMemoryStore(
        AdmissionState(monthly_budget=MonthlyBudget(period="2026-08", charged_starts=0))
    )
    coordinator = api_server.configure_public_admission(
        store=store,
        digest_key=b"stable-key" * 4,
        clock=lambda: NOW,
    )
    assert coordinator.readiness().kind == "allowance_paused"

    with pytest.raises(RuntimeError, match="budget"):
        with TestClient(app):
            pass
