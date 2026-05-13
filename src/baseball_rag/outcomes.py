"""Outcome policy helpers for unsupported, reviewable, and failure answers."""

from __future__ import annotations

from baseball_rag.provenance import (
    ReviewReason,
    SourceRecord,
    StructuredAnswer,
    UnsupportedReason,
)


def ambiguous_outcome(
    *,
    answer: str,
    intent: str,
    sources: list[SourceRecord] | None = None,
    warnings: list[str] | None = None,
) -> StructuredAnswer:
    """Build an unsupported outcome for ambiguous user input."""
    return unsupported_outcome(
        answer=answer,
        intent=intent,
        reason="ambiguous",
        review_reason="ambiguous",
        sources=sources,
        warnings=warnings,
    )


def no_data_outcome(
    *,
    answer: str,
    intent: str,
    sources: list[SourceRecord] | None = None,
    warnings: list[str] | None = None,
) -> StructuredAnswer:
    """Build an unsupported outcome for valid queries with no local rows."""
    return unsupported_outcome(
        answer=answer,
        intent=intent,
        reason="no_data",
        sources=sources,
        warnings=warnings,
    )


def missing_corpus_outcome(
    *,
    answer: str,
    intent: str,
    warnings: list[str] | None = None,
) -> StructuredAnswer:
    """Build an unsupported outcome for absent local retrieval corpus."""
    return unsupported_outcome(
        answer=answer,
        intent=intent,
        reason="missing_corpus",
        warnings=warnings,
    )


def retrieval_failed_outcome(
    *,
    answer: str,
    intent: str,
    warning: str,
) -> StructuredAnswer:
    """Build an unsupported outcome for recoverable retrieval failures."""
    return unsupported_outcome(
        answer=answer,
        intent=intent,
        reason="retrieval_failed",
        warnings=[warning],
    )


def llm_unavailable_outcome(
    *,
    answer: str,
    intent: str,
    warnings: list[str] | None = None,
) -> StructuredAnswer:
    """Build an unsupported outcome for unavailable local LLM execution."""
    return unsupported_outcome(
        answer=answer,
        intent=intent,
        reason="llm_unavailable",
        warnings=warnings,
    )


def timeout_outcome(exc: TimeoutError) -> StructuredAnswer:
    """Build the UI-visible outcome for a local LLM timeout."""
    return llm_unavailable_outcome(
        answer=(
            "The local LM Studio request timed out before it returned an answer. "
            "Try again, or ask a stat/database-backed question while the model catches up."
        ),
        intent="error",
        warnings=[str(exc)],
    )


def local_request_failure_outcome(exc: Exception) -> StructuredAnswer:
    """Build the UI-visible outcome for local response-shape/runtime failures."""
    return llm_unavailable_outcome(
        answer=(
            "The local request could not return an answer after a service responded. "
            "Try again, or check the server logs for the response-shape error."
        ),
        intent="error",
        warnings=[str(exc)],
    )


def unsupported_outcome(
    *,
    answer: str,
    intent: str,
    reason: UnsupportedReason,
    sources: list[SourceRecord] | None = None,
    warnings: list[str] | None = None,
    review_reason: ReviewReason | None = None,
) -> StructuredAnswer:
    """Build one unsupported answer with consistent structured reason fields."""
    return StructuredAnswer(
        answer=answer,
        intent=intent,
        sources=list(sources or []),
        warnings=list(warnings or []),
        unsupported=True,
        unsupported_reason=reason,
        review_reason=review_reason,
    )
