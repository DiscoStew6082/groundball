"""Contracts for keeping ordinary CI fast and release proof exhaustive."""

from pathlib import Path

from baseball_rag.release_candidate import MAX_CANDIDATE_IMAGE_SIZE_BYTES

ROOT = Path(__file__).resolve().parents[1]


def test_fast_ci_does_not_regenerate_exhaustive_release_proof() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '-m "not release_proof"' in workflow
    assert "not llm" not in workflow
    assert "python -m baseball_rag.coverage_proof_validator" in workflow
    assert "python -m baseball_rag.query.generate_coverage_report --check" not in workflow
    assert "--durations=20" in workflow


def test_web_ci_checks_the_built_assets_against_the_packaged_fallback() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    web_job = workflow.split("  web-test:\n", 1)[1].split("\n  test:\n", 1)[0]

    assert web_job.index("npm run build") < web_job.index("npm run package:check")


def test_release_proof_workflow_owns_exhaustive_regeneration() -> None:
    workflow = (ROOT / ".github/workflows/release-proof.yml").read_text(encoding="utf-8")

    assert '-m "release_proof"' in workflow
    assert "python -m baseball_rag.query.generate_coverage_report --check" in workflow
    assert "workflow_dispatch:" in workflow
    assert "src/baseball_rag/query/**" in workflow


def test_candidate_container_proof_is_branch_independent_and_exact_head() -> None:
    ordinary = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/candidate-proof.yml").read_text(encoding="utf-8")

    assert "implementation/public-deterministic-groundball'" not in ordinary
    assert "release-container:" not in ordinary
    automatic_trigger = workflow.split("on:\n", 1)[1].split("\nconcurrency:", 1)[0]
    assert automatic_trigger == (
        "  workflow_dispatch:\n"
        "  pull_request:\n"
        "    paths:\n"
        "      - 'release/bundle/release-manifest.json'\n"
    )
    assert "fetch-depth: 0" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "git rev-parse HEAD^" in workflow
    assert "release/bundle/release-manifest.json" in workflow
    assert "--network none" in workflow
    assert "docker image inspect" in workflow
    assert MAX_CANDIDATE_IMAGE_SIZE_BYTES == 1_073_741_824
    assert f'test "$image_size" -le {MAX_CANDIDATE_IMAGE_SIZE_BYTES}' in workflow
    assert f'"ceiling_bytes": {MAX_CANDIDATE_IMAGE_SIZE_BYTES}' in workflow
    assert "--build-arg GROUNDBALL_SOURCE_COMMIT" not in workflow
    assert '--env GROUNDBALL_SOURCE_COMMIT="$SOURCE_COMMIT"' in workflow
    assert "baseball_rag.provider_runtime_cache_smoke" in workflow
    assert "/app/release-config/protected-preview-runtime.json" in workflow
    assert "candidate-artifacts/evidence/provider-runtime-cache-smoke.json" in workflow
    assert "ground-ball-provider-runtime-cache-smoke-v3" in workflow
    assert 'test "$(id -u)" = 10001' in workflow
    assert 'test "$(id -g)" = 10001' in workflow
    assert "stat -c %u:%a:%h" in workflow
    assert "! chmod u+w" in workflow
    assert "! touch" in workflow
    assert "--network none" in workflow
    assert "baseball_rag.release_candidate assemble" in workflow
    assert "--gate-report-output candidate-artifacts/gate-report.json" in workflow
    assert (
        "--attestation-output candidate-artifacts/deployment-attestation-template.json" in workflow
    )
    assert "baseball_rag.release_candidate validate attestation" in workflow
    assert "if: always()" in workflow
    assert "actions/upload-artifact" in workflow
    assert "secrets." not in workflow


def test_candidate_image_contract_covers_fixed_config_and_fail_closed_boundaries() -> None:
    workflow = (ROOT / ".github/workflows/candidate-proof.yml").read_text(encoding="utf-8")

    assert (
        "GROUNDBALL_RUNTIME_CONFIG=/app/release-config/protected-preview-runtime.json" in workflow
    )
    assert "docker image inspect" in workflow and "Config.Env" in workflow
    assert "/usr/bin/env" in workflow and "-u GROUNDBALL_RUNTIME_CONFIG" in workflow
    assert "GROUNDBALL_RUNTIME_CONFIG=" in workflow
    assert "GROUNDBALL_RUNTIME_CONFIG=/tmp/foreign-runtime.json" in workflow
    assert "--tmpfs /app/provider-runtime-cache" in workflow
    assert "groundball-corrupt" in workflow
    assert 'printf "{}" > /app/provider-runtime-cache/pointer.json' in workflow
    assert 'docker exec -i "$container_name" /usr/bin/env' in workflow
    assert '"status":"failed"' in workflow
    assert '"operation":"query","question":"40-40"' in workflow
    assert '"operation":"unsupported"' in workflow
    assert "runtime.duckdb" in workflow


def test_candidate_workflow_labels_retained_cache_routines_truthfully() -> None:
    workflow = (ROOT / ".github/workflows/candidate-proof.yml").read_text(encoding="utf-8")

    assert '"runtime-cache-build-tools"' not in workflow
    assert '"runtime-cache-garbage-collection"' not in workflow
    assert '"present_but_denied_against_immutable_image_cache"' not in workflow
    assert '"root_only_retained_routines"' in workflow
    assert '"runtime-cache-builder-module"' in workflow
    assert '"runtime-cache-materialization-and-removal-routines"' in workflow
    assert "python -m baseball_rag.provider_runtime_cache" in workflow
    for entry_point in (
        "build_image_provider_runtime_cache",
        "build_provider_runtime_cache",
        "_materialize_cache",
        "_copy_database",
        "_acquire_build_lock",
        "_remove_build_tree",
        "_write_new_file",
        "_sync_file",
    ):
        assert f'"{entry_point}"' in workflow
    assert '"created": 0' in workflow
    assert '"removed": 0' in workflow
    assert '"modified": 0' in workflow
    assert 'Path("/tmp").rglob("*.duckdb")' in workflow
    assert "source Bundle/config path was read after UID denial" in workflow
    assert "USER 10001:10001" in (ROOT / "Dockerfile.vercel").read_text(encoding="utf-8")


def test_candidate_workflow_records_blocked_provider_gates() -> None:
    workflow = (ROOT / ".github/workflows/candidate-proof.yml").read_text(encoding="utf-8")

    assert '"protected_blob_coordination":{"evidence":[],"status":"blocked"}' in workflow
    assert '"provider_deployment_attestation":{"evidence":[],"status":"blocked"}' in workflow
    assert "local Docker evidence is not provider OCI proof" in workflow
