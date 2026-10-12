"""Distinguish source checks from strict artifact-only release proof."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

MANIFEST = "release/bundle/release-manifest.json"


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).rstrip("\n")


def inspect_topology(root: Path, base_commit: str = "") -> dict[str, object]:
    """Never claim an ordinary source or merge commit is a Release Artifact.

    Compare against the first parent, not the merge's other parents: an ordinary
    merge can retain the first parent's bundle while its older branch lacks it.
    Any new bundle bytes require the strict artifact-only, sole-parent contract.
    """
    head, *parents = git(root, "rev-list", "--parents", "-n", "1", "HEAD").split()
    if not parents:
        raise ValueError("Release proof requires a parent commit and full history.")
    paths = git(root, "diff", "--name-only", "--no-renames", "-z", parents[0], head)
    changed = paths.rstrip("\0").split("\0") if paths else []
    manifest = json.loads(git(root, "show", f"{head}:{MANIFEST}"))
    source = manifest.get("source_commit")
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("Bundle source must be an exact full commit SHA.")
    git(root, "merge-base", "--is-ancestor", source, head)
    artifact = any(path.startswith("release/bundle/") for path in changed)
    result: dict[str, object] = {
        "proof_kind": "artifact" if artifact else "source",
        "checked_commit": head,
        "bundle_source_commit": source,
    }
    if artifact:
        if parents != [source]:
            raise ValueError("Artifact must have its declared source as its sole direct parent.")
        if any(not path.startswith("release/bundle/") for path in changed):
            raise ValueError("Artifact commit may change only release/bundle/**.")
        if MANIFEST not in changed:
            raise ValueError("Artifact commit must update its Release Manifest.")
        if any(path.splitlines() != [path] for path in changed):
            raise ValueError("Artifact paths must be safe for line-delimited evidence.")
        if base_commit:
            if not re.fullmatch(r"[0-9a-f]{40}", base_commit):
                raise ValueError("PR base must be an exact full commit SHA.")
            git(root, "merge-base", "--is-ancestor", base_commit, source)
        result.update(artifact_commit=head, artifact_parent_commit=source, changed_paths=changed)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--base-commit", default="")
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--github-env", type=Path, required=True)
    args = parser.parse_args()
    result = inspect_topology(args.root, args.base_commit)
    args.evidence.mkdir(parents=True, exist_ok=True)
    (args.evidence / "proof-context.json").write_text(
        json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    variables = {
        "PROOF_KIND": result["proof_kind"],
        "SOURCE_COMMIT": result["bundle_source_commit"],
    }
    if result["proof_kind"] == "artifact":
        variables.update(
            ARTIFACT_COMMIT=result["artifact_commit"],
            ARTIFACT_PARENT_COMMIT=result["artifact_parent_commit"],
        )
        (args.evidence.parent / "artifact-changed-paths.txt").write_text(
            "\n".join(result["changed_paths"]) + "\n", encoding="utf-8"
        )
    with args.github_env.open("a", encoding="utf-8") as output:
        for key, value in variables.items():
            output.write(f"{key}={value}\n")


if __name__ == "__main__":
    main()
