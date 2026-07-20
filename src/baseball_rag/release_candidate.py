"""Strict candidate identity, release-gate, and deployment-attestation tooling."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from baseball_rag.provider_identity import is_exact_vercel_deployment_id
from baseball_rag.public_release_config import (
    PublicReleaseConfigError,
    canonical_json_bytes,
    check_admission_policy_artifact,
    load_runtime_configuration,
)
from baseball_rag.release_bundle import check_release_bundle

CANDIDATE_SCHEMA = "ground-ball-release-candidate-v1"
GATE_REPORT_SCHEMA = "ground-ball-release-gate-report-v1"
ATTESTATION_SCHEMA = "ground-ball-deployment-attestation-v1"
CANDIDATE_SCOPES = frozenset({"local_ci", "protected_preview", "production"})
MAX_CANDIDATE_IMAGE_SIZE_BYTES = 1_073_741_824
_PROVIDER_CACHE_SMOKE_SCHEMA = "ground-ball-provider-runtime-cache-smoke-v3"
_COVERAGE_REPORT_SCHEMA = "query-coverage-report-v1"
PROVIDER_OBSERVATION_IDS = (
    "cold_wakes",
    "deployment_metadata_configuration",
    "network_security_public_routes",
    "peak_memory",
    "protected_blob_coordination",
    "protected_browser_desktop_mobile",
    "provider_image_measurement",
    "provider_operation_accounting",
    "restart_replacement_scale_to_zero",
    "warm_manifest",
)
PROVIDER_OBSERVATION_SCHEMA_IDENTITIES = {
    "cold_wakes": "ground-ball-provider-cold-wakes-v1",
    "deployment_metadata_configuration": "ground-ball-provider-deployment-metadata-v1",
    "network_security_public_routes": "ground-ball-provider-network-security-proof-v1",
    "peak_memory": "ground-ball-provider-peak-memory-v1",
    "protected_blob_coordination": "ground-ball-protected-blob-admission-proof-v1",
    "protected_browser_desktop_mobile": "ground-ball-protected-browser-proof-v1",
    "provider_image_measurement": "ground-ball-provider-image-measurement-v1",
    "provider_operation_accounting": "ground-ball-provider-operation-accounting-v1",
    "restart_replacement_scale_to_zero": "ground-ball-provider-lifecycle-proof-v1",
    "warm_manifest": "ground-ball-provider-warm-results-v1",
}
REQUIRED_GATE_IDS = (
    "candidate_identity_topology",
    "release_bundle_coverage",
    "deterministic_parity_public_envelope",
    "offline_container_security",
    "local_image_size",
    "runtime_admission_configuration",
    "protected_blob_coordination",
    "protected_deployment_image",
    "cold_wake_warm_performance",
    "provider_peak_memory",
    "restart_replacement_scale_to_zero",
    "network_egress_public_routes",
    "protected_browser_desktop_mobile",
    "provider_operation_accounting",
    "provider_deployment_attestation",
)
_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CANONICAL_ID = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")
_MEDIA_TYPE = re.compile(r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")
_CANDIDATE_ID = re.compile(r"^gbc_[0-9a-f]{64}$")


class CandidateError(ValueError):
    """Candidate, gate, or attestation material is malformed or mismatched."""


class _DuplicateKeyError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceInput:
    """A machine-local input converted to a path-free logical evidence identity."""

    logical_id: str
    path: Path
    media_type: str
    schema_identity: str


def validate_artifact_topology(
    *,
    source_commit: str,
    artifact_commit: str,
    artifact_parent_commit: str,
    changed_paths: Sequence[str],
) -> None:
    """Validate exact two-commit topology discovered by an external git caller."""
    if (
        not _is_commit(source_commit)
        or not _is_commit(artifact_commit)
        or not _is_commit(artifact_parent_commit)
        or source_commit != artifact_parent_commit
        or source_commit == artifact_commit
    ):
        raise CandidateError("Candidate source/artifact commit topology is invalid.")
    if (
        not changed_paths
        or len(changed_paths) != len(set(changed_paths))
        or "release/bundle/release-manifest.json" not in changed_paths
        or any(
            not isinstance(path, str)
            or not path.startswith("release/bundle/")
            or path.endswith("/")
            or ".." in path.split("/")
            for path in changed_paths
        )
    ):
        raise CandidateError("Artifact commit must change only canonical Release Bundle files.")


def build_candidate_identity(
    *,
    scope: str,
    source_commit: str,
    artifact_commit: str,
    artifact_parent_commit: str,
    artifact_changed_paths: Sequence[str],
    bundle_digest: str,
    image_digest: str,
    image_size_bytes: int,
    image_size_measurement_kind: str,
    runtime_configuration_digest: str,
    admission_policy_digest: str,
    evidence_inputs: Sequence[EvidenceInput],
) -> dict[str, object]:
    """Build one canonical path-free identity after hashing exact evidence inputs."""
    validate_artifact_topology(
        source_commit=source_commit,
        artifact_commit=artifact_commit,
        artifact_parent_commit=artifact_parent_commit,
        changed_paths=artifact_changed_paths,
    )
    _validate_semantic_evidence(
        evidence_inputs,
        source_commit=source_commit,
        bundle_digest=bundle_digest,
        runtime_configuration_digest=runtime_configuration_digest,
    )
    evidence = [_evidence_entry(item) for item in evidence_inputs]
    evidence.sort(key=lambda item: str(item["logical_id"]))
    body: dict[str, object] = {
        "admission_policy_digest": admission_policy_digest,
        "artifact_commit": artifact_commit,
        "bundle_digest": bundle_digest,
        "evidence": evidence,
        "image_digest": image_digest,
        "image_size_bytes": image_size_bytes,
        "image_size_measurement_kind": image_size_measurement_kind,
        "runtime_configuration_digest": runtime_configuration_digest,
        "schema_version": CANDIDATE_SCHEMA,
        "scope": scope,
        "source_commit": source_commit,
        "topology": {
            "artifact_change_scope": "release/bundle/**",
            "artifact_parent_commit": artifact_parent_commit,
            "model": "source_then_release_bundle",
        },
    }
    candidate = {**body, "candidate_id": _candidate_id(body)}
    # Validation is part of construction, so malformed inputs never produce output.
    validate_candidate_identity(canonical_json_bytes(candidate))
    return candidate


def validate_candidate_identity(
    payload: bytes | Mapping[str, object],
    *,
    expected_source_commit: str | None = None,
    expected_artifact_commit: str | None = None,
    expected_bundle_digest: str | None = None,
    expected_image_digest: str | None = None,
    expected_runtime_configuration_digest: str | None = None,
    expected_admission_policy_digest: str | None = None,
) -> dict[str, object]:
    document = _canonical_document(payload, "candidate identity")
    required = {
        "admission_policy_digest",
        "artifact_commit",
        "bundle_digest",
        "candidate_id",
        "evidence",
        "image_digest",
        "image_size_bytes",
        "image_size_measurement_kind",
        "runtime_configuration_digest",
        "schema_version",
        "scope",
        "source_commit",
        "topology",
    }
    if set(document) != required or document.get("schema_version") != CANDIDATE_SCHEMA:
        raise CandidateError("Candidate identity shape is invalid.")
    scope = document.get("scope")
    source = document.get("source_commit")
    artifact = document.get("artifact_commit")
    topology = document.get("topology")
    if scope not in CANDIDATE_SCOPES or not _is_commit(source) or not _is_commit(artifact):
        raise CandidateError("Candidate scope or commits are invalid.")
    if not isinstance(topology, dict) or topology != {
        "artifact_change_scope": "release/bundle/**",
        "artifact_parent_commit": source,
        "model": "source_then_release_bundle",
    }:
        raise CandidateError("Candidate source/artifact topology is invalid.")
    if artifact == source:
        raise CandidateError("Candidate artifact commit must be distinct from its source.")
    for key in (
        "admission_policy_digest",
        "bundle_digest",
        "runtime_configuration_digest",
    ):
        if not _is_sha256(document.get(key)):
            raise CandidateError(f"Candidate {key} is invalid.")
    image_digest = document.get("image_digest")
    if not isinstance(image_digest, str) or _IMAGE_DIGEST.fullmatch(image_digest) is None:
        raise CandidateError("Candidate image digest is invalid.")
    size = document.get("image_size_bytes")
    if type(size) is not int or size < 0 or size > MAX_CANDIDATE_IMAGE_SIZE_BYTES:
        raise CandidateError("Candidate image size is invalid.")
    measurement = document.get("image_size_measurement_kind")
    expected_measurement = (
        "docker-image-inspect-size-bytes"
        if scope == "local_ci"
        else "provider-oci-manifest-size-bytes"
    )
    if measurement != expected_measurement:
        raise CandidateError("Candidate image size measurement kind is invalid for its scope.")
    evidence = document.get("evidence")
    if not isinstance(evidence, list):
        raise CandidateError("Candidate evidence set is invalid.")
    logical_ids: list[str] = []
    for entry in evidence:
        _validate_evidence_entry(entry)
        assert isinstance(entry, dict)
        logical_ids.append(entry["logical_id"])
    if logical_ids != sorted(logical_ids) or len(logical_ids) != len(set(logical_ids)):
        raise CandidateError("Candidate evidence identities must be unique and sorted.")
    body = {key: value for key, value in document.items() if key != "candidate_id"}
    candidate_id = document.get("candidate_id")
    if (
        not isinstance(candidate_id, str)
        or _CANDIDATE_ID.fullmatch(candidate_id) is None
        or candidate_id != _candidate_id(body)
    ):
        raise CandidateError("Candidate ID is noncanonical or stale.")
    _reject_secret_or_path_content(document)
    expectations = {
        "source_commit": expected_source_commit,
        "artifact_commit": expected_artifact_commit,
        "bundle_digest": expected_bundle_digest,
        "image_digest": expected_image_digest,
        "runtime_configuration_digest": expected_runtime_configuration_digest,
        "admission_policy_digest": expected_admission_policy_digest,
    }
    for key, expected in expectations.items():
        if expected is not None and document[key] != expected:
            raise CandidateError(f"Candidate {key} does not match the required identity.")
    return document


def candidate_identity_digest(candidate: Mapping[str, object]) -> str:
    checked = validate_candidate_identity(candidate)
    return hashlib.sha256(canonical_json_bytes(checked)).hexdigest()


def build_gate_report(
    candidate: Mapping[str, object],
    results: Mapping[str, Mapping[str, object]],
) -> dict[str, object]:
    checked_candidate = validate_candidate_identity(candidate)
    if set(results) != set(REQUIRED_GATE_IDS) or len(results) != len(REQUIRED_GATE_IDS):
        raise CandidateError("Release gate inventory is incomplete or contains extras.")
    evidence_ids = _candidate_evidence_ids(checked_candidate)
    gates: list[dict[str, object]] = []
    for gate_id in REQUIRED_GATE_IDS:
        result = results[gate_id]
        if not isinstance(result, Mapping) or set(result) != {"status", "evidence"}:
            raise CandidateError(f"Gate result shape is invalid for {gate_id}.")
        status = result.get("status")
        references = result.get("evidence")
        if status not in {"pass", "fail", "blocked"} or not isinstance(references, list):
            raise CandidateError(f"Gate status or evidence is invalid for {gate_id}.")
        if (
            not all(isinstance(item, str) for item in references)
            or references != sorted(references)
            or len(references) != len(set(references))
            or not set(references) <= evidence_ids
            or (status == "pass" and not references)
        ):
            raise CandidateError(f"Gate evidence is invalid for {gate_id}.")
        _validate_parity_gate_evidence(checked_candidate, gate_id, status, references)
        gates.append({"evidence": references, "gate_id": gate_id, "status": status})
    report = {
        "candidate_id": checked_candidate["candidate_id"],
        "candidate_identity_digest": candidate_identity_digest(checked_candidate),
        "eligible": all(gate["status"] == "pass" for gate in gates),
        "gates": gates,
        "schema_version": GATE_REPORT_SCHEMA,
    }
    return report


def validate_gate_report(
    payload: bytes | Mapping[str, object], candidate: Mapping[str, object]
) -> dict[str, object]:
    checked_candidate = validate_candidate_identity(candidate)
    document = _canonical_document(payload, "gate report")
    if (
        set(document)
        != {
            "candidate_id",
            "candidate_identity_digest",
            "eligible",
            "gates",
            "schema_version",
        }
        or document.get("schema_version") != GATE_REPORT_SCHEMA
    ):
        raise CandidateError("Gate report shape is invalid.")
    if (
        document.get("candidate_id") != checked_candidate["candidate_id"]
        or document.get("candidate_identity_digest") != candidate_identity_digest(checked_candidate)
        or type(document.get("eligible")) is not bool
    ):
        raise CandidateError("Gate report candidate binding is invalid.")
    gates = document.get("gates")
    if not isinstance(gates, list) or len(gates) != len(REQUIRED_GATE_IDS):
        raise CandidateError("Gate report inventory is invalid.")
    results: dict[str, Mapping[str, object]] = {}
    for gate in gates:
        if not isinstance(gate, dict) or set(gate) != {"evidence", "gate_id", "status"}:
            raise CandidateError("Gate report entry is invalid.")
        gate_id = gate.get("gate_id")
        if not isinstance(gate_id, str) or gate_id in results:
            raise CandidateError("Gate report contains a duplicate or malformed gate.")
        results[gate_id] = {"status": gate.get("status"), "evidence": gate.get("evidence")}
    if set(results) != set(REQUIRED_GATE_IDS):
        raise CandidateError("Gate report inventory is invalid.")
    if [gate.get("gate_id") for gate in gates] != list(REQUIRED_GATE_IDS):
        raise CandidateError("Gate report inventory is not in canonical order.")
    evidence_ids = _candidate_evidence_ids(checked_candidate)
    for gate_id in REQUIRED_GATE_IDS:
        status = results[gate_id].get("status")
        refs = results[gate_id].get("evidence")
        if (
            status not in {"pass", "fail", "blocked"}
            or not isinstance(refs, list)
            or refs != sorted(refs)
            or len(refs) != len(set(refs))
            or not set(refs) <= evidence_ids
            or (status == "pass" and not refs)
        ):
            raise CandidateError(f"Gate evidence is invalid for {gate_id}.")
        _validate_parity_gate_evidence(checked_candidate, gate_id, status, refs)
    expected_eligible = all(results[item]["status"] == "pass" for item in REQUIRED_GATE_IDS)
    if document["eligible"] is not expected_eligible:
        raise CandidateError("Gate eligibility is inconsistent.")
    return document


def gate_report_digest(report: Mapping[str, object]) -> str:
    # The report is already bound to a validated candidate by construction/validation.
    return hashlib.sha256(canonical_json_bytes(report)).hexdigest()


def build_local_attestation_template(
    candidate: Mapping[str, object], report: Mapping[str, object]
) -> dict[str, object]:
    checked_candidate = validate_candidate_identity(candidate)
    checked_report = validate_gate_report(report, checked_candidate)
    if checked_candidate["scope"] != "local_ci":
        raise CandidateError("A no-deployment template is valid only for local CI.")
    template = {
        "admission_policy_digest": checked_candidate["admission_policy_digest"],
        "bundle_digest": checked_candidate["bundle_digest"],
        "candidate_id": checked_candidate["candidate_id"],
        "candidate_identity_digest": candidate_identity_digest(checked_candidate),
        "deployment_exists": False,
        "evidence": [],
        "gate_report_digest": gate_report_digest(checked_report),
        "image_digest": checked_candidate["image_digest"],
        "observations": {},
        "promotion_eligible": False,
        "provider": None,
        "runtime_configuration_digest": checked_candidate["runtime_configuration_digest"],
        "schema_version": ATTESTATION_SCHEMA,
        "scope": "local_ci",
        "statement": "No provider deployment exists for this local CI candidate.",
        "status": "template",
    }
    validate_deployment_attestation(template, checked_candidate, checked_report)
    return template


def build_provider_attestation(
    candidate: Mapping[str, object],
    report: Mapping[str, object],
    *,
    provider_name: str,
    deployment_id: str,
    image_digest: str,
    image_size_bytes: int,
    image_size_measurement_kind: str,
    observation_to_evidence: Mapping[str, str],
) -> dict[str, object]:
    """Build an exact provider attestation only for one all-pass candidate."""
    checked_candidate = validate_candidate_identity(candidate)
    checked_report = validate_gate_report(report, checked_candidate)
    if checked_candidate["scope"] not in {"protected_preview", "production"}:
        raise CandidateError("Provider attestation candidate scope is invalid.")
    if checked_report["eligible"] is not True:
        raise CandidateError("Provider attestation requires an all-pass exact gate report.")
    if not isinstance(provider_name, str) or _CANONICAL_ID.fullmatch(provider_name) is None:
        raise CandidateError("Provider attestation provider name is invalid.")
    if not _provider_deployment_id_is_valid(provider_name, deployment_id):
        raise CandidateError("Provider attestation deployment ID is invalid.")
    if image_digest != checked_candidate["image_digest"]:
        raise CandidateError("Provider attestation image digest is foreign.")
    if (
        type(image_size_bytes) is not int
        or image_size_bytes < 0
        or image_size_bytes > MAX_CANDIDATE_IMAGE_SIZE_BYTES
        or image_size_bytes != checked_candidate["image_size_bytes"]
    ):
        raise CandidateError("Provider attestation image size is invalid or mismatched.")
    if (
        image_size_measurement_kind != "provider-oci-manifest-size-bytes"
        or image_size_measurement_kind != checked_candidate["image_size_measurement_kind"]
    ):
        raise CandidateError("Provider attestation image measurement kind is invalid.")
    if set(observation_to_evidence) != set(PROVIDER_OBSERVATION_IDS):
        raise CandidateError("Provider attestation observation inventory is incomplete.")
    if not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in observation_to_evidence.items()
    ):
        raise CandidateError("Provider attestation observation map is invalid.")
    candidate_evidence = _candidate_evidence_ids(checked_candidate)
    evidence = sorted(set(observation_to_evidence.values()))
    if not evidence or not set(evidence) <= candidate_evidence:
        raise CandidateError("Provider attestation evidence is foreign or incomplete.")
    raw_candidate_evidence = checked_candidate.get("evidence")
    if not isinstance(raw_candidate_evidence, list):  # validated above; keeps typing explicit
        raise CandidateError("Provider attestation candidate evidence is invalid.")
    evidence_schemas = {
        item["logical_id"]: item["schema_identity"]
        for item in raw_candidate_evidence
        if isinstance(item, dict)
        and isinstance(item.get("logical_id"), str)
        and isinstance(item.get("schema_identity"), str)
    }
    if any(
        evidence_schemas.get(logical_id) != PROVIDER_OBSERVATION_SCHEMA_IDENTITIES[observation]
        for observation, logical_id in observation_to_evidence.items()
    ):
        raise CandidateError("Provider attestation observation evidence schema is invalid.")
    attestation = {
        "admission_policy_digest": checked_candidate["admission_policy_digest"],
        "bundle_digest": checked_candidate["bundle_digest"],
        "candidate_id": checked_candidate["candidate_id"],
        "candidate_identity_digest": candidate_identity_digest(checked_candidate),
        "deployment_exists": True,
        "evidence": evidence,
        "gate_report_digest": gate_report_digest(checked_report),
        "image_digest": checked_candidate["image_digest"],
        "observations": dict(sorted(observation_to_evidence.items())),
        "promotion_eligible": True,
        "provider": {
            "deployment_id": deployment_id,
            "image_digest": image_digest,
            "image_size_bytes": image_size_bytes,
            "image_size_measurement_kind": image_size_measurement_kind,
            "name": provider_name,
        },
        "runtime_configuration_digest": checked_candidate["runtime_configuration_digest"],
        "schema_version": ATTESTATION_SCHEMA,
        "scope": checked_candidate["scope"],
        "statement": "Exact protected provider observations are attached.",
        "status": "attested",
    }
    validate_deployment_attestation(attestation, checked_candidate, checked_report)
    return attestation


def validate_deployment_attestation(
    payload: bytes | Mapping[str, object],
    candidate: Mapping[str, object],
    report: Mapping[str, object],
) -> dict[str, object]:
    checked_candidate = validate_candidate_identity(candidate)
    checked_report = validate_gate_report(report, checked_candidate)
    document = _canonical_document(payload, "deployment attestation")
    required = {
        "admission_policy_digest",
        "bundle_digest",
        "candidate_id",
        "candidate_identity_digest",
        "deployment_exists",
        "evidence",
        "gate_report_digest",
        "image_digest",
        "observations",
        "promotion_eligible",
        "provider",
        "runtime_configuration_digest",
        "schema_version",
        "scope",
        "statement",
        "status",
    }
    if set(document) != required or document.get("schema_version") != ATTESTATION_SCHEMA:
        raise CandidateError("Deployment Attestation shape is invalid.")
    bindings = {
        "candidate_id": checked_candidate["candidate_id"],
        "candidate_identity_digest": candidate_identity_digest(checked_candidate),
        "bundle_digest": checked_candidate["bundle_digest"],
        "image_digest": checked_candidate["image_digest"],
        "runtime_configuration_digest": checked_candidate["runtime_configuration_digest"],
        "admission_policy_digest": checked_candidate["admission_policy_digest"],
        "gate_report_digest": gate_report_digest(checked_report),
    }
    if any(document[key] != expected for key, expected in bindings.items()):
        raise CandidateError("Deployment Attestation identity binding is invalid.")
    if document.get("scope") != checked_candidate["scope"]:
        raise CandidateError("Deployment Attestation scope is invalid.")
    if document.get("status") == "template":
        expected_local = {
            "deployment_exists": False,
            "evidence": [],
            "observations": {},
            "promotion_eligible": False,
            "provider": None,
            "scope": "local_ci",
            "statement": "No provider deployment exists for this local CI candidate.",
        }
        if any(document.get(key) != value for key, value in expected_local.items()):
            raise CandidateError("Local Deployment Attestation template is invalid.")
    elif document.get("status") == "attested":
        _validate_provider_attestation(document, checked_candidate, checked_report)
    else:
        raise CandidateError("Deployment Attestation status is invalid.")
    _reject_secret_or_path_content(document)
    return document


def _provider_deployment_id_is_valid(provider_name: object, deployment_id: object) -> bool:
    if provider_name == "vercel":
        return is_exact_vercel_deployment_id(deployment_id)
    return isinstance(deployment_id, str) and _CANONICAL_ID.fullmatch(deployment_id) is not None


def _validate_provider_attestation(
    document: Mapping[str, object],
    candidate: Mapping[str, object],
    report: Mapping[str, object],
) -> None:
    provider = document.get("provider")
    evidence = document.get("evidence")
    observations = document.get("observations")
    provider_name = provider.get("name") if isinstance(provider, dict) else None
    deployment_id = provider.get("deployment_id") if isinstance(provider, dict) else None
    measurement_kind = (
        provider.get("image_size_measurement_kind") if isinstance(provider, dict) else None
    )
    if (
        candidate["scope"] not in {"protected_preview", "production"}
        or document.get("deployment_exists") is not True
        or document.get("promotion_eligible") is not True
        or report.get("eligible") is not True
        or not isinstance(provider, dict)
        or set(provider)
        != {
            "deployment_id",
            "image_digest",
            "image_size_bytes",
            "image_size_measurement_kind",
            "name",
        }
        or provider.get("image_digest") != candidate["image_digest"]
        or type(provider.get("image_size_bytes")) is not int
        or provider.get("image_size_bytes") != candidate["image_size_bytes"]
        or not isinstance(provider_name, str)
        or _CANONICAL_ID.fullmatch(provider_name) is None
        or not _provider_deployment_id_is_valid(provider_name, deployment_id)
        or measurement_kind != "provider-oci-manifest-size-bytes"
        or measurement_kind != candidate["image_size_measurement_kind"]
        or not isinstance(evidence, list)
        or not evidence
        or not isinstance(observations, dict)
        or set(observations) != set(PROVIDER_OBSERVATION_IDS)
        or not all(isinstance(item, str) for item in observations.values())
        or not isinstance(document.get("statement"), str)
        or not document["statement"]
    ):
        raise CandidateError("Provider Deployment Attestation lacks exact external evidence.")
    candidate_evidence = _candidate_evidence_ids(candidate)
    observation_evidence = set(observations.values())
    raw_candidate_evidence = candidate.get("evidence")
    if not isinstance(raw_candidate_evidence, list):
        raise CandidateError("Provider Deployment Attestation candidate evidence is invalid.")
    evidence_schemas = {
        item["logical_id"]: item["schema_identity"]
        for item in raw_candidate_evidence
        if isinstance(item, dict)
        and isinstance(item.get("logical_id"), str)
        and isinstance(item.get("schema_identity"), str)
    }
    if (
        not all(isinstance(item, str) for item in evidence)
        or evidence != sorted(evidence)
        or len(evidence) != len(set(evidence))
        or not set(evidence) <= candidate_evidence
        or not observation_evidence <= set(evidence)
        or any(
            evidence_schemas.get(logical_id) != PROVIDER_OBSERVATION_SCHEMA_IDENTITIES[observation]
            for observation, logical_id in observations.items()
        )
    ):
        raise CandidateError("Provider Deployment Attestation evidence is invalid.")


def _candidate_evidence_ids(candidate: Mapping[str, object]) -> set[str]:
    evidence = candidate.get("evidence")
    if not isinstance(evidence, list):
        raise CandidateError("Candidate evidence set is invalid.")
    identities: set[str] = set()
    for item in evidence:
        if not isinstance(item, dict) or not isinstance(item.get("logical_id"), str):
            raise CandidateError("Candidate evidence set is invalid.")
        identities.add(item["logical_id"])
    return identities


def _candidate_id(body: Mapping[str, object]) -> str:
    return "gbc_" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()


def _validate_parity_gate_evidence(
    candidate: Mapping[str, object],
    gate_id: str,
    status: object,
    references: list[object],
) -> None:
    if gate_id != "deterministic_parity_public_envelope" or status != "pass":
        return
    raw_evidence = candidate.get("evidence")
    if not isinstance(raw_evidence, list):
        raise CandidateError("Candidate evidence set is invalid.")
    evidence_schemas = {
        item["logical_id"]: item["schema_identity"]
        for item in raw_evidence
        if isinstance(item, dict)
        and isinstance(item.get("logical_id"), str)
        and isinstance(item.get("schema_identity"), str)
    }
    referenced_schemas = {
        evidence_schemas[item]
        for item in references
        if isinstance(item, str) and item in evidence_schemas
    }
    if not {_PROVIDER_CACHE_SMOKE_SCHEMA, _COVERAGE_REPORT_SCHEMA} <= referenced_schemas:
        raise CandidateError(
            "Deterministic parity requires semantically validated provider-cache smoke."
        )


def _validate_semantic_evidence(
    evidence_inputs: Sequence[EvidenceInput],
    *,
    source_commit: str,
    bundle_digest: str,
    runtime_configuration_digest: str,
) -> None:
    smoke_inputs = [
        item for item in evidence_inputs if item.schema_identity == _PROVIDER_CACHE_SMOKE_SCHEMA
    ]
    if not smoke_inputs:
        return
    coverage_inputs = [
        item for item in evidence_inputs if item.schema_identity == _COVERAGE_REPORT_SCHEMA
    ]
    if len(smoke_inputs) != 1 or len(coverage_inputs) != 1:
        raise CandidateError("Provider runtime-cache smoke evidence inventory is invalid.")
    try:
        smoke_bytes = smoke_inputs[0].path.read_bytes()
        coverage_bytes = coverage_inputs[0].path.read_bytes()
    except OSError as exc:
        raise CandidateError("Provider runtime-cache smoke evidence is unreadable.") from exc
    try:
        coverage = json.loads(coverage_bytes.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, _DuplicateKeyError) as exc:
        raise CandidateError("Coverage Report evidence JSON is malformed.") from exc
    if not isinstance(coverage, dict):
        raise CandidateError("Coverage Report evidence must be an object.")
    expected_coverage = {
        "proof_id": coverage.get("proof_id"),
        "proof_identity": coverage.get("proof_identity"),
    }
    smoke_runtime_digest = runtime_configuration_digest
    provider_runtime_inputs = [
        item for item in evidence_inputs if item.logical_id == "provider-runtime-config"
    ]
    if len(provider_runtime_inputs) > 1:
        raise CandidateError("Provider runtime configuration evidence is duplicated.")
    if provider_runtime_inputs:
        try:
            provider_runtime = load_runtime_configuration(provider_runtime_inputs[0].path)
        except (OSError, PublicReleaseConfigError) as exc:
            raise CandidateError("Provider runtime configuration evidence is invalid.") from exc
        if not provider_runtime.provider_deployment:
            raise CandidateError("Provider runtime configuration evidence is invalid.")
        smoke_runtime_digest = provider_runtime.digest
    try:
        from baseball_rag.provider_runtime_cache_smoke import (
            ProviderRuntimeCacheSmokeError,
            validate_provider_runtime_cache_smoke,
        )

        validate_provider_runtime_cache_smoke(
            smoke_bytes,
            expected_source_commit=source_commit,
            expected_release_bundle_digest=bundle_digest,
            expected_runtime_configuration_digest=smoke_runtime_digest,
            expected_coverage=expected_coverage,
        )
    except ProviderRuntimeCacheSmokeError as exc:
        raise CandidateError("Provider runtime-cache smoke evidence is invalid.") from exc


def _evidence_entry(item: EvidenceInput) -> dict[str, str]:
    if not isinstance(item, EvidenceInput):
        raise CandidateError("Evidence input is invalid.")
    try:
        digest = hashlib.sha256(item.path.read_bytes()).hexdigest()
    except OSError as exc:
        raise CandidateError("Evidence input is unreadable.") from exc
    entry = {
        "logical_id": item.logical_id,
        "media_type": item.media_type,
        "schema_identity": item.schema_identity,
        "sha256": digest,
    }
    _validate_evidence_entry(entry)
    return entry


def _validate_evidence_entry(entry: object) -> None:
    if not isinstance(entry, dict) or set(entry) != {
        "logical_id",
        "media_type",
        "schema_identity",
        "sha256",
    }:
        raise CandidateError("Evidence entry shape is invalid.")
    if (
        not isinstance(entry.get("logical_id"), str)
        or _CANONICAL_ID.fullmatch(entry["logical_id"]) is None
        or not isinstance(entry.get("media_type"), str)
        or _MEDIA_TYPE.fullmatch(entry["media_type"]) is None
        or not isinstance(entry.get("schema_identity"), str)
        or _CANONICAL_ID.fullmatch(entry["schema_identity"]) is None
        or not _is_sha256(entry.get("sha256"))
    ):
        raise CandidateError("Evidence identity is invalid.")


def _canonical_document(payload: bytes | Mapping[str, object], label: str) -> dict[str, object]:
    if isinstance(payload, bytes):
        try:
            document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
        except (UnicodeError, json.JSONDecodeError, _DuplicateKeyError) as exc:
            raise CandidateError(f"{label} JSON is malformed.") from exc
        if not isinstance(document, dict) or payload != canonical_json_bytes(document):
            raise CandidateError(f"{label} JSON is not canonical.")
        return document
    if not isinstance(payload, Mapping):
        raise CandidateError(f"{label} must be an object.")
    return dict(payload)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def _is_commit(value: object) -> bool:
    return isinstance(value, str) and _FULL_COMMIT.fullmatch(value) is not None


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _FULL_SHA256.fullmatch(value) is not None


def _reject_secret_or_path_content(value: object, *, field: str = "") -> None:
    forbidden_fields = {"token", "password", "credential", "secret", "cookie_value", "digest_key"}
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key.lower() in forbidden_fields:
                raise CandidateError("Secret-bearing fields are forbidden.")
            _reject_secret_or_path_content(child, field=key)
    elif isinstance(value, list):
        for child in value:
            _reject_secret_or_path_content(child, field=field)
    elif isinstance(value, str):
        lowered = value.lower()
        if (
            value.startswith(("/", "~/", "file://"))
            or "\\" in value
            or "=" in value
            or "bearer " in lowered
            or "-----begin " in lowered
        ):
            raise CandidateError("Machine-local paths and secret values are forbidden.")


def _read_json_file(path: Path, label: str) -> dict[str, object]:
    try:
        return _canonical_document(path.read_bytes(), label)
    except OSError as exc:
        raise CandidateError(f"{label} is unreadable.") from exc


def _write_document(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(document))


def _load_evidence_spec(path: Path) -> tuple[EvidenceInput, ...]:
    document = _read_json_file(path, "evidence specification")
    if set(document) != {"evidence"} or not isinstance(document["evidence"], list):
        raise CandidateError("Evidence specification shape is invalid.")
    result = []
    for item in document["evidence"]:
        if not isinstance(item, dict) or set(item) != {
            "logical_id",
            "media_type",
            "path",
            "schema_identity",
        }:
            raise CandidateError("Evidence specification entry is invalid.")
        if not all(isinstance(item[key], str) for key in item):
            raise CandidateError("Evidence specification entry is invalid.")
        result.append(
            EvidenceInput(
                logical_id=item["logical_id"],
                path=Path(item["path"]),
                media_type=item["media_type"],
                schema_identity=item["schema_identity"],
            )
        )
    return tuple(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    assemble = commands.add_parser("assemble")
    assemble.add_argument("--scope", choices=sorted(CANDIDATE_SCOPES), required=True)
    assemble.add_argument("--source-commit", required=True)
    assemble.add_argument("--artifact-commit", required=True)
    assemble.add_argument("--artifact-parent-commit", required=True)
    assemble.add_argument("--artifact-changed-paths", type=Path, required=True)
    assemble.add_argument("--bundle-root", type=Path, required=True)
    assemble.add_argument("--image-digest", required=True)
    assemble.add_argument("--image-size-bytes", type=int, required=True)
    assemble.add_argument("--image-size-measurement-kind", required=True)
    assemble.add_argument("--runtime-config", type=Path, required=True)
    assemble.add_argument("--admission-policy", type=Path, required=True)
    assemble.add_argument("--evidence-spec", type=Path, required=True)
    assemble.add_argument("--gate-results", type=Path)
    assemble.add_argument("--output", type=Path, required=True)
    assemble.add_argument("--gate-report-output", type=Path)
    assemble.add_argument("--attestation-output", type=Path)

    gates = commands.add_parser("gates")
    gates.add_argument("--candidate", type=Path, required=True)
    gates.add_argument("--results", type=Path, required=True)
    gates.add_argument("--output", type=Path, required=True)

    template = commands.add_parser("attestation-template")
    template.add_argument("--candidate", type=Path, required=True)
    template.add_argument("--gate-report", type=Path, required=True)
    template.add_argument("--output", type=Path, required=True)

    provider_attestation = commands.add_parser("provider-attestation")
    provider_attestation.add_argument("--candidate", type=Path, required=True)
    provider_attestation.add_argument("--gate-report", type=Path, required=True)
    provider_attestation.add_argument("--provider", required=True)
    provider_attestation.add_argument("--deployment-id", required=True)
    provider_attestation.add_argument("--image-digest", required=True)
    provider_attestation.add_argument("--image-size-bytes", type=int, required=True)
    provider_attestation.add_argument("--image-size-measurement-kind", required=True)
    provider_attestation.add_argument("--observation-map", type=Path, required=True)
    provider_attestation.add_argument("--output", type=Path, required=True)

    validate = commands.add_parser("validate")
    validate.add_argument("kind", choices=("candidate", "gates", "attestation"))
    validate.add_argument("--candidate", type=Path, required=True)
    validate.add_argument("--gate-report", type=Path)
    validate.add_argument("--attestation", type=Path)

    args = parser.parse_args(argv)
    try:
        if args.command == "assemble":
            try:
                changed_paths = args.artifact_changed_paths.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeError) as exc:
                raise CandidateError("Artifact changed-path inventory is unreadable.") from exc
            bundle = check_release_bundle(
                args.bundle_root, expected_source_commit=args.source_commit
            )
            runtime = load_runtime_configuration(args.runtime_config)
            if runtime.scope != args.scope:
                raise CandidateError("Runtime configuration scope does not match the candidate.")
            policy = check_admission_policy_artifact(args.admission_policy)
            policy_digest = hashlib.sha256(canonical_json_bytes(policy)).hexdigest()
            candidate = build_candidate_identity(
                scope=args.scope,
                source_commit=args.source_commit,
                artifact_commit=args.artifact_commit,
                artifact_parent_commit=args.artifact_parent_commit,
                artifact_changed_paths=changed_paths,
                bundle_digest=bundle.digest,
                image_digest=args.image_digest,
                image_size_bytes=args.image_size_bytes,
                image_size_measurement_kind=args.image_size_measurement_kind,
                runtime_configuration_digest=runtime.digest,
                admission_policy_digest=policy_digest,
                evidence_inputs=_load_evidence_spec(args.evidence_spec),
            )
            aggregate_outputs = (
                args.gate_results,
                args.gate_report_output,
                args.attestation_output,
            )
            if any(item is not None for item in aggregate_outputs) and not all(
                item is not None for item in aggregate_outputs
            ):
                raise CandidateError(
                    "Aggregate assembly requires gate results and both additional outputs."
                )
            report: dict[str, object] | None = None
            attestation: dict[str, object] | None = None
            if args.gate_results is not None:
                results_document = _read_json_file(args.gate_results, "gate results")
                if set(results_document) != {"gates"} or not isinstance(
                    results_document["gates"], dict
                ):
                    raise CandidateError("Gate results shape is invalid.")
                report = build_gate_report(candidate, results_document["gates"])
                attestation = build_local_attestation_template(candidate, report)
                validate_candidate_identity(canonical_json_bytes(candidate))
                validate_gate_report(canonical_json_bytes(report), candidate)
                validate_deployment_attestation(
                    canonical_json_bytes(attestation), candidate, report
                )
            # No candidate record is written until every requested aggregate record validates.
            _write_document(args.output, candidate)
            if report is not None and attestation is not None:
                assert args.gate_report_output is not None
                assert args.attestation_output is not None
                _write_document(args.gate_report_output, report)
                _write_document(args.attestation_output, attestation)
            print(candidate["candidate_id"])
        elif args.command == "gates":
            candidate = validate_candidate_identity(args.candidate.read_bytes())
            results_document = _read_json_file(args.results, "gate results")
            if set(results_document) != {"gates"} or not isinstance(
                results_document["gates"], dict
            ):
                raise CandidateError("Gate results shape is invalid.")
            report = build_gate_report(candidate, results_document["gates"])
            _write_document(args.output, report)
            print(gate_report_digest(report))
        elif args.command == "attestation-template":
            candidate = validate_candidate_identity(args.candidate.read_bytes())
            report = validate_gate_report(args.gate_report.read_bytes(), candidate)
            attestation = build_local_attestation_template(candidate, report)
            _write_document(args.output, attestation)
            print(hashlib.sha256(canonical_json_bytes(attestation)).hexdigest())
        elif args.command == "provider-attestation":
            candidate = validate_candidate_identity(args.candidate.read_bytes())
            report = validate_gate_report(args.gate_report.read_bytes(), candidate)
            observation_document = _read_json_file(args.observation_map, "observation map")
            if set(observation_document) != {"observations"} or not isinstance(
                observation_document["observations"], dict
            ):
                raise CandidateError("Provider attestation observation map shape is invalid.")
            attestation = build_provider_attestation(
                candidate,
                report,
                provider_name=args.provider,
                deployment_id=args.deployment_id,
                image_digest=args.image_digest,
                image_size_bytes=args.image_size_bytes,
                image_size_measurement_kind=args.image_size_measurement_kind,
                observation_to_evidence=observation_document["observations"],
            )
            _write_document(args.output, attestation)
            print(hashlib.sha256(canonical_json_bytes(attestation)).hexdigest())
        else:
            candidate = validate_candidate_identity(args.candidate.read_bytes())
            if args.kind == "candidate":
                print(candidate_identity_digest(candidate))
            else:
                if args.gate_report is None:
                    raise CandidateError("Gate report is required.")
                report = validate_gate_report(args.gate_report.read_bytes(), candidate)
                if args.kind == "gates":
                    print(gate_report_digest(report))
                else:
                    if args.attestation is None:
                        raise CandidateError("Deployment Attestation is required.")
                    attestation = validate_deployment_attestation(
                        args.attestation.read_bytes(), candidate, report
                    )
                    print(hashlib.sha256(canonical_json_bytes(attestation)).hexdigest())
    except (CandidateError, PublicReleaseConfigError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
