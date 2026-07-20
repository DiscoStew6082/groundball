from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
SOURCE_FILES = (ROOT / "generic_api.py", ROOT / "main.py", ROOT / "mlb_api.py")


def _configuration() -> dict[str, object]:
    with PYPROJECT.open("rb") as file:
        return tomllib.load(file)


def _requirement_name(requirement: str) -> str:
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
    assert match is not None, f"Cannot determine dependency name from {requirement!r}"
    return re.sub(r"[-_.]+", "-", match.group().lower())


def _runtime_imports() -> set[str]:
    imported: set[str] = set()
    for path in SOURCE_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.partition(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.add(node.module.partition(".")[0])
    return imported - sys.stdlib_module_names - {"generic_api", "mlb_api"}


def test_runtime_dependencies_exactly_match_direct_third_party_imports() -> None:
    configuration = _configuration()
    requirements = configuration["project"]["dependencies"]  # type: ignore[index]
    package_to_module = {"python-mlb-statsapi": "mlbstatsapi"}
    declared_modules = {
        package_to_module.get(name, name.replace("-", "_"))
        for name in map(_requirement_name, requirements)  # type: ignore[arg-type]
    }

    assert declared_modules == _runtime_imports()
    assert "fastapi" not in declared_modules
    assert "starlette" in declared_modules


def test_pytest_has_no_async_plugin_or_async_configuration() -> None:
    configuration = _configuration()
    test_requirements = configuration["project"]["optional-dependencies"]["test"]  # type: ignore[index]
    pytest_options = configuration["tool"]["pytest"]["ini_options"]  # type: ignore[index]

    assert "pytest-asyncio" not in map(_requirement_name, test_requirements)  # type: ignore[arg-type]
    assert not any(key.startswith("asyncio_") for key in pytest_options)


def test_pytest_enforces_strict_deprecation_and_future_warnings() -> None:
    configuration = _configuration()
    warning_filters = configuration["tool"]["pytest"]["ini_options"]["filterwarnings"]  # type: ignore[index]

    assert warning_filters == [
        "error::DeprecationWarning",
        "error::PendingDeprecationWarning",
        "error::FutureWarning",
    ]
    assert not any(filter_rule.startswith("ignore") for filter_rule in warning_filters)


def test_runtime_does_not_globally_suppress_warnings() -> None:
    main = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))

    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and (
            (isinstance(node, ast.Import) and any(alias.name == "warnings" for alias in node.names))
            or (isinstance(node, ast.ImportFrom) and node.module == "warnings")
        )
        for node in ast.walk(main)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "warnings"
        for node in ast.walk(main)
    )


def test_pre_commit_is_only_in_the_default_dev_dependency_group() -> None:
    configuration = _configuration()
    optional_dev = configuration["project"]["optional-dependencies"]["dev"]  # type: ignore[index]
    default_dev = configuration["dependency-groups"]["dev"]  # type: ignore[index]

    assert "pre-commit" not in map(_requirement_name, optional_dev)  # type: ignore[arg-type]
    assert list(map(_requirement_name, default_dev)).count("pre-commit") == 1  # type: ignore[arg-type]


def test_pre_commit_hook_revisions_are_current_and_match_the_lock() -> None:
    with (ROOT / "uv.lock").open("rb") as file:
        locked = {
            package["name"]: package["version"] for package in tomllib.load(file)["package"] if "version" in package
        }
    pre_commit = (ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")

    def revision(repository: str) -> str:
        block = pre_commit.split(f"repo: {repository}\n", 1)[1].split("\n  - repo:", 1)[0]
        match = re.search(r"^    rev: (\S+)$", block, re.MULTILINE)
        assert match is not None
        return match.group(1)

    assert revision("https://github.com/astral-sh/ruff-pre-commit") == f"v{locked['ruff']}"
    assert revision("https://github.com/pre-commit/pre-commit-hooks") == "v6.0.0"
