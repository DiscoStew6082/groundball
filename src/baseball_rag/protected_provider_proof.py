"""Strict, secret-free protected-provider evidence and gate derivation."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from baseball_rag.public_release_config import canonical_json_bytes
from baseball_rag.release_candidate import (
    MAX_CANDIDATE_IMAGE_SIZE_BYTES,
    CandidateError,
    build_gate_report,
    validate_candidate_identity,
)

WARM_MANIFEST_SCHEMA = "ground-ball-warm-workload-manifest-v1"
BROWSER_MANIFEST_SCHEMA = "ground-ball-browser-proof-manifest-v1"
EVIDENCE_SCHEMAS = {
    "deployment_metadata": "ground-ball-provider-deployment-metadata-v1",
    "provider_image": "ground-ball-provider-image-measurement-v1",
    "blob_admission": "ground-ball-protected-blob-admission-proof-v1",
    "cold_wakes": "ground-ball-provider-cold-wakes-v1",
    "warm_results": "ground-ball-provider-warm-results-v1",
    "peak_memory": "ground-ball-provider-peak-memory-v1",
    "lifecycle": "ground-ball-provider-lifecycle-proof-v1",
    "network_security": "ground-ball-provider-network-security-proof-v1",
    "browser": "ground-ball-protected-browser-proof-v1",
    "provider_accounting": "ground-ball-provider-operation-accounting-v1",
}
WARM_MANIFEST_PATH = Path("release/proof/warm-workloads-v1.json")
BROWSER_MANIFEST_PATH = Path("release/proof/browser-scenarios-v1.json")
MAX_PROVIDER_PEAK_MEMORY_BYTES = 1_500_000_000
_REQUIRED_IDENTITY_FIELDS = {
    "admission_policy_digest",
    "artifact_commit",
    "bundle_digest",
    "deployment_id",
    "provider_image_digest",
    "runtime_configuration_digest",
    "source_commit",
}
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANONICAL_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_UTC_SECONDS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class ProviderProofError(ValueError):
    """Protected-provider material is malformed, unsafe, or mismatched."""


class _DuplicateKeyError(ValueError):
    pass


def load_warm_manifest(path: Path | str = WARM_MANIFEST_PATH) -> dict[str, object]:
    document = _load_canonical_object(path, "warm workload manifest")
    if set(document) != {"immutable", "schema_version", "workloads"}:
        raise ProviderProofError("Warm workload manifest shape is invalid.")
    if (
        document.get("schema_version") != WARM_MANIFEST_SCHEMA
        or document.get("immutable") is not True
    ):
        raise ProviderProofError("Warm workload manifest identity is invalid.")
    workloads = document.get("workloads")
    if not isinstance(workloads, list) or len(workloads) != 20:
        raise ProviderProofError("Warm workload manifest must contain exactly twenty runs.")
    ids: list[str] = []
    categories: set[str] = set()
    for item in workloads:
        required = {
            "category",
            "corpus_case_id",
            "expected_http_status",
            "expected_outcome",
            "method",
            "path",
            "workload_id",
        }
        if not isinstance(item, dict) or set(item) != required:
            raise ProviderProofError("Warm workload entry shape is invalid.")
        workload_id = item.get("workload_id")
        category = item.get("category")
        status = item.get("expected_http_status")
        if (
            not _canonical_id(workload_id)
            or not _canonical_id(category)
            or not _canonical_id(item.get("corpus_case_id"))
            or item.get("method") not in {"GET", "POST"}
            or item.get("path")
            not in {"/api/capabilities", "/api/query-runs", "/api/retrosheet/queries"}
            or type(status) is not int
            or status not in {200, 413, 422}
            or not _canonical_id(item.get("expected_outcome"))
        ):
            raise ProviderProofError("Warm workload entry value is invalid.")
        ids.append(str(workload_id))
        categories.add(str(category))
    required_categories = {
        "tommy",
        "ohtani",
        "paging",
        "csv_export",
        "json_export",
        "retrosheet",
        "refusal",
        "public_boundary",
    }
    if len(ids) != len(set(ids)) or not required_categories <= categories:
        raise ProviderProofError("Warm workload coverage is incomplete or duplicated.")
    return document


def load_browser_manifest(path: Path | str = BROWSER_MANIFEST_PATH) -> dict[str, object]:
    document = _load_canonical_object(path, "Browser proof manifest")
    if set(document) != {
        "desktop_viewport",
        "immutable",
        "mobile_widths",
        "schema_version",
        "scenarios",
    }:
        raise ProviderProofError("Browser proof manifest shape is invalid.")
    if (
        document.get("schema_version") != BROWSER_MANIFEST_SCHEMA
        or document.get("immutable") is not True
    ):
        raise ProviderProofError("Browser proof manifest identity is invalid.")
    if document.get("desktop_viewport") != {"height": 800, "width": 1280}:
        raise ProviderProofError("Browser desktop viewport is invalid.")
    widths = document.get("mobile_widths")
    if widths != [360, 390, 430]:
        raise ProviderProofError("Browser mobile viewport inventory is invalid.")
    scenarios = document.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ProviderProofError("Browser scenario inventory is invalid.")
    ids: list[str] = []
    for item in scenarios:
        if (
            not isinstance(item, dict)
            or set(item) != {"preserve_last_completed_run", "scenario_id"}
            or type(item.get("preserve_last_completed_run")) is not bool
            or not _canonical_id(item.get("scenario_id"))
        ):
            raise ProviderProofError("Browser scenario entry is invalid.")
        ids.append(str(item["scenario_id"]))
    required = {
        "tommy-davis",
        "ohtani-natural",
        "ohtani-structured",
        "ohtani-follow-up",
        "retrosheet-positive",
        "retrosheet-negative",
        "recipe-editing",
        "pagination-25-50-100",
        "complete-json-export",
        "complete-csv-export",
        "coverage-report-and-provenance",
        "console-errors-and-network-destinations",
        "responsive-layout-and-pixels",
    }
    if len(ids) != len(set(ids)) or not required <= set(ids):
        raise ProviderProofError("Browser scenario coverage is incomplete or duplicated.")
    return document


def validate_provider_evidence(
    payload: bytes | Mapping[str, object],
    *,
    expected_identity: Mapping[str, object] | None = None,
) -> dict[str, object]:
    document = _canonical_document(payload, "provider evidence")
    if set(document) != {"identity", "observation", "observed_at", "schema_version", "status"}:
        raise ProviderProofError("Provider evidence shape is invalid.")
    schema = document.get("schema_version")
    if schema not in EVIDENCE_SCHEMAS.values():
        raise ProviderProofError("Provider evidence schema is unsupported.")
    if document.get("status") not in {"pass", "fail", "blocked"}:
        raise ProviderProofError("Provider evidence status is invalid; warnings are forbidden.")
    _validate_observed_at(document.get("observed_at"))
    identity = document.get("identity")
    _validate_identity(identity)
    if expected_identity is not None and identity != dict(expected_identity):
        raise ProviderProofError("Provider evidence belongs to a foreign identity.")
    observation = document.get("observation")
    if not isinstance(observation, dict):
        raise ProviderProofError("Provider observation must be an object.")
    _validate_observation(str(schema), observation, identity)
    _reject_unsafe_content(document)
    return document


def derive_provider_gate_report(
    candidate: Mapping[str, object], evidence_payloads: Mapping[str, bytes]
) -> dict[str, object]:
    """Derive all fixed gates; provider statuses are never accepted from a caller."""
    checked_candidate = validate_candidate_identity(candidate)
    if checked_candidate["scope"] not in {"protected_preview", "production"}:
        raise ProviderProofError("Provider gate derivation requires a provider candidate scope.")
    raw_candidate_evidence = checked_candidate.get("evidence")
    if not isinstance(raw_candidate_evidence, list):  # validated above; keeps typing explicit
        raise ProviderProofError("Candidate evidence is invalid.")
    entries = {
        item["logical_id"]: item
        for item in raw_candidate_evidence
        if isinstance(item, dict) and isinstance(item.get("logical_id"), str)
    }
    by_kind: dict[str, tuple[str, dict[str, object]] | None] = {
        kind: None for kind in EVIDENCE_SCHEMAS
    }
    invalid_kinds: set[str] = set()
    for logical_id, entry in entries.items():
        schema = entry.get("schema_identity")
        kind = next((name for name, value in EVIDENCE_SCHEMAS.items() if value == schema), None)
        if kind is None:
            continue
        payload = evidence_payloads.get(logical_id)
        if payload is None:
            continue
        if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
            invalid_kinds.add(kind)
            continue
        try:
            checked = validate_provider_evidence(payload)
        except ProviderProofError:
            invalid_kinds.add(kind)
            continue
        if by_kind[kind] is not None:
            invalid_kinds.add(kind)
            continue
        by_kind[kind] = (logical_id, checked)

    metadata_pair = by_kind["deployment_metadata"]
    expected_identity: dict[str, object] | None = None
    if metadata_pair is not None and "deployment_metadata" not in invalid_kinds:
        raw_identity = metadata_pair[1].get("identity")
        if isinstance(raw_identity, dict):
            expected_identity = dict(raw_identity)
        else:  # validated evidence cannot reach this branch
            invalid_kinds.add("deployment_metadata")
    candidate_identity = {
        "admission_policy_digest": checked_candidate["admission_policy_digest"],
        "artifact_commit": checked_candidate["artifact_commit"],
        "bundle_digest": checked_candidate["bundle_digest"],
        "provider_image_digest": checked_candidate["image_digest"],
        "runtime_configuration_digest": checked_candidate["runtime_configuration_digest"],
        "source_commit": checked_candidate["source_commit"],
    }
    if expected_identity is not None and any(
        expected_identity.get(key) != value for key, value in candidate_identity.items()
    ):
        invalid_kinds.add("deployment_metadata")
    if expected_identity is not None:
        for kind, pair in by_kind.items():
            if pair is not None and pair[1].get("identity") != expected_identity:
                invalid_kinds.add(kind)
    preview_origin: object = None
    if metadata_pair is not None:
        metadata_observation = metadata_pair[1].get("observation")
        if isinstance(metadata_observation, dict):
            preview_origin = metadata_observation.get("preview_origin")
    security_pair = by_kind["network_security"]
    if security_pair is not None:
        security_observation = security_pair[1].get("observation")
        if not isinstance(security_observation, dict) or security_observation.get(
            "browser_network_destinations"
        ) != [preview_origin]:
            invalid_kinds.add("network_security")
    browser_pair = by_kind["browser"]
    if browser_pair is not None:
        browser_observation = browser_pair[1].get("observation")
        if not isinstance(browser_observation, dict) or browser_observation.get(
            "network_destinations"
        ) != [preview_origin]:
            invalid_kinds.add("browser")

    def outcome(kind: str) -> tuple[str, list[str]]:
        pair = by_kind[kind]
        if kind in invalid_kinds:
            return "fail", [] if pair is None else [pair[0]]
        if pair is None:
            return "blocked", []
        status = str(pair[1]["status"])
        if status != "pass":
            return status, [pair[0]]
        if not _observation_passes(kind, pair[1]["observation"], checked_candidate):
            return "fail", [pair[0]]
        return "pass", [pair[0]]

    kinds = {kind: outcome(kind) for kind in EVIDENCE_SCHEMAS}
    metadata_status, metadata_refs = kinds["deployment_metadata"]
    image_status, image_refs = kinds["provider_image"]

    def combine(*selected: str) -> tuple[str, list[str]]:
        values = [kinds[item] for item in selected]
        refs = sorted({ref for _status, item_refs in values for ref in item_refs})
        if any(status == "fail" for status, _refs in values):
            return "fail", refs
        if any(status == "blocked" for status, _refs in values):
            return "blocked", refs
        return "pass", refs

    derived = {
        "candidate_identity_topology": (metadata_status, metadata_refs),
        "release_bundle_coverage": (metadata_status, metadata_refs),
        "deterministic_parity_public_envelope": (metadata_status, metadata_refs),
        "offline_container_security": combine("deployment_metadata", "network_security"),
        "local_image_size": (image_status, image_refs),
        "runtime_admission_configuration": (metadata_status, metadata_refs),
        "protected_blob_coordination": kinds["blob_admission"],
        "protected_deployment_image": combine("deployment_metadata", "provider_image"),
        "cold_wake_warm_performance": combine("cold_wakes", "warm_results"),
        "provider_peak_memory": kinds["peak_memory"],
        "restart_replacement_scale_to_zero": kinds["lifecycle"],
        "network_egress_public_routes": kinds["network_security"],
        "protected_browser_desktop_mobile": kinds["browser"],
        "provider_operation_accounting": kinds["provider_accounting"],
        "provider_deployment_attestation": combine(*EVIDENCE_SCHEMAS.keys()),
    }
    results = {
        gate_id: {"status": status, "evidence": refs} for gate_id, (status, refs) in derived.items()
    }
    try:
        return build_gate_report(checked_candidate, results)
    except CandidateError as exc:  # pragma: no cover - invariant protection
        raise ProviderProofError(str(exc)) from exc


def _validate_observation(schema: str, value: dict[str, object], identity: object) -> None:
    assert isinstance(identity, dict)
    kind = next(name for name, item in EVIDENCE_SCHEMAS.items() if item == schema)
    validators = {
        "deployment_metadata": _validate_metadata,
        "provider_image": _validate_image,
        "blob_admission": _validate_blob,
        "cold_wakes": _validate_cold,
        "warm_results": _validate_warm,
        "peak_memory": _validate_memory,
        "lifecycle": _validate_lifecycle,
        "network_security": _validate_security,
        "browser": _validate_browser,
        "provider_accounting": _validate_accounting,
    }
    validators[kind](value, identity)


def _validate_metadata(value: dict[str, object], identity: dict[str, object]) -> None:
    _exact(
        value,
        {
            "deployment_id",
            "exact_source_bundle_topology",
            "offline_container_security_valid",
            "parity_public_envelope_valid",
            "preview_origin",
            "provider",
            "provider_deployment",
            "public_mode",
            "release_bundle_coverage_valid",
            "runtime_scope",
        },
    )
    if (
        value.get("deployment_id") != identity["deployment_id"]
        or value.get("provider") != "vercel"
        or value.get("runtime_scope") not in {"protected_preview", "production"}
        or not _https_origin(value.get("preview_origin"))
        or any(
            type(value.get(key)) is not bool
            for key in (
                "exact_source_bundle_topology",
                "offline_container_security_valid",
                "parity_public_envelope_valid",
                "provider_deployment",
                "public_mode",
                "release_bundle_coverage_valid",
            )
        )
    ):
        raise ProviderProofError("Deployment metadata observation is invalid.")


def _validate_image(value: dict[str, object], identity: dict[str, object]) -> None:
    _exact(value, {"digest", "measurement_kind", "mutable_tag", "size_bytes"})
    if (
        value.get("digest") != identity["provider_image_digest"]
        or value.get("measurement_kind") != "provider-oci-manifest-size-bytes"
        or value.get("mutable_tag") is not None
        or not _integer(value.get("size_bytes"), minimum=0)
    ):
        raise ProviderProofError("Provider image observation is invalid.")


def _validate_blob(value: dict[str, object], _identity: dict[str, object]) -> None:
    _exact(
        value,
        {
            "application_operation_counts",
            "checks",
            "namespace",
            "provider_accounting_observation_id",
            "request_bytes",
            "response_bytes",
        },
    )
    required_checks = {
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
    }
    checks = value.get("checks")
    counts = value.get("application_operation_counts")
    if (
        value.get("namespace") != "proof"
        or not isinstance(checks, dict)
        or set(checks) != required_checks
        or any(type(item) is not bool for item in checks.values())
        or not isinstance(counts, dict)
        or not counts
        or any(not _integer(item, minimum=0) for item in counts.values())
        or not _nullable_integer(value.get("request_bytes"))
        or not _nullable_integer(value.get("response_bytes"))
        or (
            value.get("provider_accounting_observation_id") is not None
            and not _canonical_id(value.get("provider_accounting_observation_id"))
        )
    ):
        raise ProviderProofError("Protected Blob observation is invalid.")


def _validate_cold(value: dict[str, object], _identity: dict[str, object]) -> None:
    _exact(value, {"idle_period_seconds", "samples"})
    samples = value.get("samples")
    if (
        not _integer(value.get("idle_period_seconds"), minimum=30)
        or not isinstance(samples, list)
        or len(samples) != 5
    ):
        raise ProviderProofError("Cold-wake observation is invalid.")
    sample_ids: list[str] = []
    instances: list[str] = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ProviderProofError("Cold-wake sample is invalid.")
        _exact(
            sample,
            {
                "first_query_elapsed_ms",
                "full_body",
                "runtime_instance_id",
                "sample_id",
                "shell_capabilities_elapsed_ms",
                "status",
            },
        )
        if (
            not _integer(sample.get("first_query_elapsed_ms"), minimum=0)
            or type(sample.get("full_body")) is not bool
            or not _canonical_id(sample.get("runtime_instance_id"))
            or not _canonical_id(sample.get("sample_id"))
            or not _integer(sample.get("shell_capabilities_elapsed_ms"), minimum=0)
            or sample.get("status") not in {"pass", "fail"}
        ):
            raise ProviderProofError("Cold-wake sample is invalid.")
        sample_ids.append(str(sample["sample_id"]))
        instances.append(str(sample["runtime_instance_id"]))
    if sample_ids != [f"cold-{index:02d}" for index in range(1, 6)] or len(instances) != len(
        set(instances)
    ):
        raise ProviderProofError("Cold-wake samples are duplicated or substituted.")


def _validate_warm(value: dict[str, object], _identity: dict[str, object]) -> None:
    _exact(value, {"manifest_digest", "results"})
    manifest = load_warm_manifest()
    expected_digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    results = value.get("results")
    if (
        value.get("manifest_digest") != expected_digest
        or not isinstance(results, list)
        or len(results) != 20
    ):
        raise ProviderProofError("Warm result manifest binding is invalid.")
    manifest_workloads = manifest.get("workloads")
    assert isinstance(manifest_workloads, list)
    expected_ids = [item["workload_id"] for item in manifest_workloads if isinstance(item, dict)]
    observed_ids: list[object] = []
    for item in results:
        if not isinstance(item, dict):
            raise ProviderProofError("Warm result sample is invalid.")
        _exact(
            item,
            {"elapsed_ms", "fingerprint", "full_body", "http_status", "outcome", "workload_id"},
        )
        if (
            not _integer(item.get("elapsed_ms"), minimum=0)
            or not _is_sha256(item.get("fingerprint"))
            or type(item.get("full_body")) is not bool
            or not _integer(item.get("http_status"), minimum=100)
            or item.get("outcome") not in {"pass", "fail"}
            or not _canonical_id(item.get("workload_id"))
        ):
            raise ProviderProofError("Warm result sample is invalid.")
        observed_ids.append(item["workload_id"])
    if observed_ids != expected_ids:
        raise ProviderProofError("Warm results contain missing, extra, or substituted workloads.")


def _validate_memory(value: dict[str, object], _identity: dict[str, object]) -> None:
    _exact(
        value,
        {
            "deployment_filterable",
            "measurement_kind",
            "observability_plus_available",
            "observability_plus_required",
            "peak_memory_mb",
            "plan",
            "provisioned_limit_mb",
            "reason",
        },
    )
    if (
        value.get("measurement_kind") != "vercel.function_invocation.peak_memory_mb"
        or value.get("deployment_filterable") is not True
        or value.get("observability_plus_required") is not True
        or value.get("observability_plus_available") is not False
        or value.get("peak_memory_mb") is not None
        or value.get("plan") != "hobby"
        or value.get("provisioned_limit_mb") != 2048
        or value.get("reason") != "provider_metric_unavailable_on_hobby"
    ):
        raise ProviderProofError("Provider memory observation is invalid.")


def _validate_lifecycle(value: dict[str, object], identity: dict[str, object]) -> None:
    _exact(
        value,
        {
            "initial_deployment_id",
            "replacement_deployment_id",
            "restart_observed",
            "runtime_instance_transitions",
            "scale_to_zero_provider_reported",
            "state_persisted",
        },
    )
    transitions = value.get("runtime_instance_transitions")
    if (
        value.get("initial_deployment_id") != identity["deployment_id"]
        or not _canonical_id(value.get("replacement_deployment_id"))
        or any(
            type(value.get(key)) is not bool
            for key in ("restart_observed", "scale_to_zero_provider_reported", "state_persisted")
        )
        or not isinstance(transitions, list)
        or len(transitions) < 2
        or len(transitions) != len(set(transitions))
        or not all(
            isinstance(item, str) and re.fullmatch(r"[a-z0-9._-]+:[a-z0-9._-]+", item)
            for item in transitions
        )
    ):
        raise ProviderProofError("Provider lifecycle observation is invalid.")


def _validate_security(value: dict[str, object], _identity: dict[str, object]) -> None:
    _exact(
        value,
        {
            "browser_network_destinations",
            "egress_provider_reported",
            "forbidden_routes_before_body",
            "provider_coordination_destinations",
            "public_route_inventory_valid",
            "secret_exposure_detected",
            "unexpected_egress_destinations",
        },
    )
    forbidden = value.get("forbidden_routes_before_body")
    coordination = value.get("provider_coordination_destinations")
    if (
        type(value.get("egress_provider_reported")) is not bool
        or type(value.get("public_route_inventory_valid")) is not bool
        or type(value.get("secret_exposure_detected")) is not bool
        or not isinstance(forbidden, dict)
        or not forbidden
        or any(
            not isinstance(path, str) or not path.startswith("/") or status not in {404, 405}
            for path, status in forbidden.items()
        )
        or not _origin_list(value.get("browser_network_destinations"))
        or not isinstance(coordination, list)
        or not coordination
        or not all(_provider_coordination_origin(item) for item in coordination)
        or value.get("unexpected_egress_destinations") != []
    ):
        raise ProviderProofError("Network/security observation is invalid.")


def _validate_browser(value: dict[str, object], _identity: dict[str, object]) -> None:
    _exact(
        value,
        {
            "console_errors",
            "manifest_digest",
            "network_destinations",
            "pixels_observed",
            "responsive",
            "scenario_ids",
            "viewports",
        },
    )
    manifest = load_browser_manifest()
    expected_digest = hashlib.sha256(canonical_json_bytes(manifest)).hexdigest()
    manifest_scenarios = manifest.get("scenarios")
    assert isinstance(manifest_scenarios, list)
    expected_ids = [item["scenario_id"] for item in manifest_scenarios if isinstance(item, dict)]
    viewports = value.get("viewports")
    if (
        value.get("manifest_digest") != expected_digest
        or value.get("scenario_ids") != expected_ids
        or value.get("console_errors") != []
        or not _origin_list(value.get("network_destinations"))
        or type(value.get("pixels_observed")) is not bool
        or type(value.get("responsive")) is not bool
        or not isinstance(viewports, list)
    ):
        raise ProviderProofError("Protected Browser observation is invalid.")
    observed: set[tuple[str, int, int]] = set()
    for viewport in viewports:
        if not isinstance(viewport, dict) or set(viewport) != {"height", "kind", "width"}:
            raise ProviderProofError("Browser viewport evidence is invalid.")
        if (
            viewport.get("kind") not in {"desktop", "mobile"}
            or not _integer(viewport.get("width"), minimum=1)
            or not _integer(viewport.get("height"), minimum=1)
        ):
            raise ProviderProofError("Browser viewport evidence is invalid.")
        observed.add((str(viewport["kind"]), int(viewport["width"]), int(viewport["height"])))
    if not any(kind == "desktop" for kind, _width, _height in observed) or not {360, 390, 430} <= {
        width for kind, width, _height in observed if kind == "mobile"
    }:
        raise ProviderProofError("Browser viewport coverage is incomplete.")


def _validate_accounting(value: dict[str, object], _identity: dict[str, object]) -> None:
    _exact(
        value,
        {
            "application_counts_reconciled",
            "billing_limit_fit",
            "provider_measurement_kind",
            "provider_reported",
            "read_operations",
            "request_bytes",
            "response_bytes",
            "write_operations",
        },
    )
    if (
        value.get("provider_measurement_kind") != "vercel-blob-usage-observation"
        or any(
            type(value.get(key)) is not bool
            for key in ("application_counts_reconciled", "billing_limit_fit", "provider_reported")
        )
        or any(
            not _integer(value.get(key), minimum=0)
            for key in ("read_operations", "request_bytes", "response_bytes", "write_operations")
        )
    ):
        raise ProviderProofError("Provider accounting observation is invalid.")


def _observation_passes(kind: str, observation: object, candidate: Mapping[str, object]) -> bool:
    assert isinstance(observation, dict)
    if kind == "deployment_metadata":
        return (
            all(
                observation.get(key) is True
                for key in (
                    "exact_source_bundle_topology",
                    "offline_container_security_valid",
                    "parity_public_envelope_valid",
                    "provider_deployment",
                    "public_mode",
                    "release_bundle_coverage_valid",
                )
            )
            and observation.get("runtime_scope") == candidate["scope"]
        )
    if kind == "provider_image":
        return (
            observation.get("digest") == candidate["image_digest"]
            and observation.get("size_bytes") == candidate["image_size_bytes"]
            and int(observation["size_bytes"]) <= MAX_CANDIDATE_IMAGE_SIZE_BYTES
        )
    if kind == "blob_admission":
        return all(observation["checks"].values())  # type: ignore[union-attr]
    if kind == "cold_wakes":
        return int(observation["idle_period_seconds"]) >= 30 and all(
            sample["status"] == "pass"
            and sample["full_body"] is True
            and sample["shell_capabilities_elapsed_ms"] <= 5000
            and sample["first_query_elapsed_ms"] <= 10000
            for sample in observation["samples"]  # type: ignore[union-attr]
        )
    if kind == "warm_results":
        return all(
            item["outcome"] == "pass" and item["full_body"] is True and item["elapsed_ms"] <= 3000
            for item in observation["results"]
        )  # type: ignore[union-attr]
    if kind == "peak_memory":
        # Hobby cannot query the provider metric; a provisioned limit is never peak use.
        return False
    if kind == "lifecycle":
        return all(
            observation[key] is True
            for key in ("restart_observed", "scale_to_zero_provider_reported", "state_persisted")
        )
    if kind == "network_security":
        return (
            observation["egress_provider_reported"] is True
            and observation["public_route_inventory_valid"] is True
            and observation["secret_exposure_detected"] is False
            and observation["unexpected_egress_destinations"] == []
        )
    if kind == "browser":
        return (
            observation["pixels_observed"] is True
            and observation["responsive"] is True
            and observation["console_errors"] == []
        )
    if kind == "provider_accounting":
        return (
            observation["provider_reported"] is True
            and observation["application_counts_reconciled"] is True
            and observation["billing_limit_fit"] is True
        )
    return False


def _validate_identity(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _REQUIRED_IDENTITY_FIELDS:
        raise ProviderProofError("Provider evidence identity shape is invalid.")
    if (
        _FULL_COMMIT.fullmatch(str(value.get("source_commit"))) is None
        or _FULL_COMMIT.fullmatch(str(value.get("artifact_commit"))) is None
        or value.get("source_commit") == value.get("artifact_commit")
        or any(
            not _is_sha256(value.get(key))
            for key in ("admission_policy_digest", "bundle_digest", "runtime_configuration_digest")
        )
        or _IMAGE_DIGEST.fullmatch(str(value.get("provider_image_digest"))) is None
        or not _canonical_id(value.get("deployment_id"))
    ):
        raise ProviderProofError("Provider evidence identity is invalid.")


def _canonical_document(payload: bytes | Mapping[str, object], label: str) -> dict[str, object]:
    if isinstance(payload, bytes):
        try:
            document = json.loads(
                payload.decode("utf-8"),
                object_pairs_hook=_unique_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
            )
        except (UnicodeError, json.JSONDecodeError, _DuplicateKeyError, ValueError) as exc:
            raise ProviderProofError(f"{label} JSON is malformed.") from exc
        if not isinstance(document, dict) or payload != canonical_json_bytes(document):
            raise ProviderProofError(f"{label} JSON is not canonical.")
        return document
    if not isinstance(payload, Mapping):
        raise ProviderProofError(f"{label} must be an object.")
    document = dict(payload)
    _reject_nonfinite(document)
    return document


def _load_canonical_object(path: Path | str, label: str) -> dict[str, object]:
    try:
        return _canonical_document(Path(path).read_bytes(), label)
    except OSError as exc:
        raise ProviderProofError(f"{label} is unreadable.") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _reject_nonfinite(value: object) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ProviderProofError("Non-finite provider evidence is forbidden.")
    if isinstance(value, Mapping):
        for child in value.values():
            _reject_nonfinite(child)
    elif isinstance(value, list):
        for child in value:
            _reject_nonfinite(child)


def _reject_unsafe_content(value: object, *, field: str = "") -> None:
    forbidden = {
        "token",
        "password",
        "credential",
        "secret",
        "cookie",
        "digest_key",
        "filesystem_path",
        "report_path",
    }
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key.lower() in forbidden:
                raise ProviderProofError("Secret-bearing or machine-path fields are forbidden.")
            _reject_unsafe_content(child, field=key)
    elif isinstance(value, list):
        for child in value:
            _reject_unsafe_content(child, field=field)
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            value.startswith(("/tmp/", "/var/", "/users/", "~/", "file://"))
            or "\\" in value
            or "bearer " in lowered
            or "-----begin " in lowered
        ):
            raise ProviderProofError("Secret values and machine-local paths are forbidden.")


def _validate_observed_at(value: object) -> None:
    if not isinstance(value, str) or _UTC_SECONDS.fullmatch(value) is None:
        raise ProviderProofError("Provider observation time is invalid.")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ProviderProofError("Provider observation time is invalid.") from exc
    if parsed.year < 2020:
        raise ProviderProofError("Provider observation time is invalid.")


def _exact(value: Mapping[str, object], fields: set[str]) -> None:
    if set(value) != fields:
        raise ProviderProofError("Provider observation shape is invalid.")


def _integer(value: object, *, minimum: int) -> bool:
    return type(value) is int and value >= minimum


def _nullable_integer(value: object) -> bool:
    return value is None or _integer(value, minimum=0)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _FULL_SHA256.fullmatch(value) is not None


def _canonical_id(value: object) -> bool:
    return isinstance(value, str) and _CANONICAL_ID.fullmatch(value) is not None


def _https_origin(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and parsed.username is None
        and parsed.password is None
        and parsed.port in {None, 443}
        and parsed.path == ""
        and not parsed.query
        and not parsed.fragment
        and value == f"https://{parsed.hostname}"
    )


def _provider_coordination_origin(value: object) -> bool:
    if not _https_origin(value):
        return False
    assert isinstance(value, str)
    hostname = urlsplit(value).hostname
    return hostname == "vercel.com" or (
        isinstance(hostname, str) and hostname.endswith(".private.blob.vercel-storage.com")
    )


def _origin_list(value: object) -> bool:
    return (
        isinstance(value, list)
        and bool(value)
        and len(value) == len(set(value))
        and all(_https_origin(item) for item in value)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    manifests = commands.add_parser("validate-manifests")
    manifests.add_argument("--warm", type=Path, default=WARM_MANIFEST_PATH)
    manifests.add_argument("--browser", type=Path, default=BROWSER_MANIFEST_PATH)

    evidence = commands.add_parser("validate-evidence")
    evidence.add_argument("--input", type=Path, required=True)

    derive = commands.add_parser("derive-gates")
    derive.add_argument("--candidate", type=Path, required=True)
    derive.add_argument("--evidence-index", type=Path, required=True)
    derive.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "validate-manifests":
            warm = load_warm_manifest(args.warm)
            browser = load_browser_manifest(args.browser)
            print(hashlib.sha256(canonical_json_bytes(warm)).hexdigest())
            print(hashlib.sha256(canonical_json_bytes(browser)).hexdigest())
        elif args.command == "validate-evidence":
            checked = validate_provider_evidence(args.input.read_bytes())
            print(hashlib.sha256(canonical_json_bytes(checked)).hexdigest())
        else:
            candidate = validate_candidate_identity(args.candidate.read_bytes())
            index = _load_canonical_object(args.evidence_index, "provider evidence index")
            if set(index) != {"evidence"} or not isinstance(index["evidence"], list):
                raise ProviderProofError("Provider evidence index shape is invalid.")
            payloads: dict[str, bytes] = {}
            for item in index["evidence"]:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"logical_id", "path"}
                    or not _canonical_id(item.get("logical_id"))
                    or not isinstance(item.get("path"), str)
                    or item["logical_id"] in payloads
                ):
                    raise ProviderProofError("Provider evidence index entry is invalid.")
                payloads[item["logical_id"]] = Path(item["path"]).read_bytes()
            report = derive_provider_gate_report(candidate, payloads)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(canonical_json_bytes(report))
            print(hashlib.sha256(canonical_json_bytes(report)).hexdigest())
    except (OSError, ProviderProofError, CandidateError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
