"""Adapter-neutral query session policy for the Gradio Query tab."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

from baseball_rag.request_execution import RequestExecution
from baseball_rag.ui.query_transaction import (
    BegunQuery,
    QueryTransaction,
    QueryUiUpdate,
    RequestExecutor,
)

_SESSIONLESS_QUERY_KEY = "__sessionless_query__"
RecordExecution = Callable[[RequestExecution, str | None], None]


class LatestQueryTurns:
    """Track the latest submitted query per browser session."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest_by_session: dict[str, str | None] = {}

    def mark(self, session_key: str, turn_id: str | None) -> None:
        with self._lock:
            self._latest_by_session[session_key] = turn_id

    def has_session(self, session_key: str) -> bool:
        with self._lock:
            return session_key in self._latest_by_session

    def is_latest(self, session_key: str, turn_id: str) -> bool:
        with self._lock:
            return self._latest_by_session.get(session_key) == turn_id


@dataclass(frozen=True)
class BegunQuerySession:
    """Result of beginning a UI query turn."""

    update: QueryUiUpdate
    begun: BegunQuery
    registry: dict[str, str | None]
    ask_interactive: bool


@dataclass(frozen=True)
class CompletedQuerySession:
    """Result of completing a UI query turn."""

    update: QueryUiUpdate
    ask_interactive: bool = True


class QuerySession:
    """Own latest-turn guards and trace-recording policy for query UI adapters."""

    def __init__(
        self,
        *,
        execute: RequestExecutor,
        default_question: str,
        record_execution: RecordExecution | None = None,
        latest_turns: LatestQueryTurns | None = None,
    ) -> None:
        self._execute = execute
        self._default_question = default_question
        self._record_execution = record_execution
        self._latest_turns = latest_turns or LatestQueryTurns()

    def begin(
        self,
        message: str | None,
        chat_history: list[dict[str, str]] | None,
        conversation: list[dict[str, Any]] | None,
        registry: dict[str, str | None] | None,
        *,
        session_key: str | None = None,
    ) -> BegunQuerySession:
        """Begin a query and mark it as the latest turn for the session."""
        begun = self._transaction().begin(message, chat_history, conversation)
        registry = self._mark_latest_query(registry, begun, session_key=session_key)
        return BegunQuerySession(
            update=begun.update,
            begun=begun,
            registry=registry,
            ask_interactive=begun.pending is None,
        )

    def complete(
        self,
        begun: BegunQuery | None,
        registry: dict[str, str | None] | None,
        *,
        session_key: str | None = None,
    ) -> CompletedQuerySession | None:
        """Complete a latest pending query, returning ``None`` for stale turns."""
        if begun is None:
            update = self._transaction().run(None, [], [])
        elif begun.pending is None:
            update = begun.update
        else:
            resolved_session_key = self._query_session_key(session_key, registry)
            if not self._is_latest_query(begun, registry, session_key=session_key):
                return None
            update = self._transaction().complete(begun.pending)
            if not self._is_latest_query(begun, registry, session_key=session_key):
                return None
            if self._record_execution is not None and update.execution is not None:
                self._record_execution(update.execution, resolved_session_key)
        return CompletedQuerySession(update=update)

    def _transaction(self) -> QueryTransaction:
        return QueryTransaction(
            execute=self._execute,
            default_question=self._default_question,
        )

    def _mark_latest_query(
        self,
        registry: dict[str, str | None] | None,
        begun: BegunQuery,
        *,
        session_key: str | None,
    ) -> dict[str, str | None]:
        updated = dict(registry or {})
        turn_id = begun.pending.turn_id if begun.pending is not None else None
        resolved_session_key = self._query_session_key(session_key, updated)
        updated["latest_turn_id"] = turn_id
        updated["session_key"] = resolved_session_key
        self._latest_turns.mark(resolved_session_key, turn_id)
        return updated

    def _is_latest_query(
        self,
        begun: BegunQuery,
        registry: dict[str, str | None] | None,
        *,
        session_key: str | None,
    ) -> bool:
        if begun.pending is None:
            return True
        resolved_session_key = self._query_session_key(session_key, registry)
        if self._latest_turns.has_session(resolved_session_key):
            return self._latest_turns.is_latest(resolved_session_key, begun.pending.turn_id)
        if registry is None:
            return False
        return registry.get("latest_turn_id") == begun.pending.turn_id

    def _query_session_key(
        self,
        session_key: str | None,
        registry: dict[str, str | None] | None,
    ) -> str:
        if session_key:
            return session_key
        if registry is not None and registry.get("session_key"):
            return str(registry["session_key"])
        return _SESSIONLESS_QUERY_KEY
