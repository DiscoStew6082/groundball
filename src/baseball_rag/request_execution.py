"""Request-to-answer execution spine shared by user-facing adapters."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from baseball_rag.arch.tracing import (
    PipelineTrace,
    finish_trace,
    get_current_trace,
    start_trace,
    traced,
)
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.service import answer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RequestExecution:
    """A completed answer plus the trace produced while building it."""

    answer: StructuredAnswer
    trace: PipelineTrace | None


def execute_request(
    question: str,
    *,
    adapter_component_id: str | None = None,
    adapter_label: str | None = None,
    conversation: list[dict[str, Any]] | None = None,
    attach_audit: bool = False,
    attach_review: bool = False,
    audit_logger: Any = logger,
) -> RequestExecution:
    """Run the complete answer lifecycle for one user question."""
    current_trace = get_current_trace()
    owns_trace = current_trace is None or current_trace.query == ""
    if owns_trace:
        start_trace(question)

    try:
        if adapter_component_id is None:
            result = answer(question, conversation=conversation)
        else:
            with traced(
                component_id=adapter_component_id,
                label=adapter_label or adapter_component_id.upper(),
            ):
                result = answer(question, conversation=conversation)
    except Exception:
        if owns_trace:
            finish_trace(route_type="")
        raise

    trace = finish_trace(route_type=result.intent) if owns_trace else get_current_trace()

    if attach_audit:
        from baseball_rag.audit import build_query_metadata

        result.metadata.update(build_query_metadata(question, result, trace=trace))
        audit_logger.info("query_audit", extra={"audit": result.metadata})

    if attach_review:
        from baseball_rag.review_queue import enqueue_review_item

        result.review = enqueue_review_item(question, result)

    return RequestExecution(answer=result, trace=trace)
