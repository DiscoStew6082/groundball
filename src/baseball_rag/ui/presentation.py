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
    """Build Gradio-compatible displays from structured domain answers."""

    def present(self, result: StructuredAnswer) -> PresentedAnswer:
        payload = result.to_dict()
        sources = _json_safe_for_gradio(payload["sources"])
        primary_source = sources[0] if sources else {}
        return PresentedAnswer(
            answer_text=payload["answer"],
            rows=_rows_for_dataframe(primary_source),
            sources=sources,
            sql=primary_source.get("sql") or "",
            chat_message=render_text(result),
            payload=payload,
            answer=result,
        )


def _json_safe_for_gradio(value: Any) -> Any:
    """Avoid file-shaped JSON objects that Gradio tries to download."""
    if isinstance(value, list):
        return [_json_safe_for_gradio(item) for item in value]
    if isinstance(value, dict):
        return {
            ("file_path" if key == "path" else key): _json_safe_for_gradio(item)
            for key, item in value.items()
        }
    return value


def _rows_for_dataframe(source: dict[str, Any]) -> RowsPayload:
    """Return source rows in a shape Gradio Dataframe renders as scalar cells."""
    rows = source.get("rows") or []
    if not rows or not all(isinstance(row, dict) for row in rows):
        return rows

    columns = source.get("columns") or list(rows[0])
    return {
        "headers": columns,
        "data": [[row.get(column) for column in columns] for row in rows],
    }
