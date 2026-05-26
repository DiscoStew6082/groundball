"""Architecture test status adapter for dashboard test badges."""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from baseball_rag.arch.components import ComponentRegistry, TestStatus

PYTEST_COMMAND = ("uv", "run", "pytest", "-q", "--tb=no")
_DEFAULT_REPO_ROOT = Path(__file__).parents[3]

COMPONENT_TEST_MAP: dict[str, tuple[str, ...]] = {
    "cli": ("tests/test_cli_player_query.py",),
    "query-router": (
        "tests/test_router.py",
        "tests/test_router_player_bio.py",
        "tests/test_router_player_detection.py",
    ),
    "claim-verifier": ("tests/test_player_bio_query.py",),
    "duckdb": ("tests/test_queries.py",),
    "llm": ("tests/test_llm.py",),
    "prompt": ("tests/test_generation.py",),
}


@dataclass(frozen=True)
class ArchitectureTestStatusResult:
    """Parsed pytest status for Architecture diagram components."""

    passed: int
    failed: int
    skipped: int = 0
    errors: int = 0
    component_statuses: dict[str, TestStatus] = field(default_factory=dict)
    missing_mapped_tests: dict[str, tuple[str, ...]] = field(default_factory=dict)
    failed_test_files: tuple[str, ...] = ()
    errored_test_files: tuple[str, ...] = ()


def collect_test_status(
    *,
    component_ids: Iterable[str],
    component_test_map: Mapping[str, Sequence[str]] = COMPONENT_TEST_MAP,
    repo_root: str | Path | None = None,
    timeout: int = 180,
) -> ArchitectureTestStatusResult:
    """Run pytest and return per-component Architecture test status."""

    root = _DEFAULT_REPO_ROOT if repo_root is None else Path(repo_root)
    completed = subprocess.run(
        list(PYTEST_COMMAND),
        capture_output=True,
        cwd=root,
        text=True,
        timeout=timeout,
    )
    output = f"{completed.stdout}{completed.stderr}"
    passed, failed, skipped, errors = _parse_summary_counts(output)
    failed_test_files = _parse_failed_test_files(output)
    errored_test_files = _parse_errored_test_files(output)
    missing_mapped_tests = _missing_mapped_tests(component_test_map, repo_root=root)
    runner_failed_without_test_files = (
        completed.returncode != 0
        and failed == 0
        and errors == 0
        and not failed_test_files
        and not errored_test_files
    )

    component_statuses = _component_statuses(
        component_ids=component_ids,
        component_test_map=component_test_map,
        missing_mapped_tests=missing_mapped_tests,
        failed_count=failed,
        error_count=errors,
        failed_test_files=failed_test_files,
        errored_test_files=errored_test_files,
        runner_failed_without_test_files=runner_failed_without_test_files,
    )

    return ArchitectureTestStatusResult(
        passed=passed,
        failed=failed,
        skipped=skipped,
        errors=errors,
        component_statuses=component_statuses,
        missing_mapped_tests=missing_mapped_tests,
        failed_test_files=tuple(sorted(failed_test_files)),
        errored_test_files=tuple(sorted(errored_test_files)),
    )


def apply_test_statuses(
    registry: ComponentRegistry,
    result: ArchitectureTestStatusResult,
) -> None:
    """Apply adapter statuses to registered Architecture components."""

    for component_id, status in result.component_statuses.items():
        registry.set_test_status(component_id, status)


def collect_and_apply_test_status(
    registry: ComponentRegistry,
    *,
    component_test_map: Mapping[str, Sequence[str]] = COMPONENT_TEST_MAP,
    repo_root: str | Path | None = None,
    timeout: int = 180,
) -> ArchitectureTestStatusResult:
    """Run pytest, compute statuses for *registry*, and apply them."""

    result = collect_test_status(
        component_ids=(component.id for component in registry.all()),
        component_test_map=component_test_map,
        repo_root=repo_root,
        timeout=timeout,
    )
    apply_test_statuses(registry, result)
    return result


def _parse_summary_counts(output: str) -> tuple[int, int, int, int]:
    passed = failed = skipped = errors = 0
    for line in output.splitlines():
        passed_match = re.search(r"(\d+)\s+passed", line)
        failed_match = re.search(r"(\d+)\s+failed", line)
        skipped_match = re.search(r"(\d+)\s+skipped", line)
        error_match = re.search(r"(\d+)\s+errors?", line)
        if passed_match:
            passed = int(passed_match.group(1))
        if failed_match:
            failed = int(failed_match.group(1))
        if skipped_match:
            skipped = int(skipped_match.group(1))
        if error_match:
            errors = int(error_match.group(1))
    return passed, failed, skipped, errors


def _parse_failed_test_files(output: str) -> set[str]:
    failed_files: set[str] = set()
    for line in output.splitlines():
        failed_match = re.search(r"\bFAILED\s+([^:\s]+\.py)(?:::|\s|$)", line)
        if failed_match:
            failed_files.add(_normalize_test_path(failed_match.group(1)))
            continue

        progress_match = re.search(r"([^:\s]+\.py)::[^\s]+.*\bFAILED\b", line)
        if progress_match:
            failed_files.add(_normalize_test_path(progress_match.group(1)))
    return failed_files


def _parse_errored_test_files(output: str) -> set[str]:
    errored_files: set[str] = set()
    for line in output.splitlines():
        error_match = re.search(r"\bERROR\s+([^:\s]+\.py)(?:::|\s+-|\s|$)", line)
        if error_match:
            errored_files.add(_normalize_test_path(error_match.group(1)))
    return errored_files


def _missing_mapped_tests(
    component_test_map: Mapping[str, Sequence[str]],
    *,
    repo_root: str | Path | None,
) -> dict[str, tuple[str, ...]]:
    root = _DEFAULT_REPO_ROOT if repo_root is None else Path(repo_root)
    missing: dict[str, tuple[str, ...]] = {}
    for component_id, test_paths in component_test_map.items():
        missing_paths = tuple(
            test_path for test_path in test_paths if not (root / test_path).exists()
        )
        if missing_paths:
            missing[component_id] = missing_paths
    return missing


def _component_statuses(
    *,
    component_ids: Iterable[str],
    component_test_map: Mapping[str, Sequence[str]],
    missing_mapped_tests: Mapping[str, Sequence[str]],
    failed_count: int,
    error_count: int,
    failed_test_files: set[str],
    errored_test_files: set[str],
    runner_failed_without_test_files: bool,
) -> dict[str, TestStatus]:
    statuses: dict[str, TestStatus] = {}
    mapped_ids = set(component_test_map)
    failures_are_mapped = bool(failed_test_files)
    suite_did_not_complete_cleanly = error_count > 0 or runner_failed_without_test_files

    for component_id in component_ids:
        if component_id not in mapped_ids or component_id in missing_mapped_tests:
            statuses[component_id] = TestStatus.UNKNOWN
            continue

        mapped_files = {
            _normalize_test_path(test_path) for test_path in component_test_map[component_id]
        }
        if mapped_files & (failed_test_files | errored_test_files):
            statuses[component_id] = TestStatus.FAIL
        elif suite_did_not_complete_cleanly:
            statuses[component_id] = TestStatus.UNKNOWN
        elif failed_count == 0 or failures_are_mapped:
            statuses[component_id] = TestStatus.PASS
        else:
            statuses[component_id] = TestStatus.UNKNOWN

    return statuses


def _normalize_test_path(test_path: str) -> str:
    return test_path.replace("\\", "/")
