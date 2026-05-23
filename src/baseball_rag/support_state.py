"""Support-state policy for audit metadata and human review."""

from __future__ import annotations

from dataclasses import dataclass

from baseball_rag.provenance import ReviewReason, StructuredAnswer, UnsupportedReason


@dataclass(frozen=True)
class AnswerSupportState:
    """One read model for answer support, audit, and review policy."""

    unsupported_reason: UnsupportedReason | None
    review_reason: ReviewReason | None
    structured_unsupported_reason: UnsupportedReason | None

    @property
    def audit_reason(self) -> UnsupportedReason | None:
        return self.unsupported_reason

    @property
    def reviewable(self) -> bool:
        return self.review_reason is not None


def answer_support_state(answer: StructuredAnswer) -> AnswerSupportState:
    """Return support state for one answer without re-deriving it in callers."""
    unsupported_reason = _unsupported_reason(answer)
    return AnswerSupportState(
        unsupported_reason=unsupported_reason,
        review_reason=_review_reason(answer),
        structured_unsupported_reason=answer.unsupported_reason,
    )


def _unsupported_reason(answer: StructuredAnswer) -> UnsupportedReason | None:
    if not answer.unsupported:
        return None
    if answer.unsupported_reason is not None:
        return answer.unsupported_reason
    return "unsupported"


def _review_reason(answer: StructuredAnswer) -> ReviewReason | None:
    if answer.review_reason is not None:
        return answer.review_reason
    if answer.unsupported:
        if answer.unsupported_reason == "ambiguous":
            return "ambiguous"
        return "unsupported"
    return None
