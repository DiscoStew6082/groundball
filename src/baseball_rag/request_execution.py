"""Request-to-answer execution spine shared by user-facing adapters."""

from __future__ import annotations

import logging
import threading
from typing import Any

from baseball_rag.request_lifecycle import RequestExecution, run_request_lifecycle
from baseball_rag.service import answer, answer_public_demo

logger = logging.getLogger(__name__)
_public_demo_request_lock = threading.Lock()


def execute_request(
    question: str,
    *,
    answer_mode: str = "stats_only",
    adapter_component_id: str | None = None,
    adapter_label: str | None = None,
    conversation: list[dict[str, Any]] | None = None,
    attach_audit: bool = False,
    attach_review: bool = False,
    audit_logger: Any = logger,
) -> RequestExecution:
    """Run the complete answer lifecycle for one user question."""
    return run_request_lifecycle(
        question,
        answer_fn=answer,
        answer_mode=answer_mode,
        adapter_component_id=adapter_component_id,
        adapter_label=adapter_label,
        conversation=conversation,
        attach_audit=attach_audit,
        attach_review=attach_review,
        audit_logger=audit_logger,
    )


def execute_public_demo_request(
    question: str,
    *,
    adapter_component_id: str | None = None,
    adapter_label: str | None = None,
    conversation: list[dict[str, Any]] | None = None,
) -> RequestExecution:
    """Run one stats-only request through the serialized public demo seam."""
    with _public_demo_request_lock:
        execution = run_request_lifecycle(
            question,
            answer_fn=answer_public_demo,
            answer_mode="stats_only",
            adapter_component_id=adapter_component_id,
            adapter_label=adapter_label,
            conversation=conversation,
        )
        execution.answer.metadata["public_demo"] = True
        execution.answer.metadata["llm_access"] = "disabled"
        return execution
