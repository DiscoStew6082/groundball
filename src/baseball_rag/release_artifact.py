"""Canonical identity for one public Release Artifact."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

RELEASE_ARTIFACT_SCHEMA = "ground-ball-release-artifact-v2"
RELEASE_BUNDLE_MANIFEST_PATH = "release/bundle/release-manifest.json"

_FULL_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_FULL_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ARTIFACT_ID = re.compile(r"^gbra_[0-9a-f]{64}$")
_INTERFACE_REVISION = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")

_ARTIFACT_FIELDS = {
    "artifact_commit",
    "artifact_id",
    "public_admission_policy_digest",
    "public_interface_revision",
    "query_coverage_report_digest",
    "release_bundle_digest",
    "schema_version",
    "source_commit",
    "topology",
}
_TOPOLOGY_FIELDS = {"artifact_parent_commit", "changed_paths", "model"}
_DIGEST_FIELDS = (
    "public_admission_policy_digest",
    "query_coverage_report_digest",
    "release_bundle_digest",
)


class ReleaseArtifactError(ValueError):
    """The public Release Artifact is malformed, noncanonical, or mismatched."""


class _DuplicateKeyError(ValueError):
    pass


def validate_artifact_topology(
    *,
    source_commit: str,
    artifact_commit: str,
    artifact_parent_commit: str,
    changed_paths: Sequence[str],
) -> None:
    """Validate an exact source-then-Release-Bundle commit topology.

    Git discovery stays outside this module. Callers supply the full commits and
    the complete changed-path inventory reported for the artifact commit.
    """
    if (
        not _is_commit(source_commit)
        or not _is_commit(artifact_commit)
        or not _is_commit(artifact_parent_commit)
        or artifact_parent_commit != source_commit
        or artifact_commit == source_commit
    ):
        raise ReleaseArtifactError("Release Artifact commit topology is invalid.")
    if isinstance(changed_paths, (str, bytes)) or not isinstance(changed_paths, Sequence):
        raise ReleaseArtifactError("Release Artifact changed paths are invalid.")

    paths = list(changed_paths)
    if not paths or any(not _is_bundle_file_path(path) for path in paths):
        raise ReleaseArtifactError("Release Artifact changed paths are invalid.")
    if (
        paths != sorted(paths)
        or len(paths) != len(set(paths))
        or RELEASE_BUNDLE_MANIFEST_PATH not in paths
    ):
        raise ReleaseArtifactError("Release Artifact changed paths are invalid.")


def build_release_artifact(
    *,
    source_commit: str,
    artifact_commit: str,
    artifact_parent_commit: str,
    artifact_changed_paths: Sequence[str],
    release_bundle_digest: str,
    public_admission_policy_digest: str,
    query_coverage_report_digest: str,
    public_interface_revision: str,
) -> dict[str, object]:
    """Build the exact canonical public Release Artifact record."""
    validate_artifact_topology(
        source_commit=source_commit,
        artifact_commit=artifact_commit,
        artifact_parent_commit=artifact_parent_commit,
        changed_paths=artifact_changed_paths,
    )
    identities = {
        "public_admission_policy_digest": public_admission_policy_digest,
        "query_coverage_report_digest": query_coverage_report_digest,
        "release_bundle_digest": release_bundle_digest,
    }
    for field, value in identities.items():
        if not _is_sha256(value):
            raise ReleaseArtifactError(f"Release Artifact {field} is invalid.")
    if not _is_interface_revision(public_interface_revision):
        raise ReleaseArtifactError("Release Artifact public interface revision is invalid.")

    body: dict[str, object] = {
        "artifact_commit": artifact_commit,
        "public_admission_policy_digest": public_admission_policy_digest,
        "public_interface_revision": public_interface_revision,
        "query_coverage_report_digest": query_coverage_report_digest,
        "release_bundle_digest": release_bundle_digest,
        "schema_version": RELEASE_ARTIFACT_SCHEMA,
        "source_commit": source_commit,
        "topology": {
            "artifact_parent_commit": artifact_parent_commit,
            "changed_paths": list(artifact_changed_paths),
            "model": "source_then_release_bundle",
        },
    }
    artifact = {**body, "artifact_id": _artifact_id(body)}
    return validate_release_artifact(artifact)


def validate_release_artifact(
    payload: bytes | Mapping[str, object],
    *,
    expected_source_commit: str | None = None,
    expected_artifact_commit: str | None = None,
    expected_release_bundle_digest: str | None = None,
    expected_public_admission_policy_digest: str | None = None,
    expected_query_coverage_report_digest: str | None = None,
    expected_public_interface_revision: str | None = None,
) -> dict[str, object]:
    """Validate canonical bytes or a mapping and return a detached plain object."""
    document = _canonical_document(payload)
    if set(document) != _ARTIFACT_FIELDS:
        raise ReleaseArtifactError("Release Artifact shape is invalid.")
    if document.get("schema_version") != RELEASE_ARTIFACT_SCHEMA:
        raise ReleaseArtifactError("Release Artifact schema is invalid.")

    source_commit = document.get("source_commit")
    artifact_commit = document.get("artifact_commit")
    topology = document.get("topology")
    if not isinstance(topology, dict) or set(topology) != _TOPOLOGY_FIELDS:
        raise ReleaseArtifactError("Release Artifact topology shape is invalid.")
    if topology.get("model") != "source_then_release_bundle":
        raise ReleaseArtifactError("Release Artifact topology model is invalid.")
    changed_paths = topology.get("changed_paths")
    if not isinstance(changed_paths, list):
        raise ReleaseArtifactError("Release Artifact topology changed paths are invalid.")
    validate_artifact_topology(
        source_commit=source_commit,  # type: ignore[arg-type]
        artifact_commit=artifact_commit,  # type: ignore[arg-type]
        artifact_parent_commit=topology.get("artifact_parent_commit"),  # type: ignore[arg-type]
        changed_paths=changed_paths,
    )

    for field in _DIGEST_FIELDS:
        if not _is_sha256(document.get(field)):
            raise ReleaseArtifactError(f"Release Artifact {field} is invalid.")
    if not _is_interface_revision(document.get("public_interface_revision")):
        raise ReleaseArtifactError("Release Artifact public interface revision is invalid.")

    body = {key: value for key, value in document.items() if key != "artifact_id"}
    artifact_id = document.get("artifact_id")
    if (
        not isinstance(artifact_id, str)
        or _ARTIFACT_ID.fullmatch(artifact_id) is None
        or artifact_id != _artifact_id(body)
    ):
        raise ReleaseArtifactError("Release Artifact ID is malformed or stale.")

    expectations = {
        "source_commit": expected_source_commit,
        "artifact_commit": expected_artifact_commit,
        "release_bundle_digest": expected_release_bundle_digest,
        "public_admission_policy_digest": expected_public_admission_policy_digest,
        "query_coverage_report_digest": expected_query_coverage_report_digest,
        "public_interface_revision": expected_public_interface_revision,
    }
    for field, expected in expectations.items():
        if expected is not None and document[field] != expected:
            raise ReleaseArtifactError(
                f"Release Artifact {field} does not match required identity."
            )
    return document


def canonical_release_artifact_bytes(payload: bytes | Mapping[str, object]) -> bytes:
    """Return newline-terminated canonical JSON bytes for a valid artifact."""
    return _canonical_json_bytes(validate_release_artifact(payload))


def release_artifact_digest(payload: bytes | Mapping[str, object]) -> str:
    """Return the plain lowercase SHA-256 digest of the complete artifact record."""
    return hashlib.sha256(canonical_release_artifact_bytes(payload)).hexdigest()


def _artifact_id(body: Mapping[str, object]) -> str:
    return "gbra_" + hashlib.sha256(_canonical_json_bytes(body)).hexdigest()


def _canonical_document(payload: bytes | Mapping[str, object]) -> dict[str, object]:
    if isinstance(payload, bytes):
        try:
            document = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_object)
            canonical = _canonical_json_bytes(document)
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as error:
            raise ReleaseArtifactError("Release Artifact JSON is malformed.") from error
        if not isinstance(document, dict) or payload != canonical:
            raise ReleaseArtifactError("Release Artifact JSON is not canonical.")
        return document
    if not isinstance(payload, Mapping):
        raise ReleaseArtifactError("Release Artifact must be an object.")
    try:
        encoded = _canonical_json_bytes(dict(payload))
        document = json.loads(encoded, object_pairs_hook=_unique_object)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise ReleaseArtifactError("Release Artifact mapping is malformed.") from error
    if not isinstance(document, dict):
        raise ReleaseArtifactError("Release Artifact must be an object.")
    return document


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


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
    # Public artifact digests consistently use plain lowercase hexadecimal.
    return isinstance(value, str) and _FULL_SHA256.fullmatch(value) is not None


def _is_interface_revision(value: object) -> bool:
    return isinstance(value, str) and _INTERFACE_REVISION.fullmatch(value) is not None


def _is_bundle_file_path(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("release/bundle/"):
        return False
    if (
        value.endswith("/")
        or "\\" in value
        or "=" in value
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        return False
    parts = value.split("/")
    return all(part not in {"", ".", ".."} for part in parts)
