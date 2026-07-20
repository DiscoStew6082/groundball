"""Canonical provider runtime-cache smoke evidence contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import pytest

from baseball_rag.public_release_config import load_runtime_configuration
from baseball_rag.public_results import run_public_query_input

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "release/bundle"
CONFIG = ROOT / "release/config/protected-preview-runtime.json"
SOURCE = json.loads((BUNDLE / "release-manifest.json").read_text(encoding="utf-8"))["source_commit"]
BUNDLE_DIGEST = hashlib.sha256((BUNDLE / "release-manifest.json").read_bytes()).hexdigest()
COVERAGE = json.loads(
    (BUNDLE / "src/baseball_rag/query/coverage/coverage-report.json").read_text(encoding="utf-8")
)


def _worker_payload() -> dict[str, object]:
    verified = {
        "coverage_report": "/coverage-report",
        "proof_id": COVERAGE["proof_id"],
        "proof_identity": copy.deepcopy(COVERAGE["proof_identity"]),
        "reason": "Verified for this data release.",
        "status": "verified",
    }
    with patch("baseball_rag.query.adapters.verification_payload", return_value=verified):
        payload = run_public_query_input(question="40-40")
    payload["verification"] = copy.deepcopy(verified)
    return payload


def _identity() -> dict[str, object]:
    return {
        "cache_metadata_sha256": "a" * 64,
        "cache_reference": "a" * 64,
        "database_sha256": "b" * 64,
        "release_bundle_digest": BUNDLE_DIGEST,
        "runtime_configuration_digest": load_runtime_configuration(CONFIG).digest,
        "source_commit": SOURCE,
    }


def _timing() -> dict[str, object]:
    return {
        "activation_validation_seconds": 0.125,
        "image_build_preparation_seconds": 2.5,
        "worker_seconds": 0.75,
    }


def _document() -> dict[str, object]:
    return {
        "identity": _identity(),
        "query_proof": _worker_payload(),
        "schema_version": "ground-ball-provider-runtime-cache-smoke-v3",
        "status": "pass",
        "timing": _timing(),
    }


def _validate(document: dict[str, object]) -> dict[str, object]:
    from baseball_rag.provider_runtime_cache_smoke import validate_provider_runtime_cache_smoke

    return validate_provider_runtime_cache_smoke(
        document,
        expected_source_commit=SOURCE,
        expected_release_bundle_digest=BUNDLE_DIGEST,
        expected_runtime_configuration_digest=load_runtime_configuration(CONFIG).digest,
        expected_coverage={
            "proof_id": COVERAGE["proof_id"],
            "proof_identity": copy.deepcopy(COVERAGE["proof_identity"]),
        },
    )


def test_canonical_provider_cache_smoke_accepts_the_full_observed_40_40_proof() -> None:
    assert _validate(_document()) == _document()


def test_smoke_builder_preserves_actual_worker_payload_without_expected_substitution() -> None:
    from baseball_rag.provider_runtime_cache_smoke import build_provider_runtime_cache_smoke

    observed = _worker_payload()
    document = build_provider_runtime_cache_smoke(
        worker_payload=observed,
        identity=_identity(),
        timing=_timing(),
        expected_source_commit=SOURCE,
        expected_release_bundle_digest=BUNDLE_DIGEST,
        expected_runtime_configuration_digest=load_runtime_configuration(CONFIG).digest,
        expected_coverage={
            "proof_id": COVERAGE["proof_id"],
            "proof_identity": copy.deepcopy(COVERAGE["proof_identity"]),
        },
    )

    assert document["query_proof"] == observed
    assert document["query_proof"] is not observed
    assert "outcome" not in document


Mutation = Callable[[dict[str, object]], None]


_EXACT_JSON_TYPE_MUTATIONS: tuple[tuple[str, Mutation], ...] = (
    (
        "recipe-output-float-for-int",
        lambda value: value["recipe"]["output"].__setitem__("offset", 0.0),
    ),
    (
        "recipe-predicate-bool-for-int",
        lambda value: value["recipe"]["predicate"]["predicates"][0].__setitem__("literal", True),
    ),
    ("plan-output-bool-for-int", lambda value: value["plan"]["output"].__setitem__("size", True)),
    (
        "plan-predicate-float-for-int",
        lambda value: value["plan"]["predicate"]["predicates"][1].__setitem__("literal", 40.0),
    ),
    ("row-float-for-int", lambda value: value["rows"][0].__setitem__("season", 1988.0)),
    ("row-bool-for-int", lambda value: value["rows"][0].__setitem__("batting.SB", True)),
    ("returned-count-float-for-int", lambda value: value.__setitem__("returned_row_count", 6.0)),
    ("matched-count-bool-for-int", lambda value: value.__setitem__("total_matched_count", True)),
    ("pagination-bool-for-int", lambda value: value["pagination"].__setitem__("offset", False)),
    ("pagination-int-for-bool", lambda value: value["pagination"].__setitem__("has_more", 0)),
    (
        "bound-value-float-for-int",
        lambda value: value["evidence"].__setitem__("bound_values", [40.0, 40]),
    ),
    (
        "evidence-row-count-float-for-int",
        lambda value: value["evidence"].__setitem__("row_count", 6.0),
    ),
    (
        "evidence-matched-count-bool-for-int",
        lambda value: value["evidence"].__setitem__("matched_row_count", True),
    ),
    (
        "source-expected-rows-float-for-int",
        lambda value: value["evidence"]["sources"][0].__setitem__("expected_rows", 128598.0),
    ),
)


@pytest.mark.parametrize("representation", ["mapping", "canonical-bytes"])
@pytest.mark.parametrize(
    ("_name", "mutation"),
    _EXACT_JSON_TYPE_MUTATIONS,
    ids=[item[0] for item in _EXACT_JSON_TYPE_MUTATIONS],
)
def test_exact_json_type_mutations_fail_at_direct_validator_seams(
    representation: str, _name: str, mutation: Mutation
) -> None:
    from baseball_rag.provider_runtime_cache_smoke import ProviderRuntimeCacheSmokeError
    from baseball_rag.public_release_config import canonical_json_bytes

    document = _document()
    mutation(document["query_proof"])
    payload: bytes | dict[str, object] = (
        canonical_json_bytes(document) if representation == "canonical-bytes" else document
    )

    with pytest.raises(ProviderRuntimeCacheSmokeError):
        if isinstance(payload, bytes):
            from baseball_rag.provider_runtime_cache_smoke import (
                validate_provider_runtime_cache_smoke,
            )

            validate_provider_runtime_cache_smoke(
                payload,
                expected_source_commit=SOURCE,
                expected_release_bundle_digest=BUNDLE_DIGEST,
                expected_runtime_configuration_digest=load_runtime_configuration(CONFIG).digest,
                expected_coverage={
                    "proof_id": COVERAGE["proof_id"],
                    "proof_identity": copy.deepcopy(COVERAGE["proof_identity"]),
                },
            )
        else:
            _validate(payload)


@pytest.mark.parametrize(
    ("_name", "mutation"),
    _EXACT_JSON_TYPE_MUTATIONS,
    ids=[item[0] for item in _EXACT_JSON_TYPE_MUTATIONS],
)
def test_smoke_builder_rejects_exact_json_type_mutations(_name: str, mutation: Mutation) -> None:
    from baseball_rag.provider_runtime_cache_smoke import (
        ProviderRuntimeCacheSmokeError,
        build_provider_runtime_cache_smoke,
    )

    worker_payload = _worker_payload()
    mutation(worker_payload)
    with pytest.raises(ProviderRuntimeCacheSmokeError):
        build_provider_runtime_cache_smoke(
            worker_payload=worker_payload,
            identity=_identity(),
            timing=_timing(),
            expected_source_commit=SOURCE,
            expected_release_bundle_digest=BUNDLE_DIGEST,
            expected_runtime_configuration_digest=load_runtime_configuration(CONFIG).digest,
            expected_coverage={
                "proof_id": COVERAGE["proof_id"],
                "proof_identity": copy.deepcopy(COVERAGE["proof_identity"]),
            },
        )


@pytest.mark.parametrize("key", list(_timing()))
def test_timing_fields_intentionally_accept_int_or_float_but_reject_bool(key: str) -> None:
    document = _document()
    document["timing"][key] = 1
    assert _validate(document) == document

    document["timing"][key] = True
    from baseball_rag.provider_runtime_cache_smoke import ProviderRuntimeCacheSmokeError

    with pytest.raises(ProviderRuntimeCacheSmokeError):
        _validate(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["recipe"]["selections"].reverse(),
        lambda value: value["recipe"].pop("selections"),
        lambda value: value["plan"]["selections"].reverse(),
        lambda value: value["plan"].pop("selections"),
        lambda value: value["plan"]["ordering"].reverse(),
        lambda value: value["recipe"]["predicate"]["predicates"].reverse(),
        lambda value: value["recipe"]["output"].__setitem__("size", 50),
        lambda value: value["rows"][0].__setitem__("unknown", 1),
        lambda value: value["rows"][0].pop("player.name"),
        lambda value: value["rows"].reverse(),
        lambda value: value["verification"].__setitem__("status", "unavailable"),
        lambda value: value["verification"].__setitem__("status", "unverified"),
        lambda value: value["verification"].__setitem__("proof_id", "6" * 64),
        lambda value: value["verification"]["proof_identity"].__setitem__(
            "catalog_revision", "foreign-catalog"
        ),
        lambda value: value["evidence"].__setitem__("catalog_revision", "foreign-catalog"),
        lambda value: value["evidence"].__setitem__("data_release", "foreign-release"),
        lambda value: value["evidence"].__setitem__("row_count", 5),
        lambda value: value["evidence"].__setitem__("matched_row_count", 5),
        lambda value: value["evidence"].__setitem__("result_fingerprint", "5" * 64),
        lambda value: value["evidence"].__setitem__("parameterized_sql", "SELECT 1"),
        lambda value: value["evidence"].__setitem__("bound_values", [40, 41]),
        lambda value: value["evidence"]["sources"][0].__setitem__("release", "foreign"),
        lambda value: value["evidence"]["sources"][0].__setitem__("sha256", "4" * 64),
        lambda value: value["evidence"]["sources"][0].__setitem__("row_fingerprint", "3" * 64),
        lambda value: value["evidence"].__setitem__("unknown", True),
        lambda value: value.__setitem__("unknown", True),
    ],
    ids=[
        "recipe-selections-reordered",
        "recipe-selections-missing",
        "plan-selections-reordered",
        "plan-selections-missing",
        "plan-ordering-reordered",
        "predicates-reordered",
        "output-drift",
        "row-key-extra",
        "row-key-missing",
        "rows-reordered",
        "verification-unavailable",
        "verification-unverified",
        "foreign-proof-id",
        "foreign-proof-identity",
        "catalog-revision",
        "data-release",
        "row-count",
        "matched-count",
        "result-fingerprint",
        "sql",
        "bound-values",
        "source-release",
        "source-hash",
        "source-row-fingerprint",
        "query-proof-unknown-field",
        "worker-payload-unknown-field",
    ],
)
def test_worker_payload_mutations_fail_closed(mutation: Mutation) -> None:
    from baseball_rag.provider_runtime_cache_smoke import ProviderRuntimeCacheSmokeError

    payload = _worker_payload()
    mutation(payload)
    document = _document()
    document["query_proof"] = payload

    with pytest.raises(ProviderRuntimeCacheSmokeError):
        _validate(document)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["identity"].__setitem__("source_commit", "9" * 40),
        lambda value: value["identity"].__setitem__("release_bundle_digest", "8" * 64),
        lambda value: value["identity"].__setitem__("runtime_configuration_digest", "7" * 64),
        lambda value: value["identity"].__setitem__("database_sha256", "bad"),
        lambda value: value["timing"].__setitem__("worker_seconds", 10.0),
        lambda value: value["timing"].__setitem__("activation_validation_seconds", math.nan),
        lambda value: value.__setitem__("status", "fail"),
        lambda value: value.__setitem__("unknown", True),
        lambda value: value.pop("query_proof"),
    ],
    ids=[
        "foreign-source",
        "foreign-bundle",
        "foreign-config",
        "malformed-digest",
        "deadline",
        "nonfinite-timing",
        "failed-status",
        "unknown-field",
        "missing-query-proof",
    ],
)
def test_smoke_evidence_document_mutations_fail_closed(mutation: Mutation) -> None:
    from baseball_rag.provider_runtime_cache_smoke import ProviderRuntimeCacheSmokeError

    document = _document()
    mutation(document)

    with pytest.raises(ProviderRuntimeCacheSmokeError):
        _validate(document)


def test_smoke_serialization_rejects_duplicate_and_noncanonical_fields() -> None:
    from baseball_rag.provider_runtime_cache_smoke import (
        ProviderRuntimeCacheSmokeError,
        validate_provider_runtime_cache_smoke,
    )
    from baseball_rag.public_release_config import canonical_json_bytes

    canonical = canonical_json_bytes(_document())
    duplicate = canonical.replace(b'{"identity":', b'{"identity":{},"identity":', 1)
    pretty = json.dumps(_document(), ensure_ascii=False, indent=2).encode("utf-8")
    arguments = {
        "expected_source_commit": SOURCE,
        "expected_release_bundle_digest": BUNDLE_DIGEST,
        "expected_runtime_configuration_digest": load_runtime_configuration(CONFIG).digest,
        "expected_coverage": {
            "proof_id": COVERAGE["proof_id"],
            "proof_identity": copy.deepcopy(COVERAGE["proof_identity"]),
        },
    }

    assert validate_provider_runtime_cache_smoke(canonical, **arguments) == _document()
    with pytest.raises(ProviderRuntimeCacheSmokeError):
        validate_provider_runtime_cache_smoke(pretty, **arguments)
    with pytest.raises(ProviderRuntimeCacheSmokeError):
        validate_provider_runtime_cache_smoke(
            duplicate,
            **arguments,
        )
