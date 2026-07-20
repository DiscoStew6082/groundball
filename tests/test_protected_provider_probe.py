from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from baseball_rag.protected_provider_probe import (
    ProbeResponse,
    ProtectedProbeError,
    build_lifecycle_evidence,
    run_protected_http_probe,
    run_security_route_probe,
)
from baseball_rag.protected_provider_proof import EVIDENCE_SCHEMAS, ProviderProofError
from baseball_rag.public_release_config import canonical_json_bytes

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "1" * 40
ARTIFACT = "2" * 40
BUNDLE = "3" * 64
RUNTIME = "4" * 64
POLICY = "5" * 64
IMAGE = "sha256:" + "6" * 64
DEPLOYMENT = "dpl_9XW9KmE2rqe4XWZ7YBbmetEQLgab"
REPLACEMENT_DEPLOYMENT = "dpl_A6LMSbEbfgRQqSJ7RS4TfKKgv7ke"
ORIGIN = "https://groundball-wave7.vercel.app"


def _identity() -> dict[str, object]:
    return {
        "admission_policy_digest": POLICY,
        "artifact_commit": ARTIFACT,
        "bundle_digest": BUNDLE,
        "deployment_id": DEPLOYMENT,
        "provider_image_digest": IMAGE,
        "runtime_configuration_digest": RUNTIME,
        "source_commit": SOURCE,
    }


class AdvancingClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        self.value += 0.125
        return self.value


class FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.readiness_count = 0

    def request(self, **kwargs: Any) -> ProbeResponse:
        self.calls.append(kwargs)
        path = kwargs["path"]
        if path == "/api/release-readiness":
            self.readiness_count += 1
            body = {
                "hosting": {"runtime_instance_id": f"{self.readiness_count:032x}"},
                "release_bundle_digest": BUNDLE,
                "runtime_configuration": {
                    "digest": RUNTIME,
                    "provider_deployment": True,
                    "scope": "protected_preview",
                },
                "source_commit": SOURCE,
            }
            return ProbeResponse(200, canonical_json_bytes(body))
        if path == "/api/capabilities":
            return ProbeResponse(
                200,
                canonical_json_bytes(
                    {
                        "mode": "public",
                        "retrosheet_capabilities": [{"capability_id": "pitcher_strikeout_side"}],
                    }
                ),
            )
        if path in {"/api/architecture", "/api/generate", "/api/query"}:
            return ProbeResponse(404, canonical_json_bytes({"detail": "Not found."}))
        case = kwargs["workload_case"]
        if case == "tommy_davis_natural":
            body = {
                "kind": "rows",
                "rows": [{"batting.RBI": 153, "player.name": "Tommy Davis", "season": 1962}],
            }
            return ProbeResponse(200, canonical_json_bytes(body))
        if case in {"ohtani_natural", "ohtani_structured"}:
            body = {
                "kind": "rows",
                "rows": [
                    {
                        "batting.HR": 34,
                        "pitching.W": 15,
                        "player.name": "Shohei Ohtani",
                        "season": 2022,
                    }
                ],
            }
            return ProbeResponse(200, canonical_json_bytes(body))
        if case == "ohtani_first_turn":
            return ProbeResponse(
                200,
                canonical_json_bytes(
                    {
                        "kind": "rows",
                        "recipe": {"grain": "player-season", "source": "Batting"},
                        "rows": [{"batting.RBI": 95}],
                    }
                ),
            )
        if case == "ohtani_follow_up":
            return ProbeResponse(
                200, canonical_json_bytes({"kind": "rows", "rows": [{"batting.HR": 34}]})
            )
        if case in {"complete_json_export", "complete_csv_export"}:
            return ProbeResponse(
                200, canonical_json_bytes({"kind": "exported", "export": "complete"})
            )
        if case.startswith("retrosheet_") and case != "retrosheet_unbundled_refusal":
            return ProbeResponse(
                200, canonical_json_bytes({"kind": "rows", "rows": [{"count": 1}]})
            )
        expected = next(
            item
            for item in json.loads((ROOT / "release/proof/warm-workloads-v1.json").read_text())[
                "workloads"
            ]
            if item["corpus_case_id"] == case
        )
        status = expected["expected_http_status"]
        outcome = expected["expected_outcome"]
        return ProbeResponse(status, canonical_json_bytes({"kind": outcome}))


def test_http_probe_requires_exact_https_origin_and_documented_idle_period() -> None:
    with pytest.raises(ProtectedProbeError):
        run_protected_http_probe(
            _identity(),
            "http://example.com",
            30,
            transport=FakeTransport(),
            monotonic=AdvancingClock(),
            sleep=lambda _seconds: None,
        )
    with pytest.raises(ProtectedProbeError):
        run_protected_http_probe(
            _identity(),
            ORIGIN + "/path",
            30,
            transport=FakeTransport(),
            monotonic=AdvancingClock(),
            sleep=lambda _seconds: None,
        )
    with pytest.raises(ProtectedProbeError):
        run_protected_http_probe(
            _identity(),
            ORIGIN,
            29,
            transport=FakeTransport(),
            monotonic=AdvancingClock(),
            sleep=lambda _seconds: None,
        )


def test_http_probe_records_all_samples_without_retries_and_never_serializes_bypass_secret() -> (
    None
):
    transport = FakeTransport()
    sleeps: list[float] = []
    bypass = "synthetic-bypass-material"

    result = run_protected_http_probe(
        _identity(),
        ORIGIN,
        30,
        transport=transport,
        monotonic=AdvancingClock(),
        sleep=sleeps.append,
        bypass_secret=bypass,
    )

    assert result["cold_wakes"]["schema_version"] == EVIDENCE_SCHEMAS["cold_wakes"]
    assert len(result["cold_wakes"]["observation"]["samples"]) == 5
    assert result["warm_results"]["schema_version"] == EVIDENCE_SCHEMAS["warm_results"]
    assert len(result["warm_results"]["observation"]["results"]) == 20
    assert sleeps == [30.0] * 5
    assert len(transport.calls) == 3 + 5 * 3 + 20
    assert bypass.encode() not in canonical_json_bytes(result)
    assert all(call["origin"] == ORIGIN for call in transport.calls)
    assert all(
        set(call["headers"]) <= {"Content-Type", "x-vercel-protection-bypass"}
        for call in transport.calls
    )


def test_lifecycle_helper_binds_deployments_and_runtime_instance_transitions() -> None:
    from datetime import UTC, datetime

    evidence = build_lifecycle_evidence(
        _identity(),
        replacement_deployment_id=REPLACEMENT_DEPLOYMENT,
        runtime_instance_transitions=[
            "instance-a:instance-b",
            "instance-b:instance-c",
        ],
        restart_observed=True,
        scale_to_zero_provider_reported=True,
        state_persisted=True,
        observed_at=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )

    assert evidence["status"] == "pass"
    assert evidence["observation"]["initial_deployment_id"] == DEPLOYMENT
    assert evidence["observation"]["replacement_deployment_id"] == REPLACEMENT_DEPLOYMENT


def test_security_probe_rejects_malformed_deployment_identity_before_transport() -> None:
    transport = FakeTransport()
    identity = _identity()
    identity["deployment_id"] = DEPLOYMENT + "/"

    with pytest.raises(ProviderProofError, match="identity is invalid"):
        run_security_route_probe(
            identity,
            ORIGIN,
            transport=transport,
            provider_coordination_destinations=["https://vercel.com"],
            egress_provider_reported=True,
        )

    assert transport.calls == []


def test_security_probe_checks_only_fixed_origin_routes_before_body_processing() -> None:
    from datetime import UTC, datetime

    transport = FakeTransport()
    evidence = run_security_route_probe(
        _identity(),
        ORIGIN,
        transport=transport,
        provider_coordination_destinations=["https://vercel.com"],
        egress_provider_reported=True,
        utc_now=lambda: datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    )

    assert evidence["status"] == "pass"
    assert evidence["observation"]["forbidden_routes_before_body"] == {
        "/api/architecture": 404,
        "/api/generate": 404,
        "/api/query": 404,
    }
    security_calls = transport.calls[-3:]
    assert [call["path"] for call in security_calls] == [
        "/api/architecture",
        "/api/generate",
        "/api/query",
    ]
    assert all(len(call["payload"]) > 16_384 for call in security_calls)


def test_http_probe_has_no_hidden_retry_or_discarded_warm_sample() -> None:
    transport = FakeTransport()
    original = transport.request
    failed = False

    def one_failure(**kwargs: Any) -> ProbeResponse:
        nonlocal failed
        if kwargs["workload_case"] == "page_50" and not failed:
            failed = True
            return ProbeResponse(503, canonical_json_bytes({"kind": "provider_unavailable"}))
        return original(**kwargs)

    transport.request = one_failure  # type: ignore[method-assign]
    result = run_protected_http_probe(
        _identity(),
        ORIGIN,
        30,
        transport=transport,
        monotonic=AdvancingClock(),
        sleep=lambda _seconds: None,
    )

    samples = result["warm_results"]["observation"]["results"]
    assert len(samples) == 20
    failed_sample = next(item for item in samples if item["workload_id"] == "warm-07-page-50")
    assert failed_sample["outcome"] == "fail"
    assert result["warm_results"]["status"] == "fail"
