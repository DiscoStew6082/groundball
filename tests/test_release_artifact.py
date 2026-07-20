from __future__ import annotations

import copy
import json

import pytest

from baseball_rag.release_artifact import (
    ReleaseArtifactError,
    build_release_artifact,
    canonical_release_artifact_bytes,
    release_artifact_digest,
    validate_artifact_topology,
    validate_release_artifact,
)

SOURCE = "1" * 40
ARTIFACT_COMMIT = "2" * 40
BUNDLE = "3" * 64
POLICY = "4" * 64
COVERAGE = "5" * 64
INTERFACE = "ground-ball-public-interface-v1"
CONTAINER_PROOF = "6" * 64
CHANGED_PATHS = (
    "release/bundle/data/manifest.json",
    "release/bundle/release-manifest.json",
)


def _artifact() -> dict[str, object]:
    return build_release_artifact(
        source_commit=SOURCE,
        artifact_commit=ARTIFACT_COMMIT,
        artifact_parent_commit=SOURCE,
        artifact_changed_paths=CHANGED_PATHS,
        release_bundle_digest=BUNDLE,
        public_admission_policy_digest=POLICY,
        query_coverage_report_digest=COVERAGE,
        public_interface_revision=INTERFACE,
        release_container_proof_digest=CONTAINER_PROOF,
    )


def test_builds_the_exact_canonical_public_artifact() -> None:
    artifact = _artifact()

    assert artifact == {
        "artifact_commit": ARTIFACT_COMMIT,
        "artifact_id": "gbra_60f598ce48c4da53b2e4057249f4652ff5d3d4549d2f0b8bfc3816e678688b5d",
        "public_admission_policy_digest": POLICY,
        "public_interface_revision": INTERFACE,
        "query_coverage_report_digest": COVERAGE,
        "release_bundle_digest": BUNDLE,
        "release_container_proof_digest": CONTAINER_PROOF,
        "schema_version": "ground-ball-release-artifact-v1",
        "source_commit": SOURCE,
        "topology": {
            "artifact_parent_commit": SOURCE,
            "changed_paths": list(CHANGED_PATHS),
            "model": "source_then_release_bundle",
        },
    }
    assert validate_release_artifact(canonical_release_artifact_bytes(artifact)) == artifact


def test_topology_accepts_exact_sorted_source_then_bundle_inventory() -> None:
    validate_artifact_topology(
        source_commit=SOURCE,
        artifact_commit=ARTIFACT_COMMIT,
        artifact_parent_commit=SOURCE,
        changed_paths=CHANGED_PATHS,
    )


@pytest.mark.parametrize(
    ("source", "artifact", "parent"),
    [
        ("1" * 39, ARTIFACT_COMMIT, SOURCE),
        (SOURCE, "2" * 39, SOURCE),
        (SOURCE, ARTIFACT_COMMIT, "9" * 40),
        (SOURCE, SOURCE, SOURCE),
        (True, ARTIFACT_COMMIT, SOURCE),
    ],
)
def test_topology_rejects_malformed_or_inexact_commits(
    source: object, artifact: object, parent: object
) -> None:
    with pytest.raises(ReleaseArtifactError, match="topology"):
        validate_artifact_topology(
            source_commit=source,  # type: ignore[arg-type]
            artifact_commit=artifact,  # type: ignore[arg-type]
            artifact_parent_commit=parent,  # type: ignore[arg-type]
            changed_paths=CHANGED_PATHS,
        )


@pytest.mark.parametrize(
    "paths",
    [
        (),
        ("release/bundle/release-manifest.json", "release/bundle/data/manifest.json"),
        (
            "release/bundle/release-manifest.json",
            "release/bundle/release-manifest.json",
        ),
        ("release/bundle/data/manifest.json",),
        ("release/bundle/release-manifest.json", "src/baseball_rag/app.py"),
        ("release/bundle/../secret.json", "release/bundle/release-manifest.json"),
        ("release/bundle/data/", "release/bundle/release-manifest.json"),
        ("release/bundle/data\\secret.json", "release/bundle/release-manifest.json"),
        "release/bundle/release-manifest.json",
    ],
)
def test_topology_rejects_noncanonical_changed_paths(paths: object) -> None:
    with pytest.raises(ReleaseArtifactError, match="changed paths"):
        validate_artifact_topology(
            source_commit=SOURCE,
            artifact_commit=ARTIFACT_COMMIT,
            artifact_parent_commit=SOURCE,
            changed_paths=paths,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("argument", "value"),
    [
        ("release_bundle_digest", "sha256:" + "3" * 64),
        ("public_admission_policy_digest", "4" * 63),
        ("query_coverage_report_digest", "G" * 64),
        ("release_container_proof_digest", True),
        ("public_interface_revision", ""),
        ("public_interface_revision", "/tmp/interface"),
        ("public_interface_revision", "to" + "ken=" + "se" + "cret"),
    ],
)
def test_builder_rejects_malformed_public_identity(argument: str, value: object) -> None:
    arguments: dict[str, object] = {
        "source_commit": SOURCE,
        "artifact_commit": ARTIFACT_COMMIT,
        "artifact_parent_commit": SOURCE,
        "artifact_changed_paths": CHANGED_PATHS,
        "release_bundle_digest": BUNDLE,
        "public_admission_policy_digest": POLICY,
        "query_coverage_report_digest": COVERAGE,
        "public_interface_revision": INTERFACE,
        "release_container_proof_digest": CONTAINER_PROOF,
    }
    arguments[argument] = value

    with pytest.raises(ReleaseArtifactError):
        build_release_artifact(**arguments)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "field",
    [
        "scope",
        "provider",
        "deployment_id",
        "image_digest",
        "gate_report",
        "attestation",
        "credentials",
    ],
)
def test_validator_rejects_nonpublic_and_unknown_content(field: str) -> None:
    artifact = _artifact()
    artifact[field] = "not-public"

    with pytest.raises(ReleaseArtifactError, match="shape"):
        validate_release_artifact(artifact)


def test_validator_rejects_missing_fields_and_unknown_topology_fields() -> None:
    missing = _artifact()
    missing.pop("query_coverage_report_digest")
    with pytest.raises(ReleaseArtifactError, match="shape"):
        validate_release_artifact(missing)

    unknown_topology = _artifact()
    topology = unknown_topology["topology"]
    assert isinstance(topology, dict)
    topology["directory"] = "release/bundle/"
    with pytest.raises(ReleaseArtifactError, match="topology"):
        validate_release_artifact(unknown_topology)


@pytest.mark.parametrize("mutation", ["duplicate", "pretty", "missing-newline"])
def test_validator_rejects_duplicate_keys_and_noncanonical_json_bytes(mutation: str) -> None:
    encoded = canonical_release_artifact_bytes(_artifact())
    if mutation == "duplicate":
        payload = encoded.replace(
            b'{"artifact_commit":',
            b'{"artifact_commit":"' + ARTIFACT_COMMIT.encode() + b'","artifact_commit":',
            1,
        )
    elif mutation == "pretty":
        payload = json.dumps(_artifact(), indent=2, sort_keys=True).encode()
    else:
        payload = encoded.rstrip(b"\n")

    with pytest.raises(ReleaseArtifactError):
        validate_release_artifact(payload)


def test_validator_rejects_stale_artifact_id() -> None:
    artifact = _artifact()
    artifact["artifact_id"] = "gbra_" + "9" * 64

    with pytest.raises(ReleaseArtifactError, match="stale"):
        validate_release_artifact(artifact)


@pytest.mark.parametrize(
    ("expectation", "foreign"),
    [
        ("expected_source_commit", "7" * 40),
        ("expected_artifact_commit", "7" * 40),
        ("expected_release_bundle_digest", "7" * 64),
        ("expected_public_admission_policy_digest", "7" * 64),
        ("expected_query_coverage_report_digest", "7" * 64),
        ("expected_public_interface_revision", "ground-ball-public-interface-v2"),
        ("expected_release_container_proof_digest", "7" * 64),
    ],
)
def test_validator_rejects_foreign_expected_bindings(expectation: str, foreign: str) -> None:
    with pytest.raises(ReleaseArtifactError, match="required identity"):
        validate_release_artifact(_artifact(), **{expectation: foreign})


def test_validation_copies_mapping_and_canonical_bytes_are_stable() -> None:
    supplied = _artifact()
    checked = validate_release_artifact(supplied)
    supplied["source_commit"] = "9" * 40

    assert checked["source_commit"] == SOURCE
    assert canonical_release_artifact_bytes(checked) == canonical_release_artifact_bytes(
        canonical_release_artifact_bytes(checked)
    )


def test_release_artifact_digest_hashes_the_validated_complete_record() -> None:
    artifact = _artifact()

    assert release_artifact_digest(artifact) == (
        "3991cc89fd8d61224df9ce50d8650ea039007ec85a67a1caeeac155dd13ce83a"
    )
    assert release_artifact_digest(canonical_release_artifact_bytes(artifact)) == (
        release_artifact_digest(artifact)
    )


def test_validator_rejects_boolean_and_path_values_in_exact_fields() -> None:
    for field, value in (
        ("public_interface_revision", True),
        ("release_bundle_digest", True),
    ):
        artifact = copy.deepcopy(_artifact())
        artifact[field] = value
        with pytest.raises(ReleaseArtifactError):
            validate_release_artifact(artifact)
