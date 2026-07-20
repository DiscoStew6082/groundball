"""Canonical provider runtime-cache smoke evidence contracts."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "release/bundle"
CONFIG = ROOT / "release/config/protected-preview-runtime.json"
SOURCE = json.loads((BUNDLE / "release-manifest.json").read_text(encoding="utf-8"))["source_commit"]
BUNDLE_DIGEST = (
    __import__("hashlib").sha256((BUNDLE / "release-manifest.json").read_bytes()).hexdigest()
)
COVERAGE = json.loads(
    (BUNDLE / "src/baseball_rag/query/coverage/coverage-report.json").read_text(encoding="utf-8")
)
EXPECTED_ROWS = [
    {"player.name": "Jose Canseco", "season": 1988, "batting.HR": 42, "batting.SB": 40},
    {"player.name": "Barry Bonds", "season": 1996, "batting.HR": 42, "batting.SB": 40},
    {"player.name": "Alex Rodriguez", "season": 1998, "batting.HR": 42, "batting.SB": 46},
    {"player.name": "Alfonso Soriano", "season": 2006, "batting.HR": 46, "batting.SB": 41},
    {"player.name": "Ronald Acuña", "season": 2023, "batting.HR": 41, "batting.SB": 73},
    {"player.name": "Shohei Ohtani", "season": 2024, "batting.HR": 54, "batting.SB": 59},
]


def _document() -> dict[str, object]:
    from baseball_rag.public_release_config import load_runtime_configuration

    return {
        "coverage": {
            "proof_id": COVERAGE["proof_id"],
            "proof_identity": copy.deepcopy(COVERAGE["proof_identity"]),
        },
        "identity": {
            "cache_metadata_sha256": "a" * 64,
            "cache_reference": "a" * 64,
            "database_sha256": "b" * 64,
            "release_bundle_digest": BUNDLE_DIGEST,
            "runtime_configuration_digest": load_runtime_configuration(CONFIG).digest,
            "source_commit": SOURCE,
        },
        "outcome": {
            "columns": ["player.name", "season", "batting.HR", "batting.SB"],
            "kind": "completed",
            "payload_kind": "rows",
            "returned_row_count": 6,
            "rows": copy.deepcopy(EXPECTED_ROWS),
            "total_matched_count": 6,
        },
        "schema_version": "ground-ball-provider-runtime-cache-smoke-v2",
        "status": "pass",
        "timing": {
            "activation_validation_seconds": 0.125,
            "image_build_preparation_seconds": 2.5,
            "worker_seconds": 0.75,
        },
    }


def _validate(document: dict[str, object]) -> dict[str, object]:
    from baseball_rag.provider_runtime_cache_smoke import validate_provider_runtime_cache_smoke
    from baseball_rag.public_release_config import load_runtime_configuration

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


def test_canonical_provider_cache_smoke_accepts_only_the_exact_40_40_proof() -> None:
    assert _validate(_document()) == _document()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["outcome"]["rows"][0].__setitem__("batting.HR", 41),
        lambda value: value["outcome"]["rows"].reverse(),
        lambda value: value["outcome"].__setitem__("returned_row_count", 5),
        lambda value: value["outcome"].pop("columns"),
        lambda value: value["outcome"].__setitem__("unknown", True),
        lambda value: value["identity"].__setitem__("source_commit", "9" * 40),
        lambda value: value["identity"].__setitem__("release_bundle_digest", "8" * 64),
        lambda value: value["identity"].__setitem__("runtime_configuration_digest", "7" * 64),
        lambda value: value["identity"].__setitem__("database_sha256", "bad"),
        lambda value: value["timing"].__setitem__("worker_seconds", 10.0),
        lambda value: value["timing"].__setitem__("activation_validation_seconds", math.nan),
        lambda value: value["coverage"].__setitem__("proof_id", "6" * 64),
        lambda value: value["coverage"]["proof_identity"]["source_fingerprints"].__setitem__(
            "Batting", "5" * 64
        ),
        lambda value: value.__setitem__("status", "fail"),
    ],
    ids=[
        "wrong-row",
        "reordered-row",
        "count-mismatch",
        "missing-field",
        "unknown-field",
        "foreign-source",
        "foreign-bundle",
        "foreign-config",
        "malformed-digest",
        "deadline",
        "nonfinite-timing",
        "wrong-coverage-id",
        "wrong-source-fingerprint",
        "failed-status",
    ],
)
def test_provider_cache_smoke_mutations_fail_closed(mutation) -> None:
    from baseball_rag.provider_runtime_cache_smoke import ProviderRuntimeCacheSmokeError

    document = _document()
    mutation(document)

    with pytest.raises(ProviderRuntimeCacheSmokeError):
        _validate(document)
