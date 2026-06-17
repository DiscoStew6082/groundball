"""Lightweight human review queue helpers for uncertain answers."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from baseball_rag.provenance import StructuredAnswer
from baseball_rag.support_state import answer_support_state

ReviewReason = Literal["unsupported", "ambiguous"]
ReviewStatus = Literal["open", "resolved", "dismissed"]
DEFAULT_REVIEW_QUEUE_PATH = Path("data/review_queue.jsonl")


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
    resolved_at: str | None = None
    resolution_note: str | None = None


def build_review_item(
    question: str,
    answer: StructuredAnswer,
) -> ReviewQueueItem | None:
    """Return a review item when an answer should be checked by a person."""
    reason = answer_support_state(answer).review_reason
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


def enqueue_review_item(question: str, answer: StructuredAnswer) -> dict[str, Any] | None:
    """Build, persist, and return the public human-review payload for an answer."""
    item = build_review_item(question, answer)
    persist_review_item(item)
    return review_payload(item)


_REVIEW_QUEUE_ENV_VAR = "GROUNDBALL_REVIEW_QUEUE_PATH"
_LEGACY_REVIEW_QUEUE_ENV_VAR = "BASEBALL_RAG_REVIEW_QUEUE_PATH"


def review_queue_path() -> Path:
    """Return the configured local review queue path."""
    configured = os.environ.get(
        _REVIEW_QUEUE_ENV_VAR,
        os.environ.get(_LEGACY_REVIEW_QUEUE_ENV_VAR, DEFAULT_REVIEW_QUEUE_PATH),
    )
    return Path(configured)


def persist_review_item(
    item: ReviewQueueItem | None,
    *,
    path: Path | None = None,
) -> None:
    """Persist an open review item unless it is already the latest stored state."""
    if item is None:
        return
    target = path or review_queue_path()
    latest = {stored.id: stored for stored in list_review_items(path=target, status="all")}
    existing = latest.get(item.id)
    if existing == item or _same_open_snapshot(existing, item):
        return
    write_review_item(target, item)


def list_review_items(
    *,
    path: Path | None = None,
    status: ReviewStatus | Literal["all"] | None = "open",
) -> list[ReviewQueueItem]:
    """Return latest review item snapshots, optionally filtered by status."""
    latest: dict[str, ReviewQueueItem] = {}
    for item in load_review_items(path or review_queue_path()):
        latest[item.id] = item
    items = list(latest.values())
    if status in (None, "all"):
        return items
    return [item for item in items if item.status == status]


def resolve_review_item(
    item_id: str,
    status: Literal["resolved", "dismissed"],
    *,
    note: str | None = None,
    path: Path | None = None,
) -> ReviewQueueItem:
    """Append a resolved/dismissed snapshot for an existing review item."""
    target = path or review_queue_path()
    latest = {item.id: item for item in list_review_items(path=target, status="all")}
    item = latest.get(item_id)
    if item is None:
        raise KeyError(f"review item {item_id!r} not found")
    updated = ReviewQueueItem(
        id=item.id,
        question=item.question,
        answer_id=item.answer_id,
        status=status,
        reason=item.reason,
        audit=item.audit,
        created_at=item.created_at,
        resolved_at=datetime.now(UTC).isoformat(),
        resolution_note=note,
    )
    write_review_item(target, updated)
    return updated


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


def _same_open_snapshot(existing: ReviewQueueItem | None, item: ReviewQueueItem) -> bool:
    if existing is None:
        return False
    return (
        existing.status == "open"
        and item.status == "open"
        and existing.question == item.question
        and existing.answer_id == item.answer_id
        and existing.reason == item.reason
        and existing.audit == item.audit
    )


def _review_id(*, question: str, reason: ReviewReason, audit: dict[str, Any]) -> str:
    stable_payload = json.dumps(
        {
            "question": question,
            "reason": reason,
            "route": audit.get("route"),
            "query_id": audit.get("query_id"),
        },
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(stable_payload.encode("utf-8")).hexdigest()[:12]
    return f"review_{digest}"
