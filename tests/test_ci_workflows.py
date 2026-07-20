"""Contracts for keeping ordinary CI fast and release proof exhaustive."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fast_ci_does_not_regenerate_exhaustive_release_proof() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '-m "not llm and not release_proof"' in workflow
    assert "python -m baseball_rag.coverage_proof_validator" in workflow
    assert "python -m baseball_rag.query.generate_coverage_report --check" not in workflow
    assert "--durations=20" in workflow


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
    assert "pull_request:" in workflow
    assert "fetch-depth: 0" in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "git rev-parse HEAD^" in workflow
    assert "release/bundle/release-manifest.json" in workflow
    assert "--network none" in workflow
    assert "docker image inspect" in workflow
    assert "1073741824" in workflow
    assert "baseball_rag.release_candidate assemble" in workflow
    assert "--gate-report-output candidate-artifacts/gate-report.json" in workflow
    assert (
        "--attestation-output candidate-artifacts/deployment-attestation-template.json" in workflow
    )
    assert "baseball_rag.release_candidate validate attestation" in workflow
    assert "if: always()" in workflow
    assert "actions/upload-artifact" in workflow
    assert "secrets." not in workflow


def test_candidate_workflow_records_blocked_provider_gates() -> None:
    workflow = (ROOT / ".github/workflows/candidate-proof.yml").read_text(encoding="utf-8")

    assert '"protected_blob_coordination":{"evidence":[],"status":"blocked"}' in workflow
    assert '"provider_deployment_attestation":{"evidence":[],"status":"blocked"}' in workflow
    assert "local Docker evidence is not provider OCI proof" in workflow
