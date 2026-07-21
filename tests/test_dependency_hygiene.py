from __future__ import annotations

import ast
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SOURCE_ROOT = ROOT / "src/baseball_rag"


def _requirement_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    assert match is not None, f"Cannot determine dependency name from {requirement!r}"
    return re.sub(r"[-_.]+", "-", match.group().lower())


def _project_configuration() -> dict[str, object]:
    with PYPROJECT.open("rb") as file:
        return tomllib.load(file)


def _imported_runtime_modules() -> set[str]:
    imported: set[str] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.partition(".")[0])
    return imported - sys.stdlib_module_names - {"baseball_rag"}


def test_runtime_dependencies_exactly_match_direct_third_party_imports() -> None:
    configuration = _project_configuration()
    requirements = configuration["project"]["dependencies"]  # type: ignore[index]
    package_to_module = {"pyyaml": "yaml"}
    declared_modules = {
        package_to_module.get(name, name.replace("-", "_"))
        for name in map(_requirement_name, requirements)  # type: ignore[arg-type]
    }

    assert declared_modules == _imported_runtime_modules()


def test_testclient_uses_declared_httpx2_without_starlette_deprecation() -> None:
    configuration = _project_configuration()
    requirements = configuration["project"]["optional-dependencies"]["dev"]  # type: ignore[index]
    by_name = {_requirement_name(requirement): requirement for requirement in requirements}  # type: ignore[union-attr]

    assert "httpx" not in by_name
    assert by_name.get("httpx2") == "httpx2>=2.0.0"

    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import warnings; "
            "from starlette.exceptions import StarletteDeprecationWarning; "
            "warnings.simplefilter('error', StarletteDeprecationWarning); "
            "from fastapi.testclient import TestClient; "
            "import starlette.testclient as testclient; "
            "assert TestClient is testclient.TestClient; "
            "assert testclient.httpx.__name__ == 'httpx2'",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert probe.returncode == 0, probe.stderr


def test_pytest_treats_deprecations_and_future_warnings_as_errors() -> None:
    configuration = _project_configuration()

    assert configuration["tool"]["pytest"]["ini_options"]["filterwarnings"] == [  # type: ignore[index]
        "error::DeprecationWarning",
        "error::PendingDeprecationWarning",
        "error::FutureWarning",
        "error::starlette.exceptions.StarletteDeprecationWarning",
    ]


def test_declared_custom_pytest_markers_exactly_match_usage() -> None:
    configuration = _project_configuration()
    marker_entries = configuration["tool"]["pytest"]["ini_options"]["markers"]  # type: ignore[index]
    declared = {entry.partition(":")[0].strip() for entry in marker_entries}
    builtin_markers = {
        "filterwarnings",
        "parametrize",
        "skip",
        "skipif",
        "tryfirst",
        "trylast",
        "usefixtures",
        "xfail",
    }
    used: set[str] = set()
    for path in (ROOT / "tests").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Attribute)
                and isinstance(node.value.value, ast.Name)
                and node.value.value.id == "pytest"
                and node.value.attr == "mark"
                and node.attr not in builtin_markers
            ):
                used.add(node.attr)

    assert declared == used


def test_pre_commit_tool_revisions_match_root_lock() -> None:
    with (ROOT / "uv.lock").open("rb") as file:
        locked = {
            package["name"]: package["version"]
            for package in tomllib.load(file)["package"]
            if "version" in package
        }
    pre_commit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    for repository, package in (
        ("https://github.com/astral-sh/ruff-pre-commit", "ruff"),
        ("https://github.com/pre-commit/mirrors-mypy", "mypy"),
    ):
        repository_block = pre_commit.split(f"repo: {repository}\n", 1)[1].split("\n  - repo:", 1)[
            0
        ]
        revision = re.search(r"^    rev: (\S+)$", repository_block, re.MULTILINE)
        assert revision is not None
        assert revision.group(1) == f"v{locked[package]}"
