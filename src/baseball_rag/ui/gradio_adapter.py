"""Gradio-specific mapping for query UI updates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gradio as gr

from baseball_rag.ui.query_transaction import QueryUiUpdate

PendingOutputName = str
CompletedOutputName = str
QueryComponentMap = dict[str, Any]
QueryOutputValueMap = dict[str, Any]


@dataclass(frozen=True)
class QueryOutputContract:
    """Named Gradio outputs for the Query tab."""

    pending: tuple[PendingOutputName, ...] = (
        "answer",
        "rows",
        "sources",
        "sql",
        "pending_query",
        "turn_registry",
        "ask_button",
    )
    completed: tuple[CompletedOutputName, ...] = (
        "chat",
        "question",
        "answer",
        "rows",
        "sources",
        "sql",
        "chat_state",
        "conversation_state",
        "ask_button",
    )

    @property
    def all_names(self) -> tuple[str, ...]:
        """Return each query output component name once."""
        return tuple(dict.fromkeys((*self.pending, *self.completed)))

    def pending_components(self, components: QueryComponentMap) -> list[Any]:
        """Return pending Gradio components in callback output order."""
        return self._components_for(self.pending, components)

    def completed_components(self, components: QueryComponentMap) -> list[Any]:
        """Return completed Gradio components in callback output order."""
        return self._components_for(self.completed, components)

    def pending_values(self, values: QueryOutputValueMap) -> tuple[Any, ...]:
        """Return pending Gradio values in callback output order."""
        return self._values_for(self.pending, values)

    def completed_values(self, values: QueryOutputValueMap) -> tuple[Any, ...]:
        """Return completed Gradio values in callback output order."""
        return self._values_for(self.completed, values)

    def _components_for(self, names: tuple[str, ...], components: QueryComponentMap) -> list[Any]:
        missing = [name for name in names if name not in components]
        if missing:
            raise KeyError("Query output component map is missing: " + ", ".join(sorted(missing)))
        return [components[name] for name in names]

    def _values_for(self, names: tuple[str, ...], values: QueryOutputValueMap) -> tuple[Any, ...]:
        missing = [name for name in names if name not in values]
        if missing:
            raise KeyError("Query output values are missing: " + ", ".join(sorted(missing)))
        return tuple(values[name] for name in names)


class GradioQueryAdapter:
    """Map adapter-neutral query updates to Gradio component output tuples."""

    output_contract = QueryOutputContract()

    @property
    def pending_output_names(self) -> tuple[str, ...]:
        return self.output_contract.pending

    @property
    def completed_output_names(self) -> tuple[str, ...]:
        return self.output_contract.completed

    @property
    def stale_output_names(self) -> tuple[str, ...]:
        return self.output_contract.completed

    @property
    def query_output_names(self) -> tuple[str, ...]:
        return self.output_contract.all_names

    def pending_components(self, components: QueryComponentMap) -> list[Any]:
        return self.output_contract.pending_components(components)

    def completed_components(self, components: QueryComponentMap) -> list[Any]:
        return self.output_contract.completed_components(components)

    def completed_named_outputs(self, update: QueryUiUpdate) -> QueryOutputValueMap:
        """Return completed-query values keyed by Query tab output name."""
        return {
            "chat": update.visible_chat_history,
            "question": update.question,
            "answer": update.answer_text,
            "rows": update.rows,
            "sources": update.sources,
            "sql": update.sql,
            "chat_state": update.chat_history,
            "conversation_state": update.conversation,
            "ask_button": gr.update(interactive=True),
        }

    def pending_named_outputs(
        self,
        update: QueryUiUpdate,
        *,
        begun: Any,
        registry: dict[str, str | None],
        ask_interactive: bool,
    ) -> QueryOutputValueMap:
        """Return pending-query values keyed by Query tab output name."""
        return {
            "answer": update.answer_text,
            "rows": update.rows,
            "sources": update.sources,
            "sql": update.sql,
            "pending_query": begun,
            "turn_registry": registry,
            "ask_button": gr.update(interactive=ask_interactive),
        }

    def stale_named_outputs(self) -> QueryOutputValueMap:
        """Return stale-query no-op values keyed by completed output name."""
        return {name: gr.update() for name in self.stale_output_names}

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
        return self.output_contract.completed_values(self.completed_named_outputs(update))

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
        return self.output_contract.pending_values(
            self.pending_named_outputs(
                update,
                begun=begun,
                registry=registry,
                ask_interactive=ask_interactive,
            )
        )

    def stale_outputs(self) -> tuple[Any, ...]:
        """Return no-op updates for stale query completions."""
        return self.output_contract.completed_values(self.stale_named_outputs())
