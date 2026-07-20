from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from baseball_rag.protected_provider_proof import (
    BROWSER_MANIFEST_SCHEMA,
    EVIDENCE_SCHEMAS,
    WARM_MANIFEST_SCHEMA,
    ProviderProofError,
    derive_provider_gate_report,
    load_browser_manifest,
    load_warm_manifest,
    validate_provider_evidence,
)
from baseball_rag.public_release_config import canonical_json_bytes
from baseball_rag.release_candidate import (
    PROVIDER_OBSERVATION_IDS,
    REQUIRED_GATE_IDS,
    CandidateError,
    EvidenceInput,
    build_candidate_identity,
    build_provider_attestation,
    validate_deployment_attestation,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "1" * 40
ARTIFACT = "2" * 40
BUNDLE = "3" * 64
RUNTIME = "4" * 64
POLICY = "5" * 64
IMAGE = "sha256:" + "6" * 64
DEPLOYMENT = "dpl_wave7proof"
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


def _document(schema: str) -> dict[str, object]:
    warm = load_warm_manifest(ROOT / "release/proof/warm-workloads-v1.json")
    browser = load_browser_manifest(ROOT / "release/proof/browser-scenarios-v1.json")
    base: dict[str, object] = {
        "identity": _identity(),
        "observed_at": "2026-07-20T12:00:00Z",
        "schema_version": schema,
        "status": "pass",
    }
    if schema == EVIDENCE_SCHEMAS["deployment_metadata"]:
        observation = {
            "deployment_id": DEPLOYMENT,
            "exact_source_bundle_topology": True,
            "offline_container_security_valid": True,
            "parity_public_envelope_valid": True,
            "preview_origin": ORIGIN,
            "provider": "vercel",
            "provider_deployment": True,
            "public_mode": True,
            "release_bundle_coverage_valid": True,
            "runtime_scope": "protected_preview",
        }
    elif schema == EVIDENCE_SCHEMAS["provider_image"]:
        observation = {
            "digest": IMAGE,
            "measurement_kind": "provider-oci-manifest-size-bytes",
            "mutable_tag": None,
            "size_bytes": 900_000_000,
        }
    elif schema == EVIDENCE_SCHEMAS["blob_admission"]:
        checks = {
            check: True
            for check in (
                "bounded_contention",
                "conflict",
                "create_if_absent",
                "current_partial_month_initialization",
                "etag_conditional_write",
                "expired_lease",
                "fifth_deployment_busy",
                "future_state_fail_closed",
                "hour_limit",
                "malformed_state_fail_closed",
                "minute_limit",
                "nonrefund_after_interruption",
                "older_period_utc_rollover",
                "private_uncached_read",
                "rejected_attempts_uncharged",
                "same_visitor_busy",
                "state_codec",
                "unavailable_store",
                "unused_rollover_forbidden",
                "hundredth_admit_101st_refusal",
            )
        }
        observation = {
            "application_operation_counts": {"attempted_reads": 25, "attempted_writes": 20},
            "checks": checks,
            "namespace": "proof",
            "provider_accounting_observation_id": "provider-accounting",
            "request_bytes": 1234,
            "response_bytes": 4321,
        }
    elif schema == EVIDENCE_SCHEMAS["cold_wakes"]:
        observation = {
            "idle_period_seconds": 30,
            "samples": [
                {
                    "first_query_elapsed_ms": 9000 - index,
                    "full_body": True,
                    "runtime_instance_id": f"instance-cold-{index}",
                    "sample_id": f"cold-{index:02d}",
                    "shell_capabilities_elapsed_ms": 4000 - index,
                    "status": "pass",
                }
                for index in range(1, 6)
            ],
        }
    elif schema == EVIDENCE_SCHEMAS["warm_results"]:
        observation = {
            "manifest_digest": hashlib.sha256(canonical_json_bytes(warm)).hexdigest(),
            "results": [
                {
                    "elapsed_ms": 2500,
                    "fingerprint": f"{index:064x}",
                    "full_body": True,
                    "http_status": 200,
                    "outcome": "pass",
                    "workload_id": item["workload_id"],
                }
                for index, item in enumerate(warm["workloads"], start=1)
            ],
        }
    elif schema == EVIDENCE_SCHEMAS["peak_memory"]:
        base["status"] = "blocked"
        observation = {
            "deployment_filterable": True,
            "measurement_kind": "vercel.function_invocation.peak_memory_mb",
            "observability_plus_available": False,
            "observability_plus_required": True,
            "peak_memory_mb": None,
            "plan": "hobby",
            "provisioned_limit_mb": 2048,
            "reason": "provider_metric_unavailable_on_hobby",
        }
    elif schema == EVIDENCE_SCHEMAS["lifecycle"]:
        observation = {
            "initial_deployment_id": DEPLOYMENT,
            "replacement_deployment_id": "dpl_wave7replacement",
            "restart_observed": True,
            "runtime_instance_transitions": ["instance-a:instance-b", "instance-b:instance-c"],
            "scale_to_zero_provider_reported": True,
            "state_persisted": True,
        }
    elif schema == EVIDENCE_SCHEMAS["network_security"]:
        observation = {
            "browser_network_destinations": [ORIGIN],
            "egress_provider_reported": True,
            "forbidden_routes_before_body": {
                "/api/architecture": 404,
                "/api/generate": 404,
                "/api/query": 404,
            },
            "provider_coordination_destinations": ["https://vercel.com"],
            "public_route_inventory_valid": True,
            "secret_exposure_detected": False,
            "unexpected_egress_destinations": [],
        }
    elif schema == EVIDENCE_SCHEMAS["browser"]:
        observation = {
            "console_errors": [],
            "manifest_digest": hashlib.sha256(canonical_json_bytes(browser)).hexdigest(),
            "network_destinations": [ORIGIN],
            "pixels_observed": True,
            "responsive": True,
            "scenario_ids": [item["scenario_id"] for item in browser["scenarios"]],
            "viewports": [
                {"height": 800, "kind": "desktop", "width": 1280},
                {"height": 800, "kind": "mobile", "width": 360},
                {"height": 844, "kind": "mobile", "width": 390},
                {"height": 932, "kind": "mobile", "width": 430},
            ],
        }
    elif schema == EVIDENCE_SCHEMAS["provider_accounting"]:
        observation = {
            "application_counts_reconciled": True,
            "billing_limit_fit": True,
            "provider_measurement_kind": "vercel-blob-usage-observation",
            "provider_reported": True,
            "read_operations": 25,
            "request_bytes": 1234,
            "response_bytes": 4321,
            "write_operations": 20,
        }
    else:  # pragma: no cover - protects fixture drift
        raise AssertionError(schema)
    return {**base, "observation": observation}


def _candidate(tmp_path: Path, documents: list[dict[str, object]]) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    evidence = []
    for index, document in enumerate(documents):
        path = tmp_path / f"evidence-{index}.json"
        path.write_bytes(canonical_json_bytes(document))
        evidence.append(
            EvidenceInput(
                logical_id=f"provider-evidence-{index:02d}",
                path=path,
                media_type="application/json",
                schema_identity=str(document["schema_version"]),
            )
        )
    return build_candidate_identity(
        scope="protected_preview",
        source_commit=SOURCE,
        artifact_commit=ARTIFACT,
        artifact_parent_commit=SOURCE,
        artifact_changed_paths=("release/bundle/release-manifest.json",),
        bundle_digest=BUNDLE,
        image_digest=IMAGE,
        image_size_bytes=900_000_000,
        image_size_measurement_kind="provider-oci-manifest-size-bytes",
        runtime_configuration_digest=RUNTIME,
        admission_policy_digest=POLICY,
        evidence_inputs=tuple(evidence),
    )


def _all_documents() -> list[dict[str, object]]:
    return [_document(schema) for schema in EVIDENCE_SCHEMAS.values()]


def _measured_memory_document(*, peak_memory_mb: int | float = 1400) -> dict[str, object]:
    document = _document(EVIDENCE_SCHEMAS["peak_memory"])
    document["status"] = "pass"
    document["observation"] = {
        "deployment_filterable": True,
        "measurement_kind": "vercel.function_invocation.peak_memory_mb",
        "observability_plus_available": True,
        "observability_plus_required": True,
        "peak_memory_mb": peak_memory_mb,
        "plan": "pro",
        "provisioned_limit_mb": 2048,
        "reason": None,
    }
    return document


def _replace_memory(
    documents: list[dict[str, object]], memory: dict[str, object]
) -> list[dict[str, object]]:
    documents[list(EVIDENCE_SCHEMAS).index("peak_memory")] = memory
    return documents


def _observation_map() -> dict[str, str]:
    return {
        observation_id: f"provider-evidence-{list(EVIDENCE_SCHEMAS).index(kind):02d}"
        for observation_id, kind in {
            "cold_wakes": "cold_wakes",
            "deployment_metadata_configuration": "deployment_metadata",
            "network_security_public_routes": "network_security",
            "peak_memory": "peak_memory",
            "protected_blob_coordination": "blob_admission",
            "protected_browser_desktop_mobile": "browser",
            "provider_image_measurement": "provider_image",
            "provider_operation_accounting": "provider_accounting",
            "restart_replacement_scale_to_zero": "lifecycle",
            "warm_manifest": "warm_results",
        }.items()
    }


def test_fixed_manifests_are_canonical_complete_and_immutable_in_shape() -> None:
    warm = load_warm_manifest(ROOT / "release/proof/warm-workloads-v1.json")
    browser = load_browser_manifest(ROOT / "release/proof/browser-scenarios-v1.json")

    assert warm["schema_version"] == WARM_MANIFEST_SCHEMA
    assert len(warm["workloads"]) == 20
    assert len({item["workload_id"] for item in warm["workloads"]}) == 20
    categories = {item["category"] for item in warm["workloads"]}
    assert {
        "tommy",
        "ohtani",
        "paging",
        "csv_export",
        "json_export",
        "retrosheet",
        "refusal",
        "public_boundary",
    } <= categories
    assert browser["schema_version"] == BROWSER_MANIFEST_SCHEMA
    assert len(browser["scenarios"]) == len({item["scenario_id"] for item in browser["scenarios"]})
    assert {360, 390, 430} <= set(browser["mobile_widths"])


def test_provider_evidence_rejects_duplicate_keys_unknown_fields_secrets_paths_and_nonfinite() -> (
    None
):
    document = _document(EVIDENCE_SCHEMAS["provider_image"])
    assert validate_provider_evidence(canonical_json_bytes(document)) == document

    duplicate = canonical_json_bytes(document).replace(
        b'{"identity"', b'{"status":"pass","identity"'
    )
    with pytest.raises(ProviderProofError):
        validate_provider_evidence(duplicate)

    for mutation in (
        lambda value: value.update({"extra": True}),
        lambda value: value["observation"].update({"token": "synthetic"}),
        lambda value: value["observation"].update({"report_path": "/tmp/provider.json"}),
        lambda value: value["observation"].update({"size_bytes": True}),
        lambda value: value["observation"].update({"size_bytes": float("nan")}),
    ):
        changed = copy.deepcopy(document)
        mutation(changed)
        with pytest.raises((ProviderProofError, ValueError)):
            validate_provider_evidence(canonical_json_bytes(changed))


@pytest.mark.parametrize("plan", ["pro", "enterprise"])
def test_measured_provider_memory_within_limit_passes_gate(tmp_path: Path, plan: str) -> None:
    memory = _measured_memory_document()
    memory["observation"]["plan"] = plan  # type: ignore[index]
    documents = _replace_memory(_all_documents(), memory)
    candidate = _candidate(tmp_path, documents)
    evidence = {
        f"provider-evidence-{index:02d}": canonical_json_bytes(document)
        for index, document in enumerate(documents)
    }

    report = derive_provider_gate_report(candidate, evidence)

    assert report["eligible"] is True
    assert all(gate["status"] == "pass" for gate in report["gates"])
    attestation = build_provider_attestation(
        candidate,
        report,
        provider_name="vercel",
        deployment_id=DEPLOYMENT,
        image_digest=IMAGE,
        image_size_bytes=900_000_000,
        image_size_measurement_kind="provider-oci-manifest-size-bytes",
        observation_to_evidence=_observation_map(),
    )
    assert (
        validate_deployment_attestation(canonical_json_bytes(attestation), candidate, report)
        == attestation
    )


@pytest.mark.parametrize("peak_memory_mb", [2048.5, 10**400])
def test_measured_provider_memory_over_declared_limit_fails_gate(
    tmp_path: Path, peak_memory_mb: int | float
) -> None:
    documents = _replace_memory(
        _all_documents(), _measured_memory_document(peak_memory_mb=peak_memory_mb)
    )
    candidate = _candidate(tmp_path, documents)
    evidence = {
        f"provider-evidence-{index:02d}": canonical_json_bytes(document)
        for index, document in enumerate(documents)
    }

    report = derive_provider_gate_report(candidate, evidence)

    assert (
        next(gate for gate in report["gates"] if gate["gate_id"] == "provider_peak_memory")[
            "status"
        ]
        == "fail"
    )
    assert report["eligible"] is False


@pytest.mark.parametrize("hobby_status", ["pass", "fail"])
def test_peak_memory_variants_require_consistent_envelope_status(hobby_status: str) -> None:
    hobby = _document(EVIDENCE_SCHEMAS["peak_memory"])
    hobby["status"] = hobby_status
    measured = _measured_memory_document()
    measured["status"] = "blocked"

    for document in (hobby, measured):
        with pytest.raises(ProviderProofError):
            validate_provider_evidence(canonical_json_bytes(document))

    measured["status"] = "fail"
    assert validate_provider_evidence(canonical_json_bytes(measured)) == measured


def test_peak_memory_rejects_mixed_unknown_boolean_nonfinite_and_unsupported_values() -> None:
    mutations = (
        lambda value: value["observation"].update({"observability_plus_available": False}),
        lambda value: value["observation"].update({"reason": "metric-unavailable"}),
        lambda value: value["observation"].update({"peak_memory_mb": True}),
        lambda value: value["observation"].update({"peak_memory_mb": float("nan")}),
        lambda value: value["observation"].update({"peak_memory_mb": float("inf")}),
        lambda value: value["observation"].update({"provisioned_limit_mb": True}),
        lambda value: value["observation"].update({"provisioned_limit_mb": 0}),
        lambda value: value["observation"].update({"provisioned_limit_mb": 2048.0}),
        lambda value: value["observation"].update({"plan": "team"}),
        lambda value: value["observation"].update({"plan": "Pro"}),
        lambda value: value["observation"].update({"extra": None}),
    )
    for mutation in mutations:
        changed = _measured_memory_document()
        mutation(changed)
        with pytest.raises((ProviderProofError, ValueError)):
            validate_provider_evidence(canonical_json_bytes(changed))


def test_hobby_aggregator_accepts_all_free_evidence_but_blocks_memory_and_attestation(
    tmp_path: Path,
) -> None:
    documents = _all_documents()
    candidate = _candidate(tmp_path, documents)
    evidence = {
        f"provider-evidence-{index:02d}": canonical_json_bytes(document)
        for index, document in enumerate(documents)
    }

    report = derive_provider_gate_report(candidate, evidence)

    assert report["eligible"] is False
    assert [gate["gate_id"] for gate in report["gates"]] == list(REQUIRED_GATE_IDS)
    statuses = {gate["gate_id"]: gate["status"] for gate in report["gates"]}
    assert statuses["provider_peak_memory"] == "blocked"
    assert statuses["provider_deployment_attestation"] == "blocked"
    assert list(statuses.values()).count("pass") == 13
    memory = documents[list(EVIDENCE_SCHEMAS).index("peak_memory")]
    assert memory["observation"]["reason"] == "provider_metric_unavailable_on_hobby"  # type: ignore[index]

    logical_ids = _observation_map()
    assert set(logical_ids) == set(PROVIDER_OBSERVATION_IDS)
    with pytest.raises(CandidateError, match="all-pass"):
        build_provider_attestation(
            candidate,
            report,
            provider_name="vercel",
            deployment_id=DEPLOYMENT,
            image_digest=IMAGE,
            image_size_bytes=900_000_000,
            image_size_measurement_kind="provider-oci-manifest-size-bytes",
            observation_to_evidence=logical_ids,
        )


def test_aggregator_blocks_missing_observation_and_fails_foreign_or_over_limit_evidence(
    tmp_path: Path,
) -> None:
    documents = _all_documents()
    candidate = _candidate(tmp_path, documents)
    evidence = {
        f"provider-evidence-{index:02d}": canonical_json_bytes(document)
        for index, document in enumerate(documents)
    }
    memory_index = list(EVIDENCE_SCHEMAS).index("peak_memory")
    evidence.pop(f"provider-evidence-{memory_index:02d}")
    blocked = derive_provider_gate_report(candidate, evidence)
    assert (
        next(g for g in blocked["gates"] if g["gate_id"] == "provider_peak_memory")["status"]
        == "blocked"
    )
    assert blocked["eligible"] is False

    foreign = _all_documents()
    foreign[memory_index]["identity"]["deployment_id"] = "dpl_foreign"  # type: ignore[index]
    foreign_candidate = _candidate(tmp_path / "foreign", foreign)
    foreign_evidence = {
        f"provider-evidence-{index:02d}": canonical_json_bytes(document)
        for index, document in enumerate(foreign)
    }
    failed = derive_provider_gate_report(foreign_candidate, foreign_evidence)
    assert (
        next(g for g in failed["gates"] if g["gate_id"] == "provider_peak_memory")["status"]
        == "fail"
    )
    assert failed["eligible"] is False

    contradictory = _all_documents()
    contradictory[memory_index]["observation"]["peak_memory_mb"] = 1400  # type: ignore[index]
    contradictory_candidate = _candidate(tmp_path / "contradictory", contradictory)
    contradictory_evidence = {
        f"provider-evidence-{index:02d}": canonical_json_bytes(document)
        for index, document in enumerate(contradictory)
    }
    contradictory_report = derive_provider_gate_report(
        contradictory_candidate, contradictory_evidence
    )
    assert (
        next(
            gate
            for gate in contradictory_report["gates"]
            if gate["gate_id"] == "provider_peak_memory"
        )["status"]
        == "fail"
    )

    wrong_origin = _all_documents()
    browser_index = list(EVIDENCE_SCHEMAS).index("browser")
    wrong_origin[browser_index]["observation"]["network_destinations"] = [
        "https://foreign-preview.vercel.app"
    ]  # type: ignore[index]
    wrong_origin_candidate = _candidate(tmp_path / "wrong-origin", wrong_origin)
    wrong_origin_evidence = {
        f"provider-evidence-{index:02d}": canonical_json_bytes(document)
        for index, document in enumerate(wrong_origin)
    }
    wrong_origin_report = derive_provider_gate_report(wrong_origin_candidate, wrong_origin_evidence)
    assert (
        next(
            gate
            for gate in wrong_origin_report["gates"]
            if gate["gate_id"] == "protected_browser_desktop_mobile"
        )["status"]
        == "fail"
    )
