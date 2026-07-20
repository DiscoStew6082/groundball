from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from baseball_rag.public_release_config import canonical_json_bytes
from baseball_rag.release_candidate import (
    MAX_CANDIDATE_IMAGE_SIZE_BYTES,
    PROVIDER_OBSERVATION_IDS,
    PROVIDER_OBSERVATION_SCHEMA_IDENTITIES,
    REQUIRED_GATE_IDS,
    CandidateError,
    EvidenceInput,
    build_candidate_identity,
    build_gate_report,
    build_local_attestation_template,
    build_provider_attestation,
    candidate_identity_digest,
    gate_report_digest,
    validate_artifact_topology,
    validate_candidate_identity,
    validate_deployment_attestation,
    validate_gate_report,
)
from baseball_rag.release_candidate import (
    main as release_candidate_main,
)

SOURCE = "1" * 40
ARTIFACT = "2" * 40
IMAGE = "sha256:" + "3" * 64
BUNDLE = "4" * 64
RUNTIME = "5" * 64
POLICY = "6" * 64


def _evidence(tmp_path: Path) -> tuple[EvidenceInput, ...]:
    inputs = []
    base_evidence = (
        ("coverage-report", "query-coverage-report-v1"),
        ("release-bundle-check", "ground-ball-release-bundle-check-v1"),
        ("container-proof", "ground-ball-candidate-container-proof-v1"),
    )
    provider_evidence = tuple(
        (f"provider-{observation}", schema)
        for observation, schema in PROVIDER_OBSERVATION_SCHEMA_IDENTITIES.items()
    )
    for logical_id, schema in (*base_evidence, *provider_evidence):
        path = tmp_path / f"{logical_id}.json"
        path.write_bytes(canonical_json_bytes({"schema_version": schema, "ok": True}))
        inputs.append(
            EvidenceInput(
                logical_id=logical_id,
                path=path,
                media_type="application/json",
                schema_identity=schema,
            )
        )
    return tuple(inputs)


def _candidate(
    tmp_path: Path,
    *,
    scope: str = "local_ci",
    image_size_bytes: int = 123_456,
    artifact_parent_commit: str = SOURCE,
    artifact_changed_paths: tuple[str, ...] = ("release/bundle/release-manifest.json",),
) -> dict[str, object]:
    return build_candidate_identity(
        scope=scope,
        source_commit=SOURCE,
        artifact_commit=ARTIFACT,
        artifact_parent_commit=artifact_parent_commit,
        artifact_changed_paths=artifact_changed_paths,
        bundle_digest=BUNDLE,
        image_digest=IMAGE,
        image_size_bytes=image_size_bytes,
        image_size_measurement_kind=(
            "docker-image-inspect-size-bytes"
            if scope == "local_ci"
            else "provider-oci-manifest-size-bytes"
        ),
        runtime_configuration_digest=RUNTIME,
        admission_policy_digest=POLICY,
        evidence_inputs=_evidence(tmp_path),
    )


def _all_pass_results() -> dict[str, dict[str, object]]:
    return {
        gate_id: {"status": "pass", "evidence": ["container-proof"]}
        for gate_id in REQUIRED_GATE_IDS
    }


def test_candidate_identity_is_canonical_deterministic_and_path_free(tmp_path: Path) -> None:
    first = _candidate(tmp_path)
    second = _candidate(tmp_path)

    assert first == second
    assert (
        first["candidate_id"]
        == "gbc_"
        + hashlib.sha256(
            canonical_json_bytes(
                {key: value for key, value in first.items() if key != "candidate_id"}
            )
        ).hexdigest()
    )
    encoded = canonical_json_bytes(first)
    assert str(tmp_path).encode() not in encoded
    assert (
        validate_candidate_identity(
            encoded,
            expected_source_commit=SOURCE,
            expected_artifact_commit=ARTIFACT,
            expected_bundle_digest=BUNDLE,
            expected_image_digest=IMAGE,
            expected_runtime_configuration_digest=RUNTIME,
            expected_admission_policy_digest=POLICY,
        )
        == first
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_commit", "1" * 12),
        ("bundle_digest", "sha256:" + "4" * 64),
        ("image_digest", "3" * 64),
        ("image_size_bytes", -1),
        ("image_size_bytes", True),
    ],
)
def test_candidate_rejects_malformed_identity_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    candidate = _candidate(tmp_path)
    candidate[field] = value

    with pytest.raises(CandidateError):
        validate_candidate_identity(canonical_json_bytes(candidate))


@pytest.mark.parametrize("scope", ["local_ci", "protected_preview", "production"])
@pytest.mark.parametrize("image_size_bytes", [0, 1_073_741_824])
def test_candidate_accepts_image_sizes_through_exact_one_gibibyte(
    tmp_path: Path, scope: str, image_size_bytes: int
) -> None:
    candidate = _candidate(tmp_path, scope=scope, image_size_bytes=image_size_bytes)

    assert candidate["image_size_bytes"] == image_size_bytes
    assert validate_candidate_identity(canonical_json_bytes(candidate)) == candidate
    assert MAX_CANDIDATE_IMAGE_SIZE_BYTES == 1_073_741_824


@pytest.mark.parametrize("scope", ["local_ci", "protected_preview", "production"])
@pytest.mark.parametrize("image_size_bytes", [1_073_741_825, -1, True])
def test_candidate_builder_rejects_image_sizes_outside_the_authoritative_limit(
    tmp_path: Path, scope: str, image_size_bytes: int
) -> None:
    with pytest.raises(CandidateError, match="image size"):
        _candidate(tmp_path, scope=scope, image_size_bytes=image_size_bytes)


@pytest.mark.parametrize("image_size_bytes", [1_073_741_825, -1, True])
def test_candidate_validator_rejects_image_sizes_outside_the_authoritative_limit(
    tmp_path: Path, image_size_bytes: object
) -> None:
    candidate = _candidate(tmp_path)
    candidate["image_size_bytes"] = image_size_bytes
    body = {key: value for key, value in candidate.items() if key != "candidate_id"}
    candidate["candidate_id"] = "gbc_" + hashlib.sha256(canonical_json_bytes(body)).hexdigest()

    with pytest.raises(CandidateError, match="image size"):
        validate_candidate_identity(canonical_json_bytes(candidate))


def test_candidate_rejects_duplicate_json_keys_unknown_fields_and_secret_content(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    encoded = canonical_json_bytes(candidate)
    duplicate = encoded.replace(
        b'{"admission_policy_digest"',
        b'{"scope":"local_ci","admission_policy_digest"',
    )
    with pytest.raises(CandidateError):
        validate_candidate_identity(duplicate)

    candidate["machine_path"] = "/tmp/candidate"
    with pytest.raises(CandidateError):
        validate_candidate_identity(canonical_json_bytes(candidate))

    candidate.pop("machine_path")
    candidate["evidence"][0]["logical_id"] = "token=secret-value"  # type: ignore[index]
    with pytest.raises(CandidateError):
        validate_candidate_identity(canonical_json_bytes(candidate))


def test_artifact_topology_requires_exact_parent_and_bundle_only_changes() -> None:
    validate_artifact_topology(
        source_commit=SOURCE,
        artifact_commit=ARTIFACT,
        artifact_parent_commit=SOURCE,
        changed_paths=[
            "release/bundle/data/manifest.json",
            "release/bundle/release-manifest.json",
        ],
    )

    with pytest.raises(CandidateError):
        validate_artifact_topology(
            source_commit=SOURCE,
            artifact_commit=ARTIFACT,
            artifact_parent_commit="9" * 40,
            changed_paths=["release/bundle/release-manifest.json"],
        )
    with pytest.raises(CandidateError):
        validate_artifact_topology(
            source_commit=SOURCE,
            artifact_commit=ARTIFACT,
            artifact_parent_commit=SOURCE,
            changed_paths=["release/bundle/release-manifest.json", "src/baseball_rag/app.py"],
        )


@pytest.mark.parametrize(
    ("artifact_parent_commit", "artifact_changed_paths"),
    [
        (
            SOURCE,
            (
                "release/bundle/release-manifest.json",
                "src/baseball_rag/release_candidate.py",
            ),
        ),
        (SOURCE, ("release/bundle/data/manifest.json",)),
        (
            SOURCE,
            (
                "release/bundle/release-manifest.json",
                "release/bundle/release-manifest.json",
            ),
        ),
        (SOURCE, ()),
        ("9" * 40, ("release/bundle/release-manifest.json",)),
    ],
)
def test_candidate_builder_validates_the_exact_artifact_inventory(
    tmp_path: Path,
    artifact_parent_commit: str,
    artifact_changed_paths: tuple[str, ...],
) -> None:
    with pytest.raises(CandidateError):
        _candidate(
            tmp_path,
            artifact_parent_commit=artifact_parent_commit,
            artifact_changed_paths=artifact_changed_paths,
        )


def test_candidate_rejects_duplicate_logical_evidence_and_topology_mismatch(tmp_path: Path) -> None:
    duplicate = (*_evidence(tmp_path), _evidence(tmp_path)[0])
    with pytest.raises(CandidateError):
        build_candidate_identity(
            scope="local_ci",
            source_commit=SOURCE,
            artifact_commit=ARTIFACT,
            artifact_parent_commit=SOURCE,
            artifact_changed_paths=("release/bundle/release-manifest.json",),
            bundle_digest=BUNDLE,
            image_digest=IMAGE,
            image_size_bytes=1,
            image_size_measurement_kind="docker-image-inspect-size-bytes",
            runtime_configuration_digest=RUNTIME,
            admission_policy_digest=POLICY,
            evidence_inputs=duplicate,
        )

    candidate = _candidate(tmp_path)
    candidate["topology"]["artifact_parent_commit"] = "7" * 40  # type: ignore[index]
    with pytest.raises(CandidateError):
        validate_candidate_identity(canonical_json_bytes(candidate))


@pytest.mark.parametrize(
    ("expected_name", "expected_value"),
    [
        ("expected_source_commit", "7" * 40),
        ("expected_artifact_commit", "7" * 40),
        ("expected_bundle_digest", "7" * 64),
        ("expected_image_digest", "sha256:" + "7" * 64),
        ("expected_runtime_configuration_digest", "7" * 64),
        ("expected_admission_policy_digest", "7" * 64),
    ],
)
def test_candidate_rejects_foreign_expected_identity(
    tmp_path: Path, expected_name: str, expected_value: str
) -> None:
    with pytest.raises(CandidateError):
        validate_candidate_identity(
            canonical_json_bytes(_candidate(tmp_path)), **{expected_name: expected_value}
        )


def test_all_pass_gate_report_is_eligible_and_deterministic(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    report = build_gate_report(candidate, _all_pass_results())

    assert report["eligible"] is True
    assert build_gate_report(candidate, _all_pass_results()) == report
    assert validate_gate_report(canonical_json_bytes(report), candidate) == report
    assert gate_report_digest(report) == hashlib.sha256(canonical_json_bytes(report)).hexdigest()


@pytest.mark.parametrize("status", ["blocked", "fail"])
def test_one_nonpassing_gate_prevents_eligibility(tmp_path: Path, status: str) -> None:
    candidate = _candidate(tmp_path)
    results = _all_pass_results()
    results[REQUIRED_GATE_IDS[0]] = {"status": status, "evidence": []}

    report = build_gate_report(candidate, results)

    assert report["eligible"] is False


@pytest.mark.parametrize("mutation", ["missing", "extra"])
def test_gate_inventory_must_be_exact(tmp_path: Path, mutation: str) -> None:
    results = _all_pass_results()
    if mutation == "missing":
        results.pop(REQUIRED_GATE_IDS[0])
    else:
        results["historical-proof"] = {"status": "pass", "evidence": ["container-proof"]}
    with pytest.raises(CandidateError):
        build_gate_report(_candidate(tmp_path), results)


def test_non_object_gate_result_fails_as_a_clean_cli_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    candidate_path = tmp_path / "candidate.json"
    results_path = tmp_path / "results.json"
    output_path = tmp_path / "report.json"
    candidate_path.write_bytes(canonical_json_bytes(_candidate(tmp_path)))
    results: dict[str, object] = _all_pass_results()
    results[REQUIRED_GATE_IDS[0]] = None
    results_path.write_bytes(canonical_json_bytes({"gates": results}))

    with pytest.raises(SystemExit) as raised:
        release_candidate_main(
            [
                "gates",
                "--candidate",
                str(candidate_path),
                "--results",
                str(results_path),
                "--output",
                str(output_path),
            ]
        )

    assert raised.value.code == 2
    captured = capsys.readouterr()
    assert "Gate result shape is invalid" in captured.err
    assert "Traceback" not in captured.err
    assert not output_path.exists()


def test_gate_report_rejects_duplicate_gates_missing_pass_evidence_and_foreign_candidate(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path)
    report = build_gate_report(candidate, _all_pass_results())
    report["gates"].append(report["gates"][0])  # type: ignore[union-attr,index]
    with pytest.raises(CandidateError):
        validate_gate_report(canonical_json_bytes(report), candidate)

    results = _all_pass_results()
    results[REQUIRED_GATE_IDS[0]] = {"status": "pass", "evidence": []}
    with pytest.raises(CandidateError):
        build_gate_report(candidate, results)

    report = build_gate_report(candidate, _all_pass_results())
    foreign = dict(candidate)
    foreign["candidate_id"] = "gbc_" + "9" * 64
    with pytest.raises(CandidateError):
        validate_gate_report(canonical_json_bytes(report), foreign)


def test_local_attestation_template_explicitly_records_no_deployment(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    results = _all_pass_results()
    results["protected_blob_coordination"] = {"status": "blocked", "evidence": []}
    report = build_gate_report(candidate, results)

    attestation = build_local_attestation_template(candidate, report)

    assert attestation["status"] == "template"
    assert attestation["deployment_exists"] is False
    assert attestation["promotion_eligible"] is False
    assert attestation["statement"] == "No provider deployment exists for this local CI candidate."
    assert attestation["gate_report_digest"] == gate_report_digest(report)
    assert attestation["candidate_identity_digest"] == candidate_identity_digest(candidate)
    assert (
        validate_deployment_attestation(canonical_json_bytes(attestation), candidate, report)
        == attestation
    )


def test_provider_attestation_builder_emits_exact_all_pass_candidate_binding(
    tmp_path: Path,
) -> None:
    candidate = _candidate(tmp_path, scope="protected_preview")
    report = build_gate_report(candidate, _all_pass_results())
    observations = {identity: f"provider-{identity}" for identity in PROVIDER_OBSERVATION_IDS}

    attestation = build_provider_attestation(
        candidate,
        report,
        provider_name="vercel",
        deployment_id="deployment-123",
        image_digest=IMAGE,
        image_size_bytes=123_456,
        image_size_measurement_kind="provider-oci-manifest-size-bytes",
        observation_to_evidence=observations,
    )

    assert attestation["status"] == "attested"
    assert attestation["provider"]["deployment_id"] == "deployment-123"  # type: ignore[index]
    assert attestation["observations"] == observations
    assert attestation["evidence"] == sorted(observations.values())
    assert (
        validate_deployment_attestation(canonical_json_bytes(attestation), candidate, report)
        == attestation
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        ("wrong_scope", "scope"),
        ("blocked_gate", "all-pass"),
        ("foreign_deployment", "deployment"),
        ("foreign_image", "image"),
        ("size_mismatch", "size"),
        ("size_overage", "size"),
        ("measurement", "measurement"),
        ("missing_observation", "observation"),
        ("foreign_evidence", "evidence"),
        ("secret_provider", "provider"),
    ],
)
def test_provider_attestation_builder_rejects_inexact_or_unsafe_input(
    tmp_path: Path, mutation: str, expected: str
) -> None:
    scope = "local_ci" if mutation == "wrong_scope" else "protected_preview"
    candidate = _candidate(tmp_path, scope=scope)
    results = _all_pass_results()
    if mutation == "blocked_gate":
        results["provider_peak_memory"] = {"status": "blocked", "evidence": []}
    report = build_gate_report(candidate, results)
    observations = {identity: f"provider-{identity}" for identity in PROVIDER_OBSERVATION_IDS}
    kwargs: dict[str, object] = {
        "provider_name": "vercel",
        "deployment_id": "deployment-123",
        "image_digest": candidate["image_digest"],
        "image_size_bytes": candidate["image_size_bytes"],
        "image_size_measurement_kind": candidate["image_size_measurement_kind"],
        "observation_to_evidence": observations,
    }
    if mutation == "foreign_deployment":
        kwargs["deployment_id"] = "foreign/deployment"
    elif mutation == "foreign_image":
        kwargs["image_digest"] = "sha256:" + "9" * 64
    elif mutation == "size_mismatch":
        kwargs["image_size_bytes"] = int(candidate["image_size_bytes"]) + 1
    elif mutation == "size_overage":
        kwargs["image_size_bytes"] = MAX_CANDIDATE_IMAGE_SIZE_BYTES + 1
    elif mutation == "measurement":
        kwargs["image_size_measurement_kind"] = "docker-image-inspect-size-bytes"
    elif mutation == "missing_observation":
        observations.pop(PROVIDER_OBSERVATION_IDS[0])
    elif mutation == "foreign_evidence":
        observations[PROVIDER_OBSERVATION_IDS[0]] = "foreign-evidence"
    elif mutation == "secret_provider":
        kwargs["provider_name"] = "token=secret"

    with pytest.raises(CandidateError, match=expected):
        build_provider_attestation(candidate, report, **kwargs)  # type: ignore[arg-type]


def test_provider_attestation_requires_every_external_observation(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, scope="protected_preview")
    report = build_gate_report(candidate, _all_pass_results())
    observations = {identity: f"provider-{identity}" for identity in PROVIDER_OBSERVATION_IDS}
    attestation = {
        "admission_policy_digest": candidate["admission_policy_digest"],
        "bundle_digest": candidate["bundle_digest"],
        "candidate_id": candidate["candidate_id"],
        "candidate_identity_digest": candidate_identity_digest(candidate),
        "deployment_exists": True,
        "evidence": sorted(observations.values()),
        "gate_report_digest": gate_report_digest(report),
        "image_digest": candidate["image_digest"],
        "observations": observations,
        "promotion_eligible": True,
        "provider": {
            "deployment_id": "deployment-123",
            "image_digest": candidate["image_digest"],
            "image_size_bytes": 123_456,
            "image_size_measurement_kind": "provider-oci-manifest-size-bytes",
            "name": "vercel",
        },
        "runtime_configuration_digest": candidate["runtime_configuration_digest"],
        "schema_version": "ground-ball-deployment-attestation-v1",
        "scope": "protected_preview",
        "statement": "Exact protected provider observations are attached.",
        "status": "attested",
    }
    assert (
        validate_deployment_attestation(canonical_json_bytes(attestation), candidate, report)
        == attestation
    )

    for field, value in (
        ("image_size_bytes", int(candidate["image_size_bytes"]) + 1),
        ("image_size_measurement_kind", "docker-image-inspect-size-bytes"),
    ):
        mismatched = {**attestation, "provider": {**attestation["provider"], field: value}}
        with pytest.raises(CandidateError):
            validate_deployment_attestation(canonical_json_bytes(mismatched), candidate, report)

    del attestation["observations"][PROVIDER_OBSERVATION_IDS[0]]
    with pytest.raises(CandidateError):
        validate_deployment_attestation(canonical_json_bytes(attestation), candidate, report)


def test_blocked_hobby_report_cannot_build_or_validate_attested_record(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path, scope="protected_preview")
    observations = {identity: f"provider-{identity}" for identity in PROVIDER_OBSERVATION_IDS}
    all_pass_report = build_gate_report(candidate, _all_pass_results())
    attestation = build_provider_attestation(
        candidate,
        all_pass_report,
        provider_name="vercel",
        deployment_id="deployment-123",
        image_digest=IMAGE,
        image_size_bytes=123_456,
        image_size_measurement_kind="provider-oci-manifest-size-bytes",
        observation_to_evidence=observations,
    )
    blocked_results = _all_pass_results()
    blocked_results["provider_peak_memory"] = {
        "status": "blocked",
        "evidence": ["provider-peak_memory"],
    }
    blocked_results["provider_deployment_attestation"] = {
        "status": "blocked",
        "evidence": ["provider-peak_memory"],
    }
    blocked_report = build_gate_report(candidate, blocked_results)

    with pytest.raises(CandidateError, match="all-pass"):
        build_provider_attestation(
            candidate,
            blocked_report,
            provider_name="vercel",
            deployment_id="deployment-123",
            image_digest=IMAGE,
            image_size_bytes=123_456,
            image_size_measurement_kind="provider-oci-manifest-size-bytes",
            observation_to_evidence=observations,
        )

    attestation["gate_report_digest"] = gate_report_digest(blocked_report)
    with pytest.raises(CandidateError):
        validate_deployment_attestation(
            canonical_json_bytes(attestation), candidate, blocked_report
        )


def test_attestation_rejects_candidate_gate_config_and_image_mismatches(tmp_path: Path) -> None:
    candidate = _candidate(tmp_path)
    report = build_gate_report(candidate, _all_pass_results())
    template = build_local_attestation_template(candidate, report)

    for field, value in (
        ("candidate_id", "gbc_" + "9" * 64),
        ("gate_report_digest", "9" * 64),
        ("runtime_configuration_digest", "9" * 64),
        ("admission_policy_digest", "9" * 64),
        ("image_digest", "sha256:" + "9" * 64),
    ):
        changed = dict(template)
        changed[field] = value
        with pytest.raises(CandidateError):
            validate_deployment_attestation(canonical_json_bytes(changed), candidate, report)
