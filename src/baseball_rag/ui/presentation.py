"""Presentation policy for turning domain answers into adapter payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from baseball_rag.conversation import conversation_turn
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.service import render_text

RowsPayload = list[Any] | dict[str, list[Any]]


@dataclass(frozen=True)
class PresentedAnswer:
    """Display-ready answer fields for chat and structured result panels."""

    answer_text: str
    rows: RowsPayload
    sources: list[dict[str, Any]]
    sql: str
    chat_message: str
    payload: dict[str, Any]
    answer: StructuredAnswer

    def conversation_turn(self, question: str) -> dict[str, Any]:
        """Store only the answer fields needed to resolve future follow-ups."""
        return conversation_turn(question, self.answer)


class AnswerPresenter:
    """Build browser-compatible displays from structured domain answers."""

    def present(self, result: StructuredAnswer) -> PresentedAnswer:
        payload = result.to_dict()
        sources = _json_safe(payload["sources"])
        visible_rows_source = _source_for_visible_rows(sources)
        visible_sql_source = _source_for_visible_sql(sources, preferred=visible_rows_source)
        return PresentedAnswer(
            answer_text=payload["answer"],
            rows=_rows_for_dataframe(visible_rows_source),
            sources=sources,
            sql=visible_sql_source.get("sql") or "",
            chat_message=render_text(result),
            payload=payload,
            answer=result,
        )


def _json_safe(value: Any) -> Any:
    """Return recursively JSON-safe source metadata for browser adapters."""
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {
            ("file_path" if key == "path" else key): _json_safe(item) for key, item in value.items()
        }
    return value


def _rows_for_dataframe(source: dict[str, Any]) -> RowsPayload:
    """Return source rows as scalar headers and cells for browser tables."""
    rows = source.get("rows") or []
    if not rows or not all(isinstance(row, dict) for row in rows):
        return rows

    columns = source.get("columns") or list(rows[0])
    return {
        "headers": columns,
        "data": [[row.get(column) for column in columns] for row in rows],
    }


def _source_for_visible_rows(sources: list[dict[str, Any]]) -> dict[str, Any]:
    verification_source = _first_source_matching(sources, _has_verification_rows)
    if verification_source is not None:
        return verification_source
    rows_source = _first_source_matching(sources, lambda source: bool(source.get("rows")))
    return rows_source or (sources[0] if sources else {})


def _source_for_visible_sql(
    sources: list[dict[str, Any]],
    *,
    preferred: dict[str, Any],
) -> dict[str, Any]:
    if preferred.get("sql"):
        return preferred
    return _first_source_matching(sources, lambda source: bool(source.get("sql"))) or preferred


def _first_source_matching(
    sources: list[dict[str, Any]],
    predicate: Any,
) -> dict[str, Any] | None:
    for source in sources:
        if predicate(source):
            return source
    return None


def _has_verification_rows(source: dict[str, Any]) -> bool:
    rows = source.get("rows") or []
    return any(
        isinstance(row, dict)
        and any(
            key in row
            for key in (
                "consensus_status",
                "primary_status",
                "secondary_status",
            )
        )
        for row in rows
    )
