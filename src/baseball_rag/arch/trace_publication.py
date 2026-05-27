"""Architecture trace publication policy for completed requests."""

from __future__ import annotations

import logging
import threading
from typing import Any

from baseball_rag.request_execution import RequestExecution

logger = logging.getLogger(__name__)
_PUBLISH_LOCK = threading.Lock()


class ArchitectureTracePublisher:
    """Publish completed request executions to the Architecture Explorer."""

    def __init__(self, diagram: Any, *, animate: bool) -> None:
        self._diagram = diagram
        self._animate = animate

    def publish(self, execution: RequestExecution, session_key: str | None = None) -> None:
        try:
            if self._animate:
                self._animate_execution(execution)
            else:
                self._record_execution(execution, session_key=session_key)
        except Exception:
            query = execution.trace.query if execution.trace is not None else ""
            logger.exception("Gradio diagram trace update failed for %r", query)

    def _animate_execution(self, execution: RequestExecution) -> None:
        trace = execution.trace
        if trace is not None and hasattr(self._diagram, "animate_trace"):
            with _PUBLISH_LOCK:
                self._diagram.animate_trace(trace)

    def _record_execution(
        self,
        execution: RequestExecution,
        *,
        session_key: str | None,
    ) -> None:
        trace = execution.trace
        if hasattr(self._diagram, "record_execution"):
            with _PUBLISH_LOCK:
                self._diagram.record_execution(execution, session_key=session_key)
            return
        if trace is None or not hasattr(self._diagram, "trace_history"):
            return
        with _PUBLISH_LOCK:
            self._diagram.trace_history.append(trace)
            if len(self._diagram.trace_history) > self._diagram.max_history:
                self._diagram.trace_history.pop(0)
