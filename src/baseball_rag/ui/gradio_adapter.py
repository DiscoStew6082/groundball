"""Gradio-specific mapping for query UI updates."""

from __future__ import annotations

from typing import Any

import gradio as gr

from baseball_rag.ui.query_transaction import QueryUiUpdate


class GradioQueryAdapter:
    """Map adapter-neutral query updates to Gradio component output tuples."""

    def completed_outputs(
        self,
        update: QueryUiUpdate,
    ) -> tuple[
        list[dict[str, str]],
        str,
        str,
        Any,
        list[dict[str, Any]],
        str,
        list[dict[str, str]],
        list[dict[str, Any]],
        dict[str, Any],
    ]:
        """Return the full completed-query output tuple expected by the Query tab."""
        return (
            update.visible_chat_history,
            update.question,
            update.answer_text,
            update.rows,
            update.sources,
            update.sql,
            update.chat_history,
            update.conversation,
            gr.update(interactive=True),
        )

    def pending_outputs(
        self,
        update: QueryUiUpdate,
        *,
        begun: Any,
        registry: dict[str, str | None],
        ask_interactive: bool,
    ) -> tuple[
        str,
        Any,
        list[dict[str, Any]],
        str,
        Any,
        dict[str, str | None],
        dict[str, Any],
    ]:
        """Return the pending-query output tuple expected by the Query tab."""
        return (
            update.answer_text,
            update.rows,
            update.sources,
            update.sql,
            begun,
            registry,
            gr.update(interactive=ask_interactive),
        )

    def stale_outputs(self) -> tuple[Any, ...]:
        """Return no-op updates for stale query completions."""
        return tuple(gr.update() for _ in range(9))
