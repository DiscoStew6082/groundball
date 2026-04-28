"""Lightweight human review queue helpers for uncertain answers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from baseball_rag.provenance import StructuredAnswer

ReviewReason = Literal["unsupported", "ambiguous", "low_confidence"]
ReviewStatus = Literal["open", "resolved", "dismissed"]


@dataclass(frozen=True)
class ReviewQueueItem:
    """A deterministic local review queue entry."""

    id: str
    question: str
    answer_id: str | None
    status: ReviewStatus
    reason: ReviewReason
    audit: dict[str, Any]
    created_at: str


def build_review_item(
    question: str,
    answer: StructuredAnswer,
    *,
    low_confidence_threshold: float = 0.35,
) -> ReviewQueueItem | None:
    """Return a review item when an answer should be checked by a person."""
    reason = _review_reason(answer, low_confidence_threshold=low_confidence_threshold)
    if reason is None:
        return None

    audit = {
        "route": answer.intent,
        "unsupported": answer.unsupported,
        "warnings": answer.warnings,
        "source_types": [source.type for source in answer.sources],
        **answer.metadata,
    }
    item_id = _review_id(question=question, reason=reason, audit=audit)
    return ReviewQueueItem(
        id=item_id,
        question=question,
        answer_id=None,
        status="open",
        reason=reason,
        audit=audit,
        created_at=datetime.now(UTC).isoformat(),
    )


def review_payload(item: ReviewQueueItem | None) -> dict[str, Any] | None:
    """Return the public response payload for a review item."""
    if item is None:
        return None
    return {"queued": True, "reason": item.reason, "item_id": item.id}


def write_review_item(path: Path, item: ReviewQueueItem | None) -> None:
    """Append one review item to a local JSONL queue."""
    if item is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(asdict(item), sort_keys=True) + "\n")


def load_review_items(path: Path) -> list[ReviewQueueItem]:
    """Load review items from a local JSONL queue."""
    if not path.exists():
        return []
    items: list[ReviewQueueItem] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            items.append(ReviewQueueItem(**json.loads(line)))
    return items


def _review_reason(
    answer: StructuredAnswer,
    *,
    low_confidence_threshold: float,
) -> ReviewReason | None:
    if answer.unsupported:
        combined_text = " ".join([answer.answer, *answer.warnings]).casefold()
        if "ambiguous" in combined_text:
            return "ambiguous"
        return "unsupported"

    chroma_scores = [
        source.score
        for source in answer.sources
        if source.type == "chroma" and source.score is not None
    ]
    if chroma_scores and max(chroma_scores) < low_confidence_threshold:
        return "low_confidence"
    return None


def _review_id(*, question: str, reason: ReviewReason, audit: dict[str, Any]) -> str:
    stable_payload = json.dumps(
        {
            "question": question,
            "reason": reason,
            "route": audit.get("route"),
            "trace": audit.get("trace"),
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()[:12]
    return f"review_{digest}"
