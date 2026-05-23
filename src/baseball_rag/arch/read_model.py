"""Pure read models for the Architecture Explorer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from baseball_rag.arch.tracing import PipelineTrace

StatusLevel = Literal["ok", "warning", "error"]
_SESSIONLESS_ARCHITECTURE_KEY = "__sessionless_architecture__"


@dataclass(frozen=True)
class LatestRunReadModel:
    """Rendering-neutral state for the last completed Architecture run."""

    question: str
    intent: str
    route: str
    warnings: tuple[str, ...] = ()
    unsupported: bool = False
    unsupported_reason: str | None = None
    sources: tuple[Any, ...] = ()
    trace: PipelineTrace | None = None
    active_component_ids: tuple[str, ...] = ()
    row_count: int = 0
    diagnostics: tuple[str, ...] = ()
    status_level: StatusLevel = "ok"
    status_text: str = "No warnings or errors"


class LatestRunStore:
    """Remember latest Architecture read models by browser session."""

    def __init__(self) -> None:
        self._latest: LatestRunReadModel | None = None
        self._latest_by_session: dict[str, LatestRunReadModel] = {}

    def record(
        self,
        execution: Any,
        *,
        session_key: str | None = None,
    ) -> LatestRunReadModel:
        model = latest_run_from_execution(execution)
        self._latest = model
        self._latest_by_session[session_latest_key(session_key)] = model
        return model

    def latest(self, *, session_key: str | None = None) -> LatestRunReadModel | None:
        if session_key is None:
            if not self._latest_by_session:
                return None
            return self._latest
        return self._latest_by_session.get(session_latest_key(session_key))

    def clear(self) -> None:
        self._latest = None
        self._latest_by_session.clear()


def latest_run_from_execution(execution: Any) -> LatestRunReadModel:
    """Build Architecture read-model state from a completed request execution."""
    trace = execution.trace
    answer = execution.answer
    question = trace.query if trace is not None else str(answer.metadata.get("question", ""))
    if not question:
        question = str(answer.metadata.get("original_question", ""))

    route = trace.route_type if trace is not None and trace.route_type else answer.intent
    active_component_ids = (
        tuple(stage.component_id for stage in trace.stages) if trace is not None else ()
    )
    sources = tuple(answer.sources)
    diagnostics = _diagnostics(answer, trace)
    stage_errors = _stage_errors(trace)
    status_level, status_text = _status(diagnostics, stage_errors)
    return LatestRunReadModel(
        question=question,
        intent=answer.intent,
        route=route,
        warnings=tuple(answer.warnings),
        unsupported=answer.unsupported,
        unsupported_reason=answer.unsupported_reason,
        sources=sources,
        trace=trace,
        active_component_ids=active_component_ids,
        row_count=_row_count(sources),
        diagnostics=diagnostics,
        status_level=status_level,
        status_text=status_text,
    )


def session_latest_key(session_key: str | None) -> str:
    return session_key or _SESSIONLESS_ARCHITECTURE_KEY


def _diagnostics(answer: Any, trace: PipelineTrace | None) -> tuple[str, ...]:
    diagnostics = list(answer.warnings)
    if answer.unsupported:
        reason = answer.unsupported_reason or "unsupported"
        diagnostics.append(f"Unsupported outcome: {reason}")
    diagnostics.extend(f"Runtime error: {error}" for error in _stage_errors(trace))
    return tuple(diagnostics)


def _stage_errors(trace: PipelineTrace | None) -> list[str]:
    if trace is None:
        return []
    return [stage.error for stage in trace.stages if stage.error]


def _status(
    diagnostics: tuple[str, ...],
    stage_errors: list[str],
) -> tuple[StatusLevel, str]:
    if stage_errors:
        return "error", "; ".join(f"Error: {error}" for error in stage_errors)
    if diagnostics:
        return "warning", "; ".join(diagnostics)
    return "ok", "No warnings or errors"


def _row_count(sources: tuple[Any, ...]) -> int:
    return sum(len(source.rows) for source in sources)
