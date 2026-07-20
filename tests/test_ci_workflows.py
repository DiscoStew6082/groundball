"""Contracts for keeping ordinary CI fast and release proof exhaustive."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fast_ci_does_not_regenerate_exhaustive_release_proof() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '-m "not llm and not release_proof"' in workflow
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
