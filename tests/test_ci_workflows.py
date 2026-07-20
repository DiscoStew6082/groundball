"""Contracts for keeping ordinary CI fast and release proof exhaustive."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_fast_ci_does_not_regenerate_exhaustive_release_proof() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert '-m "not release_proof"' in workflow
    assert "not llm" not in workflow
    assert "python -m baseball_rag.coverage_proof_validator" in workflow
    assert "python -m baseball_rag.query.generate_coverage_report --check" not in workflow
    assert "--durations=20" in workflow
    assert "python scripts/check_provider_neutrality.py --root ." in workflow


def test_web_ci_checks_the_built_assets_against_the_packaged_fallback() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    web_job = workflow.split("  web-test:\n", 1)[1].split("\n  test:\n", 1)[0]

    assert web_job.index("npm run build") < web_job.index("npm run package:check")


def test_release_artifact_workflow_proves_exact_portable_artifacts() -> None:
    workflow = (ROOT / ".github/workflows/release-artifact-proof.yml").read_text(encoding="utf-8")

    required = (
        'artifact_parent_commit="$(git rev-parse HEAD^)"',
        'test "$artifact_parent_commit" = "$source_commit"',
        "git diff-tree --no-commit-id --name-only -r",
        "test -z \"$(grep -Ev '^release/bundle/'",
        "python -m baseball_rag.release_bundle check",
        "python -m baseball_rag.public_release_config --check",
        "python -m baseball_rag.query.generate_catalog_compatibility --check",
        "python -m baseball_rag.query.generate_raw_inventory --check",
        "python -m baseball_rag.query.generate_coverage_report --check",
        "python -m baseball_rag.query.eval_matrix",
        "npm run package:check",
        "uv build",
        "docker build",
        "--network none",
        "python -m baseball_rag.release_container_probe",
        "cmp release/proof/release-container-proof.json",
        'container_proof = Path("release/proof/release-container-proof.json")',
        "build_release_artifact",
        "python scripts/check_provider_neutrality.py --root .",
        "--artifact dist",
        "--artifact release/bundle",
        "--artifact release-artifacts",
    )
    assert all(item in workflow for item in required)

    forbidden = (
        "groundball_" + "ops",
        "secrets" + ".",
        "environment:",
        "deploy" + "ment",
        "protected" + "_",
        "GROUNDBALL_" + "BLOB",
        "Dockerfile." + "ver" + "cel",
    )
    assert all(item not in workflow for item in forbidden)


def test_release_proof_workflow_owns_exhaustive_regeneration() -> None:
    workflow = (ROOT / ".github/workflows/release-proof.yml").read_text(encoding="utf-8")

    assert '-m "release_proof"' in workflow
    assert "python -m baseball_rag.query.generate_coverage_report --check" in workflow
    assert "workflow_dispatch:" in workflow
    assert "src/baseball_rag/query/**" in workflow
