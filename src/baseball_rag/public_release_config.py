"""Canonical, rendering-neutral public release policy and runtime configuration."""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping

POLICY_SCHEMA_VERSION = "ground-ball-public-admission-policy-v1"
RUNTIME_SCHEMA_VERSION = "ground-ball-runtime-configuration-v1"
SHARED_STATE_CONFIGURATION_IDENTITY = "ground-ball-public-admission-state-v1"
SHARED_STATE_SCHEMA_VERSION = 1
QUESTION_CHARACTER_LIMIT = 500
COMPLETE_REQUEST_BODY_BYTE_LIMIT = 16_384
VISITOR_CONCURRENCY_LIMIT = 1
DEPLOYMENT_CONCURRENCY_LIMIT = 4
VISITOR_STARTS_PER_MINUTE = 3
VISITOR_STARTS_PER_HOUR = 12
MONTHLY_START_LIMIT = 100
EXECUTION_DEADLINE_SECONDS = 10
LEASE_SECONDS = 15
MAXIMUM_CAS_ATTEMPTS = 8
VISITOR_COOKIE_NAME = "groundball_visitor"
VISITOR_COOKIE_SECURE = True
VISITOR_COOKIE_HTTP_ONLY = True
VISITOR_COOKIE_SAME_SITE: Literal["lax"] = "lax"
MINIMUM_VISITOR_DIGEST_KEY_BYTES = 32
_ALLOWED_RELEASE_ENVIRONMENT_KEYS = frozenset(
    {
        "GROUNDBALL_CORS_ORIGINS",
        "GROUNDBALL_DATA_DIR",
        "GROUNDBALL_PUBLIC_DEMO",
        "GROUNDBALL_RELEASE_BUNDLE",
        "GROUNDBALL_RUNTIME_CONFIG",
        "GROUNDBALL_SOURCE_COMMIT",
        "GROUNDBALL_WEB_APP_TTL_SECONDS",
        "GROUNDBALL_WEB_DIST",
    }
)


class PublicReleaseConfigError(ValueError):
    """A public release configuration is noncanonical or unsafe."""


class _DuplicateKeyError(ValueError):
    pass


@dataclass(frozen=True)
class RuntimeConfiguration:
    """Strict portable runtime identity consumed by local release startup."""

    scope: Literal["local_ci"]
    public_mode: Literal[True]
    network_policy: Literal["none"]
    release_bundle: Literal["ground-ball-release-bundle"]

    def as_dict(self) -> dict[str, object]:
        return {
            "network_policy": self.network_policy,
            "public_mode": self.public_mode,
            "release_bundle": self.release_bundle,
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "scope": self.scope,
        }

    @property
    def provider_deployment(self) -> Literal[False]:
        """Keep legacy local-mode readers fail-closed during the parser split."""
        return False

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json_bytes(self.as_dict())).hexdigest()


def validate_release_environment(environment: Mapping[str, str]) -> None:
    """Reject unknown Ground Ball keys before a configured release starts."""
    unknown = sorted(
        key
        for key in environment
        if key.startswith("GROUNDBALL_") and key not in _ALLOWED_RELEASE_ENVIRONMENT_KEYS
    )
    if unknown:
        raise PublicReleaseConfigError("Release environment contains unknown configuration keys.")


def admission_policy_document() -> dict[str, object]:
    """Return the canonical read model directly from enforced constants."""
    return {
        "admission_charging": {"charged_before_execution": True, "refunded": False},
        "cas": {"maximum_attempts": MAXIMUM_CAS_ATTEMPTS},
        "concurrency": {
            "deployment": DEPLOYMENT_CONCURRENCY_LIMIT,
            "visitor": VISITOR_CONCURRENCY_LIMIT,
        },
        "coordination_failures": {
            "contention_exhausted": "provider_unavailable",
            "invalid_state": "allowance_paused",
            "store_unavailable": "provider_unavailable",
        },
        "execution_deadline_seconds": EXECUTION_DEADLINE_SECONDS,
        "lease_seconds": LEASE_SECONDS,
        "monthly_admitted_starts": MONTHLY_START_LIMIT,
        "question_characters": QUESTION_CHARACTER_LIMIT,
        "rate_limits": {
            "visitor_starts_per_hour": VISITOR_STARTS_PER_HOUR,
            "visitor_starts_per_minute": VISITOR_STARTS_PER_MINUTE,
        },
        "request_body_bytes": COMPLETE_REQUEST_BODY_BYTE_LIMIT,
        "schema_version": POLICY_SCHEMA_VERSION,
        "shared_state": {
            "codec_schema_version": SHARED_STATE_SCHEMA_VERSION,
            "configuration_identity": SHARED_STATE_CONFIGURATION_IDENTITY,
        },
        "visitor_cookie": {
            "http_only": VISITOR_COOKIE_HTTP_ONLY,
            "minimum_keyed_digest_key_bytes": MINIMUM_VISITOR_DIGEST_KEY_BYTES,
            "name": VISITOR_COOKIE_NAME,
            "same_site": VISITOR_COOKIE_SAME_SITE,
            "secure": VISITOR_COOKIE_SECURE,
        },
    }


def canonical_json_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PublicReleaseConfigError("Configuration cannot be serialized canonically.") from exc


def check_admission_policy_artifact(path: Path | str) -> dict[str, object]:
    document, content = _load_canonical_object(path)
    expected = admission_policy_document()
    if document != expected or content != canonical_json_bytes(expected):
        raise PublicReleaseConfigError("Public Admission Policy artifact is stale.")
    return document


def write_admission_policy_artifact(path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(canonical_json_bytes(admission_policy_document()))


def load_runtime_configuration(path: Path | str) -> RuntimeConfiguration:
    document, _content = _load_canonical_object(path)
    required = {
        "network_policy",
        "public_mode",
        "release_bundle",
        "schema_version",
        "scope",
    }
    if set(document) != required or document.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise PublicReleaseConfigError("Runtime configuration shape is invalid.")
    scope = document.get("scope")
    public_mode = document.get("public_mode")
    network = document.get("network_policy")
    bundle = document.get("release_bundle")
    if (
        scope != "local_ci"
        or public_mode is not True
        or network != "none"
        or bundle != "ground-ball-release-bundle"
    ):
        raise PublicReleaseConfigError("Runtime configuration values are invalid.")
    return RuntimeConfiguration(
        scope=scope,
        public_mode=public_mode,
        network_policy=network,
        release_bundle=bundle,
    )


def _load_canonical_object(path: Path | str) -> tuple[dict[str, Any], bytes]:
    try:
        content = Path(path).read_bytes()
        document = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError, _DuplicateKeyError) as exc:
        raise PublicReleaseConfigError("Configuration JSON is malformed.") from exc
    if not isinstance(document, dict) or content != canonical_json_bytes(document):
        raise PublicReleaseConfigError("Configuration JSON is not a canonical object.")
    return document, content


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError
        result[key] = value
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        default=Path("release/config/public-admission-policy.json"),
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        check_admission_policy_artifact(args.artifact)
    else:
        write_admission_policy_artifact(args.artifact)
    print(hashlib.sha256(canonical_json_bytes(admission_policy_document())).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
