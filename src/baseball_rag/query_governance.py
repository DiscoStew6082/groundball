"""Query governance observation for audit logging and human review."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from baseball_rag.arch.tracing import PipelineTrace
from baseball_rag.provenance import StructuredAnswer

GovernanceMode = Literal["none", "audit", "review", "audit_review"]


@dataclass(frozen=True)
class QueryGovernance:
    """Observe a completed answer and attach configured governance payloads."""

    mode: GovernanceMode = "none"
    audit_logger: Any = logging.getLogger(__name__)

    @classmethod
    def from_flags(
        cls,
        *,
        attach_audit: bool,
        attach_review: bool,
        audit_logger: Any,
    ) -> "QueryGovernance":
        if attach_audit and attach_review:
            mode: GovernanceMode = "audit_review"
        elif attach_audit:
            mode = "audit"
        elif attach_review:
            mode = "review"
        else:
            mode = "none"
        return cls(mode=mode, audit_logger=audit_logger)

    def observe(
        self,
        question: str,
        answer: StructuredAnswer,
        *,
        trace: PipelineTrace | None,
    ) -> StructuredAnswer:
        """Attach audit and review data for one completed request."""
        if self.mode in {"audit", "audit_review"}:
            from baseball_rag.audit import build_query_metadata

            answer.metadata.update(build_query_metadata(question, answer, trace=trace))
            self.audit_logger.info("query_audit", extra={"audit": answer.metadata})
        if self.mode in {"review", "audit_review"}:
            from baseball_rag.review_queue import enqueue_review_item

            answer.review = enqueue_review_item(question, answer)
        return answer
