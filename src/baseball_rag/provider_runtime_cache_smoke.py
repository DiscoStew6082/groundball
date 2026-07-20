"""Offline provider-mode smoke for the prepared-cache hard-stop worker path."""

from __future__ import annotations

import os
import time

from baseball_rag.provider_runtime_cache import (
    clear_provider_runtime_cache_reference,
    prepare_provider_runtime_cache,
)
from baseball_rag.public_execution import ExecutionRequest, SubprocessExecutionRunner
from baseball_rag.public_release_config import (
    EXECUTION_DEADLINE_SECONDS,
    canonical_json_bytes,
    load_runtime_configuration,
)
from baseball_rag.query.runtime import published_data_runtime
from baseball_rag.release_runtime import release_readiness

SMOKE_SCHEMA_VERSION = "ground-ball-provider-runtime-cache-smoke-v1"


def run_smoke() -> dict[str, object]:
    """Prepare one exact cache, then execute the real 40-40 child worker."""
    runtime_config_path = os.environ.get("GROUNDBALL_RUNTIME_CONFIG")
    if runtime_config_path is None:
        raise RuntimeError("Provider runtime configuration is required.")
    configuration = load_runtime_configuration(runtime_config_path)
    if not configuration.provider_deployment:
        raise RuntimeError("Provider runtime configuration is required.")

    clear_provider_runtime_cache_reference()
    prepare_started = time.monotonic()
    readiness = release_readiness()
    prepare_provider_runtime_cache(
        published_data_runtime(),
        source_commit=readiness.source_commit,
        release_bundle_digest=readiness.release_bundle_digest,
        runtime_configuration_digest=configuration.digest,
    )
    cache_prepare_seconds = time.monotonic() - prepare_started

    worker_started = time.monotonic()
    outcome = SubprocessExecutionRunner().run(
        ExecutionRequest(operation="query", question="40-40", recipe=None),
        timeout_seconds=float(EXECUTION_DEADLINE_SECONDS),
    )
    worker_seconds = time.monotonic() - worker_started
    if outcome.kind != "completed" or outcome.payload is None:
        raise RuntimeError("Prepared provider runtime-cache worker smoke failed.")
    rows = outcome.payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("Prepared provider runtime-cache worker smoke returned no rows.")
    return {
        "cache_prepare_seconds": round(cache_prepare_seconds, 6),
        "release_bundle_digest": readiness.release_bundle_digest,
        "rows": rows,
        "schema_version": SMOKE_SCHEMA_VERSION,
        "source_commit": readiness.source_commit,
        "status": "pass",
        "worker_seconds": round(worker_seconds, 6),
    }


def main() -> int:
    print(canonical_json_bytes(run_smoke()).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
