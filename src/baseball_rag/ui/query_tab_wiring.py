"""Browser-facing Gradio Query tab callback wiring."""

from __future__ import annotations

from typing import Any

import gradio as gr

from baseball_rag.ui.gradio_adapter import GradioQueryAdapter, QueryComponentMap
from baseball_rag.ui.query_session import QuerySession
from baseball_rag.ui.query_transaction import BegunQuery


def request_session_key(request: gr.Request | None) -> str | None:
    """Return the Gradio browser session key used for latest-turn state."""
    if request is not None and request.session_hash:
        return request.session_hash
    return None


class GradioQueryTabWiring:
    """Own the Query tab's Gradio callback order and session-key plumbing."""

    def __init__(
        self,
        *,
        session: QuerySession,
        adapter: GradioQueryAdapter,
        components: QueryComponentMap,
    ) -> None:
        self._session = session
        self._adapter = adapter
        self._components = components

    def pending_components(self) -> list[Any]:
        return self._adapter.pending_components(self._components)

    def completed_components(self) -> list[Any]:
        return self._adapter.completed_components(self._components)

    def component_ids(self) -> dict[str, int]:
        return {name: component._id for name, component in self._components.items()}

    def begin(
        self,
        msg: str | None,
        chat_history: list[dict[str, str]] | None,
        conversation: list[dict[str, Any]] | None,
        turn_registry: dict[str, str | None] | None,
        request: gr.Request | None = None,
    ) -> tuple[Any, ...]:
        begun = self._session.begin(
            msg,
            chat_history,
            conversation,
            turn_registry,
            session_key=request_session_key(request),
        )
        return self._adapter.pending_outputs(
            begun.update,
            begun=begun.begun,
            registry=begun.registry,
            ask_interactive=begun.ask_interactive,
        )

    def complete(
        self,
        begun: BegunQuery | None,
        turn_registry: dict[str, str | None] | None,
        request: gr.Request | None = None,
    ) -> tuple[Any, ...]:
        completed = self._session.complete(
            begun,
            turn_registry,
            session_key=request_session_key(request),
        )
        if completed is None:
            return self._adapter.stale_outputs()
        return self._adapter.completed_outputs(completed.update)

    def begin_query(
        self,
        msg: str | None,
        chat_history: list[dict[str, str]] | None,
        conversation: list[dict[str, Any]] | None,
        turn_registry: dict[str, str | None] | None,
        request: gr.Request | None = None,
    ) -> tuple[Any, ...]:
        """Gradio callback preserving the public Query tab API name."""
        return self.begin(msg, chat_history, conversation, turn_registry, request=request)

    def on_query(
        self,
        begun: BegunQuery | None,
        turn_registry: dict[str, str | None] | None,
        request: gr.Request | None = None,
    ) -> tuple[Any, ...]:
        """Gradio callback preserving the public Query tab API name."""
        return self.complete(begun, turn_registry, request=request)

    def wire(
        self,
        *,
        submit: gr.Button,
        question: gr.Textbox,
        chat_state: gr.State,
        conversation_state: gr.State,
        query_turn_registry: gr.State,
        query_turn_state: gr.State,
    ) -> None:
        """Register Query tab Gradio events."""
        begin_outputs = gr.on(
            triggers=[submit.click, question.submit],
            fn=self.begin_query,
            inputs=[question, chat_state, conversation_state, query_turn_registry],
            outputs=self.pending_components(),
            trigger_mode="always_last",
            show_progress="hidden",
            queue=False,
        )

        begin_outputs.then(
            fn=self.on_query,
            inputs=[query_turn_state, query_turn_registry],
            outputs=self.completed_components(),
            trigger_mode="always_last",
            show_progress="minimal",
            queue=False,
        )
