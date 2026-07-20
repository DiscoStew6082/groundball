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


def test_release_environment_accepts_only_portable_application_keys() -> None:
    validate_release_environment(
        {
            "PATH": "/bin",
            "GROUNDBALL_CORS_ORIGINS": "http://localhost:4321",
            "GROUNDBALL_DATA_DIR": "/tmp/data",
            "GROUNDBALL_PUBLIC_DEMO": "1",
            "GROUNDBALL_RELEASE_BUNDLE": "/tmp/bundle",
            "GROUNDBALL_RUNTIME_CONFIG": "/tmp/runtime.json",
            "GROUNDBALL_SOURCE_COMMIT": "0" * 40,
            "GROUNDBALL_WEB_APP_TTL_SECONDS": "30",
            "GROUNDBALL_WEB_DIST": "/tmp/web",
        }
    )


@pytest.mark.parametrize(
    "unknown_key",
    [
        "GROUNDBALL_COORDINATION_MODE",
        "GROUNDBALL_REMOTE_RUNTIME",
    ],
)
def test_release_environment_rejects_nonportable_keys(unknown_key: str) -> None:
    with pytest.raises(
        PublicReleaseConfigError,
        match="Release environment contains unknown configuration keys",
    ):
        validate_release_environment({unknown_key: "configured"})


def test_local_ci_runtime_configuration_contains_only_portable_fields() -> None:
    config = load_runtime_configuration(RUNTIME_PATH)

    assert config.as_dict() == {
        "network_policy": "none",
        "public_mode": True,
        "release_bundle": "ground-ball-release-bundle",
        "schema_version": "ground-ball-runtime-configuration-v1",
        "scope": "local_ci",
    }
    assert config.scope == "local_ci"
    assert config.public_mode is True
    assert config.network_policy == "none"
    assert config.release_bundle == "ground-ball-release-bundle"
    assert len(config.digest) == 64


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"coordination": "shared"}),
        lambda value: value.update({"scope": "remote"}),
        lambda value: value.update({"public_mode": False}),
        lambda value: value.update({"network_policy": "outbound"}),
        lambda value: value.update({"release_bundle": "alternate"}),
        lambda value: value.update({"schema_version": "runtime-v2"}),
    ],
)
def test_runtime_configuration_fails_closed_on_unknown_or_nonlocal_content(
    tmp_path: Path, mutation
) -> None:
    value = {
        "network_policy": "none",
        "public_mode": True,
        "release_bundle": "ground-ball-release-bundle",
        "schema_version": "ground-ball-runtime-configuration-v1",
        "scope": "local_ci",
    }
    mutation(value)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")

    with pytest.raises(PublicReleaseConfigError, match="Runtime configuration"):
        load_runtime_configuration(path)


@pytest.mark.parametrize("encoding", ["pretty", "missing_newline", "duplicate_key"])
def test_runtime_configuration_requires_canonical_json(tmp_path: Path, encoding: str) -> None:
    value = {
        "network_policy": "none",
        "public_mode": True,
        "release_bundle": "ground-ball-release-bundle",
        "schema_version": "ground-ball-runtime-configuration-v1",
        "scope": "local_ci",
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    if encoding == "pretty":
        content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    elif encoding == "missing_newline":
        content = canonical.rstrip("\n")
    else:
        content = canonical.replace(
            '"scope":"local_ci"',
            '"scope":"local_ci","scope":"local_ci"',
        )
    path = tmp_path / "runtime.json"
    path.write_text(content)

    with pytest.raises(PublicReleaseConfigError, match="Configuration JSON"):
        load_runtime_configuration(path)
