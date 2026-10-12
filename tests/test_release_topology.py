"""Exercise source/artifact routing against real Git history."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_release_topology.py"
spec = importlib.util.spec_from_file_location("check_release_topology", SCRIPT)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def write(root: Path, name: str, content: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def commit(root: Path, message: str) -> str:
    git(root, "add", ".")
    git(root, "commit", "-qm", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q", "-b", "main")
    git(tmp_path, "config", "user.email", "proof@example.invalid")
    git(tmp_path, "config", "user.name", "Proof Tests")
    write(tmp_path, "README.md", "Source\n")
    source = commit(tmp_path, "source")
    write(tmp_path, module.MANIFEST, json.dumps({"source_commit": source}))
    commit(tmp_path, "artifact")
    return tmp_path


def test_artifact_child_emits_exact_identity(repo: Path) -> None:
    result = module.inspect_topology(repo)
    assert result == {
        "proof_kind": "artifact",
        "checked_commit": git(repo, "rev-parse", "HEAD"),
        "bundle_source_commit": git(repo, "rev-parse", "HEAD^"),
        "artifact_commit": git(repo, "rev-parse", "HEAD"),
        "artifact_parent_commit": git(repo, "rev-parse", "HEAD^"),
        "changed_paths": [module.MANIFEST],
    }


def test_source_commit_does_not_claim_release_identity(repo: Path) -> None:
    write(repo, "README.md", "Source correction\n")
    commit(repo, "source correction")
    result = module.inspect_topology(repo)
    assert result["proof_kind"] == "source"
    assert "artifact_commit" not in result
    assert result["bundle_source_commit"] != result["checked_commit"]


def test_ordinary_merge_uses_first_parent_not_old_branch_bundle(repo: Path) -> None:
    # Feature branch predates the artifact. Main's merge retains its exact bundle.
    git(repo, "checkout", "-qb", "feature", "HEAD^")
    write(repo, "workflow.yml", "checks\n")
    commit(repo, "change workflow")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "--no-ff", "-qm", "merge workflow", "feature")
    assert module.inspect_topology(repo)["proof_kind"] == "source"


@pytest.mark.parametrize("kind", ["mixed", "wrong-source", "no-manifest", "merge"])
def test_malformed_artifact_changes_fail_closed(repo: Path, kind: str) -> None:
    source = git(repo, "rev-parse", "HEAD")
    if kind == "merge":
        git(repo, "checkout", "-qb", "artifact-branch")
    if kind != "no-manifest":
        declared = source if kind != "wrong-source" else git(repo, "rev-parse", "HEAD^")
        write(repo, module.MANIFEST, json.dumps({"source_commit": declared}))
    write(repo, "release/bundle/data.txt", "changed\n")
    if kind == "mixed":
        write(repo, "README.md", "mixed source\n")
    commit(repo, "invalid artifact")
    if kind == "merge":
        git(repo, "checkout", "-q", "main")
        git(repo, "merge", "--no-ff", "-qm", "merge artifact", "artifact-branch")
    with pytest.raises(ValueError):
        module.inspect_topology(repo)


def test_source_cli_writes_context_without_artifact_identity(repo: Path, tmp_path: Path) -> None:
    write(repo, "README.md", "Source correction\n")
    commit(repo, "source correction")
    evidence = tmp_path / "out/evidence"
    env = tmp_path / "env"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(repo),
            "--evidence",
            str(evidence),
            "--github-env",
            str(env),
        ],
        check=True,
    )
    assert "PROOF_KIND=source\n" in env.read_text()
    assert "ARTIFACT_COMMIT=" not in env.read_text()
    assert not (evidence.parent / "artifact-changed-paths.txt").exists()
    assert json.loads((evidence / "proof-context.json").read_text())["proof_kind"] == "source"


def test_artifact_pr_base_must_be_ancestor_of_source(repo: Path) -> None:
    assert (
        module.inspect_topology(repo, git(repo, "rev-parse", "HEAD^"))["proof_kind"] == "artifact"
    )
    with pytest.raises(subprocess.CalledProcessError):
        module.inspect_topology(repo, git(repo, "rev-parse", "HEAD"))


def test_artifact_cli_writes_exact_paths_and_commit(repo: Path, tmp_path: Path) -> None:
    evidence = tmp_path / "out/evidence"
    env = tmp_path / "env"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--root",
            str(repo),
            "--evidence",
            str(evidence),
            "--github-env",
            str(env),
        ],
        check=True,
    )
    assert "PROOF_KIND=artifact\n" in env.read_text()
    assert f"ARTIFACT_COMMIT={git(repo, 'rev-parse', 'HEAD')}\n" in env.read_text()
    assert (evidence.parent / "artifact-changed-paths.txt").read_text() == module.MANIFEST + "\n"


@pytest.mark.parametrize(
    "separator", ["\n", "\r", "\v", "\f", "\x1c", "\x1d", "\x1e", "\x85", "\u2028", "\u2029"]
)
def test_artifact_paths_cannot_forge_line_delimited_evidence(repo: Path, separator: str) -> None:
    source = git(repo, "rev-parse", "HEAD")
    write(repo, module.MANIFEST, json.dumps({"source_commit": source}))
    write(repo, f"release/bundle/a{separator}release/bundle/b", "forged inventory")
    commit(repo, "unsafe artifact path")
    with pytest.raises(ValueError, match="line-delimited"):
        module.inspect_topology(repo)
