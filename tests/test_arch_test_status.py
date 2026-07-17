"""Focused tests for the local architecture test-status adapter."""

from unittest.mock import MagicMock, patch

from baseball_rag.arch.components import TestStatus
from baseball_rag.arch.test_status import collect_test_status


def _test_file(tmp_path, name: str) -> None:
    path = tmp_path / "tests" / name
    path.parent.mkdir(exist_ok=True)
    path.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")


def test_reports_per_component_statuses_and_missing_mapped_tests(tmp_path) -> None:
    _test_file(tmp_path, "test_cli_player_query.py")
    fake_result = MagicMock(stdout="1 passed in 0.01s", stderr="", returncode=0)

    with patch("subprocess.run", return_value=fake_result):
        result = collect_test_status(
            component_ids=("cli", "query-router"),
            component_test_map={
                "cli": ["tests/test_cli_player_query.py"],
                "query-router": ["tests/test_missing_router.py"],
            },
            repo_root=tmp_path,
        )

    assert result.component_statuses == {
        "cli": TestStatus.PASS,
        "query-router": TestStatus.UNKNOWN,
    }
    assert result.missing_mapped_tests == {"query-router": ("tests/test_missing_router.py",)}


def test_reports_failures_per_component_from_pytest_output(tmp_path) -> None:
    _test_file(tmp_path, "test_cli_player_query.py")
    _test_file(tmp_path, "test_router.py")
    fake_result = MagicMock(
        stdout="tests/test_router.py::test_router FAILED\n1 failed, 1 passed in 0.01s",
        stderr="",
        returncode=1,
    )

    with patch("subprocess.run", return_value=fake_result):
        result = collect_test_status(
            component_ids=("cli", "query-router"),
            component_test_map={
                "cli": ["tests/test_cli_player_query.py"],
                "query-router": ["tests/test_router.py"],
            },
            repo_root=tmp_path,
        )

    assert result.component_statuses == {
        "cli": TestStatus.PASS,
        "query-router": TestStatus.FAIL,
    }
    assert result.failed_test_files == ("tests/test_router.py",)


def test_reports_collection_errors_without_false_passes(tmp_path) -> None:
    _test_file(tmp_path, "test_cli_player_query.py")
    _test_file(tmp_path, "test_router.py")
    fake_result = MagicMock(
        stdout="ERROR tests/test_router.py - ImportError: boom\n1 error in 0.01s",
        stderr="",
        returncode=2,
    )

    with patch("subprocess.run", return_value=fake_result):
        result = collect_test_status(
            component_ids=("cli", "query-router"),
            component_test_map={
                "cli": ["tests/test_cli_player_query.py"],
                "query-router": ["tests/test_router.py"],
            },
            repo_root=tmp_path,
        )

    assert result.component_statuses == {
        "cli": TestStatus.UNKNOWN,
        "query-router": TestStatus.FAIL,
    }
    assert result.errors == 1
    assert result.errored_test_files == ("tests/test_router.py",)


def test_runs_pytest_from_repo_root(tmp_path) -> None:
    _test_file(tmp_path, "test_cli_player_query.py")
    fake_result = MagicMock(stdout="1 passed in 0.01s", stderr="", returncode=0)

    with patch("subprocess.run", return_value=fake_result) as run:
        collect_test_status(
            component_ids=("cli",),
            component_test_map={"cli": ["tests/test_cli_player_query.py"]},
            repo_root=tmp_path,
        )

    assert run.call_args.kwargs["cwd"] == tmp_path
