"""Hard-deadline execution contract for admitted public Query Runs."""

from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import pytest

from baseball_rag.public_execution import (
    ExecutionRequest,
    SubprocessExecutionRunner,
    main,
)


def test_public_query_worker_applies_the_public_result_contract() -> None:
    outcome = SubprocessExecutionRunner().run(
        ExecutionRequest(operation="query", question="40-40", recipe=None),
        timeout_seconds=10,
    )

    assert outcome.kind == "completed"
    assert outcome.payload is not None
    assert outcome.payload["recipe"]["output"] == {
        "kind": "interactive_page",
        "size": 25,
        "offset": 0,
    }
    assert outcome.payload["returned_row_count"] == len(outcome.payload["rows"])


def test_public_query_worker_interprets_previous_recipe_context() -> None:
    first = SubprocessExecutionRunner().run(
        ExecutionRequest(
            operation="query",
            question="how many RBIs did Shohei Ohtani have in 2022",
            recipe=None,
        ),
        timeout_seconds=10,
    )
    assert first.kind == "completed"
    assert first.payload is not None

    follow_up = SubprocessExecutionRunner().run(
        ExecutionRequest(
            operation="query",
            question="what about his home runs in 2022?",
            recipe=None,
            previous_recipe=first.payload["recipe"],
        ),
        timeout_seconds=10,
    )

    assert follow_up.kind == "completed"
    assert follow_up.payload is not None
    assert follow_up.payload["recipe"]["selections"] == [
        "player.name",
        "season",
        "batting.HR",
    ]
    assert follow_up.payload["recipe"]["predicate"]["predicates"][0]["literal"] == ("Shohei Ohtani")


def test_subprocess_execution_returns_only_the_worker_envelope() -> None:
    runner = SubprocessExecutionRunner(
        command=(
            sys.executable,
            "-c",
            'print("{\\"kind\\":\\"completed\\",\\"payload\\":{\\"ok\\":true}}")',
        )
    )

    outcome = runner.run(
        ExecutionRequest(operation="query", question="question", recipe=None),
        timeout_seconds=1,
    )

    assert outcome.kind == "completed"
    assert outcome.payload == {"ok": True}
    assert outcome.detail is None


def test_timeout_terminates_and_reaps_work_instead_of_leaving_a_thread(
    tmp_path: Path,
) -> None:
    pid_path = tmp_path / "worker.pid"
    script = (
        "import os, pathlib, sys, time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    runner = SubprocessExecutionRunner(
        command=(sys.executable, "-c", script, str(pid_path)),
        termination_grace_seconds=0.1,
    )
    started = time.monotonic()

    outcome = runner.run(
        ExecutionRequest(operation="query", question="question", recipe=None),
        timeout_seconds=0.2,
    )

    assert outcome.kind == "timed_out"
    assert time.monotonic() - started < 2
    pid = int(pid_path.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_worker_eagerly_activates_provider_cache_before_parsing_unsupported_input(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []

    def unavailable() -> None:
        calls.append("activate")
        raise RuntimeError("sensitive cache path")

    class Input:
        buffer = io.BytesIO(b'{"operation":"unsupported"}')

    monkeypatch.setattr(
        "baseball_rag.provider_runtime_cache.require_provider_runtime_cache_for_worker",
        unavailable,
    )
    monkeypatch.setattr(sys, "stdin", Input())

    assert main() == 2
    assert calls == ["activate"]
    assert json.loads(capsys.readouterr().out) == {"kind": "failed"}


def test_failed_worker_never_exposes_sensitive_stderr() -> None:
    runner = SubprocessExecutionRunner(
        command=(
            sys.executable,
            "-c",
            'import sys; sys.stderr.write("sensitive internal detail"); raise SystemExit(2)',
        )
    )

    outcome = runner.run(
        ExecutionRequest(operation="retrosheet", question="question", recipe=None),
        timeout_seconds=1,
    )

    assert outcome.kind == "failed"
    assert outcome.detail == "Public Query Run execution failed."
    assert "sensitive" not in repr(outcome)
