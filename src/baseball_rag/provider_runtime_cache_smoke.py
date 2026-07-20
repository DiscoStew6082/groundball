"""Offline provider-mode smoke for the prepared-cache hard-stop worker path."""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Mapping
from typing import Any

from baseball_rag.provider_runtime_cache import inspect_provider_runtime_cache
from baseball_rag.public_execution import ExecutionRequest, SubprocessExecutionRunner
from baseball_rag.public_release_config import (
    EXECUTION_DEADLINE_SECONDS,
    canonical_json_bytes,
    load_runtime_configuration,
)
from baseball_rag.release_runtime import release_readiness

SMOKE_SCHEMA_VERSION = "ground-ball-provider-runtime-cache-smoke-v2"
_EXPECTED_COLUMNS = ["player.name", "season", "batting.HR", "batting.SB"]
_EXPECTED_ROWS = [
    {"player.name": "Jose Canseco", "season": 1988, "batting.HR": 42, "batting.SB": 40},
    {"player.name": "Barry Bonds", "season": 1996, "batting.HR": 42, "batting.SB": 40},
    {"player.name": "Alex Rodriguez", "season": 1998, "batting.HR": 42, "batting.SB": 46},
    {"player.name": "Alfonso Soriano", "season": 2006, "batting.HR": 46, "batting.SB": 41},
    {"player.name": "Ronald Acuña", "season": 2023, "batting.HR": 41, "batting.SB": 73},
    {"player.name": "Shohei Ohtani", "season": 2024, "batting.HR": 54, "batting.SB": 59},
]


class ProviderRuntimeCacheSmokeError(ValueError):
    """Provider cache smoke evidence is malformed, foreign, or semantically false."""


def validate_provider_runtime_cache_smoke(
    payload: bytes | Mapping[str, object],
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
    expected_coverage: Mapping[str, object],
) -> dict[str, object]:
    """Validate one exact canonical 40-40 provider-cache smoke document."""
    document = _smoke_document(payload)
    if set(document) != {
        "coverage",
        "identity",
        "outcome",
        "schema_version",
        "status",
        "timing",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke shape is invalid.")
    if document.get("schema_version") != SMOKE_SCHEMA_VERSION or document.get("status") != "pass":
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke status is invalid.")

    identity = document.get("identity")
    if not isinstance(identity, dict) or set(identity) != {
        "cache_metadata_sha256",
        "cache_reference",
        "database_sha256",
        "release_bundle_digest",
        "runtime_configuration_digest",
        "source_commit",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke identity is invalid.")
    if (
        identity.get("source_commit") != expected_source_commit
        or identity.get("release_bundle_digest") != expected_release_bundle_digest
        or identity.get("runtime_configuration_digest") != expected_runtime_configuration_digest
        or not _commit(identity.get("source_commit"))
        or any(
            not _digest(identity.get(key))
            for key in (
                "cache_metadata_sha256",
                "cache_reference",
                "database_sha256",
                "release_bundle_digest",
                "runtime_configuration_digest",
            )
        )
        or identity.get("cache_metadata_sha256") != identity.get("cache_reference")
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke identity is invalid.")

    coverage = document.get("coverage")
    if (
        not isinstance(coverage, dict)
        or set(coverage) != {"proof_id", "proof_identity"}
        or not _digest(coverage.get("proof_id"))
        or coverage != dict(expected_coverage)
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke coverage identity is invalid.")

    timing = document.get("timing")
    if not isinstance(timing, dict) or set(timing) != {
        "activation_validation_seconds",
        "image_build_preparation_seconds",
        "worker_seconds",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke timing is invalid.")
    if any(not _nonnegative_finite(timing.get(key)) for key in timing) or not (
        float(timing["worker_seconds"]) < EXECUTION_DEADLINE_SECONDS
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke timing is invalid.")

    outcome = document.get("outcome")
    if not isinstance(outcome, dict) or set(outcome) != {
        "columns",
        "kind",
        "payload_kind",
        "returned_row_count",
        "rows",
        "total_matched_count",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke outcome is invalid.")
    if outcome != {
        "columns": _EXPECTED_COLUMNS,
        "kind": "completed",
        "payload_kind": "rows",
        "returned_row_count": 6,
        "rows": _EXPECTED_ROWS,
        "total_matched_count": 6,
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke 40-40 result is invalid.")
    return document


def _smoke_document(payload: bytes | Mapping[str, object]) -> dict[str, object]:
    if isinstance(payload, bytes):

        def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result: dict[str, Any] = {}
            for key, value in pairs:
                if key in result:
                    raise ProviderRuntimeCacheSmokeError(
                        "Provider cache smoke contains duplicate fields."
                    )
                result[key] = value
            return result

        try:
            value = json.loads(payload, object_pairs_hook=reject_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderRuntimeCacheSmokeError("Provider cache smoke is malformed.") from exc
        if not isinstance(value, dict) or canonical_json_bytes(value) != payload:
            raise ProviderRuntimeCacheSmokeError("Provider cache smoke is noncanonical.")
        return value
    return dict(payload)


def _digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _commit(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    )


def _nonnegative_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


def run_smoke() -> dict[str, object]:
    """Activate the prebuilt cache, then execute and validate the real 40-40 child."""
    runtime_config_path = os.environ.get("GROUNDBALL_RUNTIME_CONFIG")
    if runtime_config_path is None:
        raise RuntimeError("Provider runtime configuration is required.")
    configuration = load_runtime_configuration(runtime_config_path)
    if not configuration.provider_deployment:
        raise RuntimeError("Provider runtime configuration is required.")

    activation_started = time.monotonic()
    readiness = release_readiness()
    cache = inspect_provider_runtime_cache(
        expected_source_commit=readiness.source_commit,
        expected_release_bundle_digest=readiness.release_bundle_digest,
        expected_runtime_configuration_digest=configuration.digest,
    )
    activation_seconds = time.monotonic() - activation_started

    worker_started = time.monotonic()
    outcome = SubprocessExecutionRunner().run(
        ExecutionRequest(operation="query", question="40-40", recipe=None),
        timeout_seconds=float(EXECUTION_DEADLINE_SECONDS),
    )
    worker_seconds = time.monotonic() - worker_started
    if outcome.kind != "completed" or outcome.payload is None:
        raise RuntimeError("Prepared provider runtime-cache worker smoke failed.")
    payload = outcome.payload
    coverage: dict[str, object] = {
        "proof_id": readiness.coverage_report["proof_id"],
        "proof_identity": readiness.coverage_report["proof_identity"],
    }
    document: dict[str, object] = {
        "coverage": coverage,
        "identity": {
            "cache_metadata_sha256": cache["cache_reference"],
            "cache_reference": cache["cache_reference"],
            "database_sha256": cache["database_sha256"],
            "release_bundle_digest": readiness.release_bundle_digest,
            "runtime_configuration_digest": configuration.digest,
            "source_commit": readiness.source_commit,
        },
        "outcome": {
            "columns": list(_EXPECTED_COLUMNS),
            "kind": outcome.kind,
            "payload_kind": payload.get("kind"),
            "returned_row_count": payload.get("returned_row_count"),
            "rows": payload.get("rows"),
            "total_matched_count": payload.get("total_matched_count"),
        },
        "schema_version": SMOKE_SCHEMA_VERSION,
        "status": "pass",
        "timing": {
            "activation_validation_seconds": round(activation_seconds, 6),
            "image_build_preparation_seconds": cache["image_build_preparation_seconds"],
            "worker_seconds": round(worker_seconds, 6),
        },
    }
    return validate_provider_runtime_cache_smoke(
        document,
        expected_source_commit=readiness.source_commit,
        expected_release_bundle_digest=readiness.release_bundle_digest,
        expected_runtime_configuration_digest=configuration.digest,
        expected_coverage=coverage,
    )


def main() -> int:
    print(canonical_json_bytes(run_smoke()).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
