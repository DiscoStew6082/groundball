"""Request-to-answer execution spine shared by user-facing adapters."""

from __future__ import annotations

import logging
from typing import Any

from baseball_rag.request_lifecycle import RequestExecution, run_request_lifecycle
from baseball_rag.service import answer

logger = logging.getLogger(__name__)


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
