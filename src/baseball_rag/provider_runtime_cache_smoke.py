"""Offline provider-mode smoke for the prepared-cache hard-stop worker path."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import time
from collections.abc import Mapping
from typing import Any, cast

from baseball_rag.provider_runtime_cache import inspect_provider_runtime_cache
from baseball_rag.public_execution import ExecutionRequest, SubprocessExecutionRunner
from baseball_rag.public_release_config import (
    EXECUTION_DEADLINE_SECONDS,
    canonical_json_bytes,
    load_runtime_configuration,
)
from baseball_rag.release_runtime import release_readiness

SMOKE_SCHEMA_VERSION = "ground-ball-provider-runtime-cache-smoke-v3"
_CANONICAL_COLUMNS = ("player.name", "season", "batting.HR", "batting.SB")
_CANONICAL_CATALOG_REVISION = "published-query-catalog-v3"
_CANONICAL_DATA_RELEASE = "neuml-baseballdata:lahman-2025:2026-01-11"
_CANONICAL_SQL_SHA256 = "8cf16a156d1862a425150371ca69a29e9882f3adc9973a1c3ab085be6d4eed74"
_CANONICAL_RESULT_FINGERPRINT = "e87866bf1c3211159214d54076f4485a70c5feae7714da0e40af887e728e39c3"
_CANONICAL_ROWS = [
    {"player.name": "Jose Canseco", "season": 1988, "batting.HR": 42, "batting.SB": 40},
    {"player.name": "Barry Bonds", "season": 1996, "batting.HR": 42, "batting.SB": 40},
    {"player.name": "Alex Rodriguez", "season": 1998, "batting.HR": 42, "batting.SB": 46},
    {"player.name": "Alfonso Soriano", "season": 2006, "batting.HR": 46, "batting.SB": 41},
    {"player.name": "Ronald Acuña", "season": 2023, "batting.HR": 41, "batting.SB": 73},
    {"player.name": "Shohei Ohtani", "season": 2024, "batting.HR": 54, "batting.SB": 59},
]
_CANONICAL_SOURCES = [
    {
        "expected_rows": 128598,
        "identity": "Batting",
        "kind": "packaged_lahman_table",
        "release": _CANONICAL_DATA_RELEASE,
        "row_fingerprint": ("ee818d76adbb35e555f1520147dc064c04382c108d0c2bc3f59b18a3a2213e1a"),
        "sha256": "007551e2fe3072aff396a8573de61dceabe14dbf8de20038c8b60e2abe16978f",
    },
    {
        "expected_rows": 24270,
        "identity": "People",
        "kind": "packaged_lahman_table",
        "release": _CANONICAL_DATA_RELEASE,
        "row_fingerprint": ("3a222112cb582f48cd7ff917b292135fad288a6227357306860e4b0dabc7ca71"),
        "sha256": "a3c6b79e388b509ddbe4097ccf4026856b7fe07f4b3b41fbe3a8551b3f516c20",
    },
]
_CANONICAL_ORDERING = [
    {"direction": "ascending", "nulls": "last", "value": "season"},
    {"direction": "ascending", "nulls": "last", "value": "player.name"},
]
_CANONICAL_PREDICATE = {
    "kind": "all",
    "predicates": [
        {
            "kind": "compare",
            "literal": 40,
            "operator": "greater_or_equal",
            "value": "batting.HR",
        },
        {
            "kind": "compare",
            "literal": 40,
            "operator": "greater_or_equal",
            "value": "batting.SB",
        },
    ],
}
_CANONICAL_OUTPUT = {"kind": "interactive_page", "offset": 0, "size": 25}


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
    """Validate the full exact canonical 40-40 worker payload and image evidence."""
    document = _smoke_document(payload)
    if set(document) != {"identity", "query_proof", "schema_version", "status", "timing"}:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke shape is invalid.")
    if document.get("schema_version") != SMOKE_SCHEMA_VERSION or document.get("status") != "pass":
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke status is invalid.")

    _validate_identity(
        document.get("identity"),
        expected_source_commit=expected_source_commit,
        expected_release_bundle_digest=expected_release_bundle_digest,
        expected_runtime_configuration_digest=expected_runtime_configuration_digest,
    )
    _validate_timing(document.get("timing"))
    _validate_query_proof(document.get("query_proof"), expected_coverage=expected_coverage)
    return document


def build_provider_runtime_cache_smoke(
    *,
    worker_payload: Mapping[str, object],
    identity: Mapping[str, object],
    timing: Mapping[str, object],
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
    expected_coverage: Mapping[str, object],
) -> dict[str, object]:
    """Preserve observed worker material verbatim and validate it before publication."""
    document: dict[str, object] = {
        "identity": copy.deepcopy(dict(identity)),
        "query_proof": copy.deepcopy(dict(worker_payload)),
        "schema_version": SMOKE_SCHEMA_VERSION,
        "status": "pass",
        "timing": copy.deepcopy(dict(timing)),
    }
    return validate_provider_runtime_cache_smoke(
        document,
        expected_source_commit=expected_source_commit,
        expected_release_bundle_digest=expected_release_bundle_digest,
        expected_runtime_configuration_digest=expected_runtime_configuration_digest,
        expected_coverage=expected_coverage,
    )


def _validate_identity(
    value: object,
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "cache_metadata_sha256",
        "cache_reference",
        "database_sha256",
        "release_bundle_digest",
        "runtime_configuration_digest",
        "source_commit",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke identity is invalid.")
    if (
        value.get("source_commit") != expected_source_commit
        or value.get("release_bundle_digest") != expected_release_bundle_digest
        or value.get("runtime_configuration_digest") != expected_runtime_configuration_digest
        or not _commit(value.get("source_commit"))
        or any(
            not _digest(value.get(key))
            for key in (
                "cache_metadata_sha256",
                "cache_reference",
                "database_sha256",
                "release_bundle_digest",
                "runtime_configuration_digest",
            )
        )
        or value.get("cache_metadata_sha256") != value.get("cache_reference")
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke identity is invalid.")


def _validate_timing(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "activation_validation_seconds",
        "image_build_preparation_seconds",
        "worker_seconds",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke timing is invalid.")
    if any(not _nonnegative_finite(value.get(key)) for key in value) or not (
        float(value["worker_seconds"]) < EXECUTION_DEADLINE_SECONDS
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke timing is invalid.")


def _validate_query_proof(value: object, *, expected_coverage: Mapping[str, object]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "evidence",
        "kind",
        "pagination",
        "plan",
        "recipe",
        "returned_row_count",
        "rows",
        "total_matched_count",
        "verification",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke query proof is invalid.")
    recipe = value.get("recipe")
    plan = value.get("plan")
    rows = value.get("rows")
    if (
        not isinstance(recipe, dict)
        or not isinstance(plan, dict)
        or not isinstance(rows, list)
        or not _exact_json_equal(recipe, _canonical_recipe())
        or not _exact_json_equal(plan, _canonical_plan())
        or not _exact_json_equal(rows, _CANONICAL_ROWS)
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke canonical query is invalid.")
    recipe_columns = tuple(recipe["selections"])
    plan_columns = tuple(plan["selections"])
    row_columns = [set(row) for row in rows]
    if not (
        recipe_columns == plan_columns == _CANONICAL_COLUMNS
        and row_columns == [set(_CANONICAL_COLUMNS)] * 6
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke columns are invalid.")
    if not _exact_json_equal(
        {
            "kind": value.get("kind"),
            "pagination": value.get("pagination"),
            "returned_row_count": value.get("returned_row_count"),
            "total_matched_count": value.get("total_matched_count"),
        },
        {
            "kind": "rows",
            "pagination": {"has_more": False, "offset": 0, "size": 25},
            "returned_row_count": 6,
            "total_matched_count": 6,
        },
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke result envelope is invalid.")
    _validate_verification(value.get("verification"), expected_coverage=expected_coverage)
    _validate_evidence(value.get("evidence"), expected_coverage=expected_coverage)


def _validate_verification(value: object, *, expected_coverage: Mapping[str, object]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "coverage_report",
        "proof_id",
        "proof_identity",
        "reason",
        "status",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke verification is invalid.")
    if not _valid_expected_coverage(expected_coverage) or not _exact_json_equal(
        value,
        {
            "coverage_report": "/coverage-report",
            "proof_id": expected_coverage["proof_id"],
            "proof_identity": expected_coverage["proof_identity"],
            "reason": "Verified for this data release.",
            "status": "verified",
        },
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke verification is invalid.")


def _validate_evidence(value: object, *, expected_coverage: Mapping[str, object]) -> None:
    if not isinstance(value, dict) or set(value) != {
        "bound_values",
        "calculations",
        "catalog_revision",
        "data_release",
        "matched_row_count",
        "parameterized_sql",
        "result_fingerprint",
        "row_count",
        "sources",
    }:
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke QueryEvidence is invalid.")
    sql = value.get("parameterized_sql")
    proof_identity = expected_coverage.get("proof_identity")
    if not isinstance(proof_identity, dict):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke coverage identity is invalid.")
    expected_fingerprints = proof_identity.get("source_fingerprints")
    expected_evidence = {
        "bound_values": [40, 40],
        "calculations": [],
        "catalog_revision": _CANONICAL_CATALOG_REVISION,
        "data_release": _CANONICAL_DATA_RELEASE,
        "matched_row_count": 6,
        "parameterized_sql": sql,
        "result_fingerprint": _CANONICAL_RESULT_FINGERPRINT,
        "row_count": 6,
        "sources": _CANONICAL_SOURCES,
    }
    if (
        not isinstance(sql, str)
        or hashlib.sha256(sql.encode("utf-8")).hexdigest() != _CANONICAL_SQL_SHA256
        or not _exact_json_equal(value, expected_evidence)
        or proof_identity.get("catalog_revision") != _CANONICAL_CATALOG_REVISION
        or proof_identity.get("data_release") != _CANONICAL_DATA_RELEASE
        or not isinstance(expected_fingerprints, dict)
        or not _exact_json_equal(
            {identity: expected_fingerprints.get(identity) for identity in ("Batting", "People")},
            {source["identity"]: source["row_fingerprint"] for source in _CANONICAL_SOURCES},
        )
    ):
        raise ProviderRuntimeCacheSmokeError("Provider cache smoke QueryEvidence is invalid.")


def _canonical_recipe() -> dict[str, object]:
    return {
        "catalog_revision": None,
        "grain": "player-season",
        "groupings": [],
        "ordering": copy.deepcopy(_CANONICAL_ORDERING),
        "output": dict(_CANONICAL_OUTPUT),
        "predicate": copy.deepcopy(_CANONICAL_PREDICATE),
        "ranking": None,
        "selections": list(_CANONICAL_COLUMNS),
        "source": "Batting",
    }


def _canonical_plan() -> dict[str, object]:
    return {
        **_canonical_recipe(),
        "catalog_revision": _CANONICAL_CATALOG_REVISION,
        "relationships": ["people-to-batting"],
        "version": "query-plan-v1",
    }


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


def _valid_expected_coverage(value: Mapping[str, object]) -> bool:
    if set(value) != {"proof_id", "proof_identity"} or not _digest(value.get("proof_id")):
        return False
    identity = value.get("proof_identity")
    if not isinstance(identity, dict) or set(identity) != {
        "catalog_revision",
        "catalog_sha256",
        "compiler_contract",
        "compiler_sha256",
        "data_manifest_semantic_sha256",
        "data_release",
        "report_schema_version",
        "source_fingerprints",
    }:
        return False
    fingerprints = identity.get("source_fingerprints")
    return (
        identity.get("catalog_revision") == _CANONICAL_CATALOG_REVISION
        and identity.get("compiler_contract") == "query-plan-v1"
        and identity.get("data_release") == _CANONICAL_DATA_RELEASE
        and identity.get("report_schema_version") == "query-coverage-report-v1"
        and all(
            _digest(identity.get(key))
            for key in (
                "catalog_sha256",
                "compiler_sha256",
                "data_manifest_semantic_sha256",
            )
        )
        and isinstance(fingerprints, dict)
        and set(fingerprints) == {"Batting", "Fielding", "People", "Pitching", "TeamReference"}
        and all(_digest(item) for item in fingerprints.values())
    )


def _exact_json_equal(observed: object, expected: object) -> bool:
    """Compare JSON values without Python's bool/int/float equality aliases."""
    if type(observed) is not type(expected):
        return False
    if isinstance(expected, dict):
        observed_object = cast(dict[object, object], observed)
        return set(observed_object) == set(expected) and all(
            _exact_json_equal(observed_object[key], child) for key, child in expected.items()
        )
    if isinstance(expected, list):
        observed_array = cast(list[object], observed)
        return len(observed_array) == len(expected) and all(
            _exact_json_equal(left, right)
            for left, right in zip(observed_array, expected, strict=True)
        )
    return bool(observed == expected)


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
    """Activate the prebuilt cache, then preserve and validate the real 40-40 child."""
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
    coverage: dict[str, object] = {
        "proof_id": readiness.coverage_report["proof_id"],
        "proof_identity": readiness.coverage_report["proof_identity"],
    }
    return build_provider_runtime_cache_smoke(
        worker_payload=outcome.payload,
        identity={
            "cache_metadata_sha256": cache["cache_reference"],
            "cache_reference": cache["cache_reference"],
            "database_sha256": cache["database_sha256"],
            "release_bundle_digest": readiness.release_bundle_digest,
            "runtime_configuration_digest": configuration.digest,
            "source_commit": readiness.source_commit,
        },
        timing={
            "activation_validation_seconds": round(activation_seconds, 6),
            "image_build_preparation_seconds": cache["image_build_preparation_seconds"],
            "worker_seconds": round(worker_seconds, 6),
        },
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
