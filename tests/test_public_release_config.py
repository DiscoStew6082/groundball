from __future__ import annotations

import json
from pathlib import Path

import pytest

from baseball_rag.public_release_config import (
    PublicReleaseConfigError,
    admission_policy_document,
    check_admission_policy_artifact,
    load_runtime_configuration,
    validate_release_environment,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "release/config/public-admission-policy.json"
RUNTIME_PATH = ROOT / "release/config/local-ci-runtime.json"
PROTECTED_RUNTIME_PATH = ROOT / "release/config/protected-preview-runtime.json"


def test_generated_admission_policy_is_derived_from_enforced_constants() -> None:
    policy = admission_policy_document()

    assert policy == {
        "admission_charging": {"charged_before_execution": True, "refunded": False},
        "cas": {"maximum_attempts": 8},
        "concurrency": {"deployment": 4, "visitor": 1},
        "coordination_failures": {
            "contention_exhausted": "provider_unavailable",
            "invalid_state": "allowance_paused",
            "store_unavailable": "provider_unavailable",
        },
        "execution_deadline_seconds": 10,
        "lease_seconds": 15,
        "monthly_admitted_starts": 100,
        "question_characters": 500,
        "rate_limits": {
            "visitor_starts_per_hour": 12,
            "visitor_starts_per_minute": 3,
        },
        "request_body_bytes": 16_384,
        "schema_version": "ground-ball-public-admission-policy-v1",
        "shared_state": {
            "codec_schema_version": 1,
            "configuration_identity": "ground-ball-public-admission-state-v1",
        },
        "visitor_cookie": {
            "http_only": True,
            "minimum_keyed_digest_key_bytes": 32,
            "name": "groundball_visitor",
            "same_site": "lax",
            "secure": True,
        },
    }


def test_checked_in_policy_artifact_matches_the_actual_policy() -> None:
    assert check_admission_policy_artifact(POLICY_PATH) == admission_policy_document()


def test_release_environment_rejects_unknown_groundball_keys() -> None:
    validate_release_environment({"PATH": "/bin", "GROUNDBALL_PUBLIC_DEMO": "1"})
    with pytest.raises(PublicReleaseConfigError):
        validate_release_environment({"GROUNDBALL_UNKNOWN_PROOF": "true"})


def test_local_ci_runtime_configuration_is_strict_and_cannot_claim_deployment() -> None:
    config = load_runtime_configuration(RUNTIME_PATH)

    assert config.scope == "local_ci"
    assert config.provider_deployment is False
    assert config.admission_adapter == "local_ci_ephemeral"
    assert config.network_policy == "none"
    assert config.resource_references == ()
    assert config.startup_credential_references == ()
    assert config.request_credential_headers == ()
    assert config.secret_references == ()


def test_protected_preview_runtime_is_provider_scoped_secret_free_and_oidc_native() -> None:
    config = load_runtime_configuration(PROTECTED_RUNTIME_PATH)

    assert config.scope == "protected_preview"
    assert config.provider_deployment is True
    assert config.public_mode is True
    assert config.admission_adapter == "vercel_blob"
    assert config.network_policy == "provider_coordination_only"
    assert config.release_bundle == "ground-ball-release-bundle"
    assert config.resource_references == ("BLOB_STORE_ID",)
    assert config.startup_credential_references == ()
    assert config.request_credential_headers == ("x-vercel-oidc-token",)
    assert config.secret_references == ("GROUNDBALL_VISITOR_DIGEST_KEY",)
    encoded = PROTECTED_RUNTIME_PATH.read_text(encoding="utf-8")
    assert "=" not in encoded
    assert "Bearer " not in encoded


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value.update({"provider_deployment": True}),
        lambda value: value.update({"scope": "protected_preview"}),
        lambda value: value.update({"secret_references": ["SECRET=value"]}),
        lambda value: value.update({"request_credential_headers": ["x-vercel-oidc-token"]}),
        lambda value: value.update({"resource_references": ["BLOB_READ_WRITE_TOKEN"]}),
        lambda value: value.update({"startup_credential_references": ["VERCEL_OIDC_TOKEN"]}),
    ],
)
def test_runtime_configuration_fails_closed_on_unknown_or_masquerading_input(
    tmp_path: Path, mutation
) -> None:
    value = json.loads(RUNTIME_PATH.read_text(encoding="utf-8"))
    mutation(value)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(PublicReleaseConfigError):
        load_runtime_configuration(path)
