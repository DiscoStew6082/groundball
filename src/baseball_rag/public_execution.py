"""Hard-stop execution seam for admitted public deterministic queries."""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from typing import Any, Literal

Operation = Literal["query", "retrosheet"]


@dataclass(frozen=True)
class ExecutionRequest:
    operation: Operation
    question: str | None
    recipe: dict[str, Any] | None
    previous_recipe: dict[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionOutcome:
    kind: Literal["completed", "invalid", "timed_out", "failed"]
    payload: dict[str, Any] | None = None
    detail: str | None = None


class SubprocessExecutionRunner:
    """Execute in a child that can be terminated and reaped at the deadline."""

    def __init__(
        self,
        *,
        command: tuple[str, ...] | None = None,
        termination_grace_seconds: float = 0.5,
    ) -> None:
        self._command = command or (sys.executable, "-m", "baseball_rag.public_execution")
        self._termination_grace_seconds = termination_grace_seconds

    def run(self, request: ExecutionRequest, *, timeout_seconds: float) -> ExecutionOutcome:
        if timeout_seconds <= 0:
            return ExecutionOutcome("timed_out")
        encoded_request = json.dumps(
            {
                "operation": request.operation,
                "question": request.question,
                "recipe": request.recipe,
                "previous_recipe": request.previous_recipe,
            }
        ).encode("utf-8")
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed argv, never a shell command
                self._command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except OSError:
            return ExecutionOutcome("failed", detail="Public Query Run execution failed.")
        try:
            stdout, _ = process.communicate(encoded_request, timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self._kill_and_reap(process)
            return ExecutionOutcome("timed_out")
        except BaseException:
            self._terminate_and_reap(process)
            raise
        if process.returncode != 0:
            return ExecutionOutcome("failed", detail="Public Query Run execution failed.")
        return _decode_worker_outcome(stdout)

    @staticmethod
    def _kill_and_reap(process: subprocess.Popen[bytes]) -> None:
        if process.poll() is None:
            process.kill()
        process.communicate()

    def _terminate_and_reap(self, process: subprocess.Popen[bytes]) -> None:
        if process.poll() is not None:
            process.wait()
            return
        process.terminate()
        try:
            process.communicate(timeout=self._termination_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


def _decode_worker_outcome(stdout: bytes) -> ExecutionOutcome:
    try:
        envelope = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ExecutionOutcome("failed", detail="Public Query Run execution failed.")
    if not isinstance(envelope, dict):
        return ExecutionOutcome("failed", detail="Public Query Run execution failed.")
    kind = envelope.get("kind")
    if kind == "completed" and isinstance(envelope.get("payload"), dict):
        return ExecutionOutcome("completed", payload=envelope["payload"])
    if kind == "invalid" and isinstance(envelope.get("detail"), str):
        return ExecutionOutcome("invalid", detail=envelope["detail"])
    return ExecutionOutcome("failed", detail="Public Query Run execution failed.")


def _execute(request: ExecutionRequest) -> dict[str, Any]:
    try:
        if request.operation == "query":
            from baseball_rag.public_results import run_public_query_input

            payload = run_public_query_input(
                question=request.question,
                recipe=request.recipe,
                previous_recipe=request.previous_recipe,
            )
        else:
            from baseball_rag.retrosheet_query import execute_retrosheet_query

            if request.question is None:
                raise ValueError("A Retrosheet question is required.")
            payload = execute_retrosheet_query(request.question)
    except ValueError as exc:
        return {"kind": "invalid", "detail": str(exc)}
    except Exception:  # noqa: BLE001 - child errors become a non-sensitive public outcome
        return {"kind": "failed"}
    return {"kind": "completed", "payload": payload}


def main() -> int:
    try:
        raw_request = json.loads(sys.stdin.buffer.read())
        operation = raw_request["operation"]
        if operation not in {"query", "retrosheet"}:
            raise ValueError("Unknown public operation.")
        request = ExecutionRequest(
            operation=operation,
            question=raw_request.get("question"),
            recipe=raw_request.get("recipe"),
            previous_recipe=raw_request.get("previous_recipe"),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        print(json.dumps({"kind": "failed"}))
        return 2
    print(json.dumps(_execute(request), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
