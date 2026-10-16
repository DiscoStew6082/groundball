"""Read-only readiness Interface for one configured immutable Release Bundle."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from baseball_rag.query.coverage import load_passing_coverage_report
from baseball_rag.query.registry import catalog_directory
from baseball_rag.query.runtime import published_data_runtime
from baseball_rag.release_bundle import ReleaseBundleError
from baseball_rag.release_context import (
    ReleaseContext,
    configured_release_context,
    install_release_context,
)
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


def release_readiness(context: ReleaseContext | None = None) -> ReleaseReadiness:
    """Fail closed unless the explicit bundle, proof, and runtime agree exactly."""
    if context is not None:
        install_release_context(context)
    else:
        context = configured_release_context()
    if context is None:
        raise ReleaseBundleError("GROUNDBALL_RELEASE_BUNDLE is required for release readiness.")
    runtime = published_data_runtime(context)
    if runtime.data_dir != context.data_dir or catalog_directory() != context.catalog_dir:
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
        release_bundle_digest=context.release_bundle_digest,
        source_commit=context.source_commit,
        data_release=runtime.data_release,
        coverage_report={
            "status": coverage["status"],
            "proof_id": coverage["proof_id"],
            "proof_identity": coverage["proof_identity"],
        },
        relations=relations,
    )
