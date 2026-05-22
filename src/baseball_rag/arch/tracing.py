"""Pipeline tracing — PipelineStage, PipelineTrace, and @traced context manager.

Phase 2 of the Architecture Explorer plan.
"""

from __future__ import annotations

import datetime
import functools
import os
import threading
import time
from dataclasses import dataclass, field


@dataclass
class PipelineStage:
    """A single timed stage in a query pipeline execution.

    Attributes:
        component_id: Which DiagramComponent.id this stage represents.
        label: Human-readable name for the stage (e.g. "Query Router").
        started_at: When the stage began (wall-clock time).
        elapsed_ms: How long the stage took in milliseconds.
        output_summary: Short human-readable result description
            (e.g. "routed to stat_query \u2192 DuckDB").
        error: Error message if the stage failed, otherwise None.
    """

    component_id: str
    label: str
    started_at: datetime.datetime
    elapsed_ms: float
    output_summary: str = ""
    error: str | None = None
    order: int = field(default=0, repr=False, compare=False)

    @property
    def is_success(self) -> bool:
        return self.error is None


@dataclass
class PipelineTrace:
    """The complete execution trace for a single user query.

    Attributes:
        query: The original natural-language question.
        stages: Ordered list of PipelineStage objects (execution order).
        total_ms: Total wall-clock time for the entire pipeline.
        route_type: Whether this was a "stat_query" or "general_explanation" routing decision.
    """

    query: str
    stages: list[PipelineStage] = field(default_factory=list)
    route_type: str = ""
    _next_order: int = field(default=0, repr=False, compare=False)

    def add_stage(self, stage: PipelineStage) -> None:
        self.stages.append(stage)

    @property
    def total_ms(self) -> float:
        """Sum of all stage elapsed_ms values."""
        return sum(s.elapsed_ms for s in self.stages)

    @property
    def is_complete(self) -> bool:
        return len(self.stages) > 0


# ---------------------------------------------------------------------------
# Global trace storage (thread-local so concurrent requests don't clobber each other)
# ---------------------------------------------------------------------------

_current_trace = threading.local()
_depth_stack_state = threading.local()


@dataclass
class _ActiveStage:
    stage: PipelineStage
    started_ns: int


def _get_depth_stack() -> list[int]:
    stack = getattr(_depth_stack_state, "stack", None)
    if stack is None:
        stack = []
        _depth_stack_state.stack = stack
    return stack


def get_current_trace() -> PipelineTrace | None:
    """Return the trace being recorded in the current thread, or None."""
    return getattr(_current_trace, "trace", None)


def _set_current_trace(trace: PipelineTrace | None) -> None:
    _current_trace.trace = trace


# ---------------------------------------------------------------------------
# @traced decorator / context manager
# ---------------------------------------------------------------------------

_TRACING_DISABLED = os.environ.get("DISABLE_TRACING", "").lower() in ("1", "true", "yes")


class traced:
    """Context manager + decorator for instrumenting pipeline stages.

    Usage as decorator::
        @traced(component_id="query-router", label="Query Router")
        def route(question: str) -> RoutedCase:
            ...

    Usage as context manager::
        with traced(component_id="claim-verifier", label="Verify Biography Claims"):
            verified = verify_claims(query)

    On exit the stage is automatically added to the current PipelineTrace
    (creating one if none exists).  Exceptions are re-raised after recording.
    """

    def __init__(
        self,
        component_id: str,
        label: str,
        output_summary: str = "",
    ):
        self.component_id = component_id
        self.label = label
        self.output_summary = output_summary
        self._local = threading.local()

    def _active_stack(self) -> list[_ActiveStage]:
        stack = getattr(self._local, "active_stack", None)
        if stack is None:
            stack = []
            self._local.active_stack = stack
        return stack

    def _set_current_output_summary(self, output_summary: str) -> None:
        active_stack = self._active_stack()
        if active_stack:
            active_stack[-1].stage.output_summary = output_summary

    def __enter__(self) -> "traced":
        if _TRACING_DISABLED:
            return self
        started_at = datetime.datetime.now()
        started_ns = time.perf_counter_ns()
        # Ensure a trace exists for this thread
        trace = get_current_trace()
        if trace is None:
            trace = PipelineTrace(query="")
            _set_current_trace(trace)
        order = trace._next_order
        trace._next_order += 1

        stage = PipelineStage(
            component_id=self.component_id,
            label=self.label,
            started_at=started_at,
            elapsed_ms=0.0,
            output_summary=self.output_summary,
            order=order,
        )
        # Track nesting depth per thread so finish_trace() in another worker cannot disturb us.
        depth_stack = _get_depth_stack()
        depth_stack.append(order)
        self._active_stack().append(_ActiveStage(stage=stage, started_ns=started_ns))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        if _TRACING_DISABLED:
            return
        active_stack = self._active_stack()
        if not active_stack:
            return
        active = active_stack.pop()
        elapsed_ns = time.perf_counter_ns() - active.started_ns
        active.stage.elapsed_ms = elapsed_ns / 1_000_000

        trace = get_current_trace()
        if trace is not None:
            if exc_val is not None:
                type_name = exc_type.__name__ if exc_type else type(exc_val).__name__
                active.stage.error = f"{type_name}: {exc_val}"
            else:
                active.stage.output_summary = self.output_summary or active.stage.output_summary
            # A nested stage may exit before its parent; sort by entry order to preserve call order.
            trace.stages.append(active.stage)
            trace.stages.sort(key=lambda stage: stage.order)
        depth_stack = _get_depth_stack()
        if depth_stack:
            depth_stack.pop()

    def __call__(self, func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with self:
                result = func(*args, **kwargs)
                # If the function returns a route_type string, capture it as output_summary
                if isinstance(result, str) and not self.output_summary:
                    self._set_current_output_summary(result)
                return result

        return wrapper


def start_trace(query: str) -> PipelineTrace:
    """Begin a new trace for *query* in the current thread."""
    trace = PipelineTrace(query=query)
    _set_current_trace(trace)
    return trace


def finish_trace(route_type: str = "") -> PipelineTrace | None:
    """Finalise and return the current trace."""
    trace = get_current_trace()
    if trace is None:
        return None
    trace.route_type = route_type
    _set_current_trace(None)  # clear
    _get_depth_stack().clear()  # reset this thread's depth stack
    return trace
