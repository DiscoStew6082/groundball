"""Read-only readiness Interface for one configured immutable Release Bundle."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from baseball_rag.query.coverage import load_passing_coverage_report
from baseball_rag.query.registry import CATALOG_DIR
from baseball_rag.query.runtime import published_data_runtime
from baseball_rag.release_bundle import ReleaseBundleError, configured_release_bundle_snapshot
from baseball_rag.retrosheet_event_capabilities import published_retrosheet_event_capabilities


@dataclass(frozen=True)
class ReleaseReadiness:
    """The exact checked identities and in-memory relations ready to serve."""

    release_bundle_digest: str
    source_commit: str
    data_release: str
    coverage_report: dict[str, Any]
    relations: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "release_bundle_digest": self.release_bundle_digest,
            "source_commit": self.source_commit,
            "data_release": self.data_release,
            "coverage_report": self.coverage_report,
            "duckdb": {"database": ":memory:", "relations": list(self.relations)},
        }


def release_readiness() -> ReleaseReadiness:
    """Fail closed unless the configured bundle, proof, and runtime agree exactly."""
    configured = os.environ.get("GROUNDBALL_RELEASE_BUNDLE")
    if not configured:
        raise ReleaseBundleError("GROUNDBALL_RELEASE_BUNDLE is required for release readiness.")
    expected_source_commit = os.environ.get("GROUNDBALL_SOURCE_COMMIT")
    if not expected_source_commit:
        raise ReleaseBundleError("GROUNDBALL_SOURCE_COMMIT is required for release readiness.")
    identity = configured_release_bundle_snapshot()
    assert identity is not None
    manifest = json.loads(identity.manifest_path.read_text(encoding="utf-8"))
    runtime = published_data_runtime()
    verified_root = identity.manifest_path.parent
    if (
        runtime.data_dir != verified_root / "data"
        or CATALOG_DIR != verified_root / "src/baseball_rag/query/catalog"
    ):
        raise ReleaseBundleError("Release runtime is not bound to the verified snapshot.")
    coverage = load_passing_coverage_report()
    relation_rows = runtime.connection.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' ORDER BY table_name"
    ).fetchall()
    relations = tuple(str(row[0]) for row in relation_rows)
    required_retrosheet = {
        capability.local_table for capability in published_retrosheet_event_capabilities()
    }
    if not required_retrosheet <= set(relations):
        raise ReleaseBundleError("Bundle-backed Retrosheet capability relation is unavailable.")
    return ReleaseReadiness(
        release_bundle_digest=identity.digest,
        source_commit=str(manifest["source_commit"]),
        data_release=runtime.data_release,
        coverage_report={
            "status": coverage["status"],
            "proof_id": coverage["proof_id"],
            "proof_identity": coverage["proof_identity"],
        },
        relations=relations,
    )
