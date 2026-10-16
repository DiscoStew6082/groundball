"""Explicit, independently verified release identity shared by one process.

Importing application modules performs no release selection. A composition root
constructs a context from trusted pins and installs it before runtime activation.
The environment reader is retained only for local CLI/offline-proof entrypoints.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Mapping

from baseball_rag.release_bundle import (
    ReleaseBundleError,
    ReleaseBundleIdentity,
    verified_release_bundle_snapshot,
)


@dataclass(frozen=True, init=False)
class ReleaseContext:
    """One verified, sealed snapshot and the identities required for readiness."""

    identity: ReleaseBundleIdentity
    source_commit: str
    data_release: str
    coverage_proof_id: str
    data_manifest_semantic_sha256: str
    source_fingerprints: tuple[tuple[str, str], ...]

    def __init__(
        self,
        bundle_root: Path | str,
        *,
        expected_source_commit: str,
        expected_digest: str,
    ) -> None:
        identity = verified_release_bundle_snapshot(
            bundle_root,
            expected_source_commit=expected_source_commit,
            expected_digest=expected_digest,
        )
        manifest = json.loads(identity.manifest_path.read_text(encoding="utf-8"))
        proof = manifest["identities"]["coverage_report"]
        object.__setattr__(self, "identity", identity)
        object.__setattr__(self, "source_commit", expected_source_commit)
        object.__setattr__(self, "data_release", manifest["identities"]["data_release"])
        object.__setattr__(self, "coverage_proof_id", proof["proof_id"])
        object.__setattr__(
            self,
            "data_manifest_semantic_sha256",
            proof["proof_identity"]["data_manifest_semantic_sha256"],
        )
        object.__setattr__(
            self,
            "source_fingerprints",
            tuple(sorted(proof["proof_identity"]["source_fingerprints"].items())),
        )

    @property
    def release_bundle_digest(self) -> str:
        return self.identity.digest

    @property
    def bundle_root(self) -> Path:
        return self.identity.manifest_path.parent

    @property
    def data_dir(self) -> Path:
        return self.bundle_root / "data"

    @property
    def catalog_dir(self) -> Path:
        return self.bundle_root / "src/baseball_rag/query/catalog"

    @property
    def coverage_report_path(self) -> Path:
        return self.bundle_root / "src/baseball_rag/query/coverage/coverage-report.json"


def verified_release_context(
    bundle_root: Path | str, *, expected_source_commit: str, expected_digest: str
) -> ReleaseContext:
    """Reuse identical pins/path spellings without replacing process identity."""
    with release_context_lock:
        return _verified_release_context(Path(bundle_root), expected_source_commit, expected_digest)


@lru_cache(maxsize=None)
def _verified_release_context(
    bundle_root: Path, expected_source_commit: str, expected_digest: str
) -> ReleaseContext:
    return ReleaseContext(
        bundle_root, expected_source_commit=expected_source_commit, expected_digest=expected_digest
    )


# The same lock also protects a registry read from racing its first activation.
release_context_lock = RLock()
_installed_context: ReleaseContext | None = None


def install_release_context(context: ReleaseContext) -> None:
    """Select one process-wide context; replacement requires a fresh process."""
    if not isinstance(context, ReleaseContext):
        raise TypeError("context must be a ReleaseContext.")
    global _installed_context
    with release_context_lock:
        if _installed_context is None:
            _installed_context = context
        elif _installed_context is not context:
            raise ReleaseBundleError("A different ReleaseContext is already installed.")


def release_context_from_environment(environment: Mapping[str, str]) -> ReleaseContext | None:
    """Read a legacy entrypoint's pins without mutating its environment or activating it."""
    configured = environment.get("GROUNDBALL_RELEASE_BUNDLE")
    if not configured:
        return None
    source = environment.get("GROUNDBALL_SOURCE_COMMIT")
    digest = environment.get("GROUNDBALL_RELEASE_BUNDLE_DIGEST")
    if not source or not digest:
        raise ReleaseBundleError(
            "GROUNDBALL_SOURCE_COMMIT and GROUNDBALL_RELEASE_BUNDLE_DIGEST are required."
        )
    return verified_release_context(
        configured, expected_source_commit=source, expected_digest=digest
    )


def installed_release_context() -> ReleaseContext | None:
    """Inspect process selection without reading configuration or selecting a release."""
    with release_context_lock:
        return _installed_context


def configured_release_context() -> ReleaseContext | None:
    """Use the installed context, or select legacy CLI configuration on first use."""
    with release_context_lock:
        if _installed_context is not None:
            return _installed_context
        context = release_context_from_environment(os.environ)
        if context is not None:
            install_release_context(context)
        return context
