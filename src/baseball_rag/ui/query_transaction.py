"""Query UI transaction lifecycle shared by Gradio adapters."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from baseball_rag.outcomes import local_request_failure_outcome, timeout_outcome
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.request_execution import RequestExecution
from baseball_rag.ui.presentation import AnswerPresenter, RowsPayload

logger = logging.getLogger(__name__)

QueryStatus = Literal["idle", "pending", "completed", "failed"]


class RequestExecutor(Protocol):
    def __call__(
        self,
        question: str,
        *,
        conversation: list[dict[str, Any]],
    ) -> RequestExecution: ...


@dataclass(frozen=True)
class QueryUiUpdate:
    """Adapter-neutral state for every visible part of the query UI."""

    status: QueryStatus
    chat_history: list[dict[str, str]]
    question: str
    answer_text: str
    rows: RowsPayload
    sources: list[dict[str, Any]]
    sql: str
    visible_chat_history: list[dict[str, str]]
    conversation: list[dict[str, Any]]
    execution: RequestExecution | None = None

    def as_gradio_values(
        self,
    ) -> tuple[
        list[dict[str, str]],
        str,
        str,
        RowsPayload,
        list[dict[str, Any]],
        str,
        list[dict[str, str]],
        list[dict[str, Any]],
    ]:
        """Return values in the order expected by the Gradio Query tab."""
        return (
            self.visible_chat_history,
            self.question,
            self.answer_text,
            self.rows,
            self.sources,
            self.sql,
            self.chat_history,
            self.conversation,
        )


@dataclass(frozen=True)
class PendingQuery:
    """The immutable data needed to finish one submitted query."""

    turn_id: str
    message: str
    chat_history: list[dict[str, str]]
    conversation: list[dict[str, Any]]


@dataclass(frozen=True)
class BegunQuery:
    """The pending visible update plus the work token for completion."""

    update: QueryUiUpdate
    pending: PendingQuery | None


class QueryTransaction:
    """Own the query lifecycle before any adapter maps it to components."""

    def __init__(
        self,
        *,
        execute: RequestExecutor,
        default_question: str,
        presenter: AnswerPresenter | None = None,
    ) -> None:
        self._execute = execute
        self._default_question = default_question
        self._presenter = presenter or AnswerPresenter()

    def begin(
        self,
        message: str | None,
        chat_history: list[dict[str, str]] | None,
        conversation: list[dict[str, Any]] | None,
    ) -> BegunQuery:
        """Return the immediate pending update and a token to complete."""
        chat = list(chat_history or [])
        prior_conversation = list(conversation or [])
        submitted = (message or "").strip()
        if not submitted:
            return BegunQuery(
                update=QueryUiUpdate(
                    status="idle",
                    chat_history=chat,
                    question=self._default_question,
                    answer_text="",
                    rows=[],
                    sources=[],
                    sql="",
                    visible_chat_history=list(chat),
                    conversation=prior_conversation,
                ),
                pending=None,
            )

        return BegunQuery(
            update=QueryUiUpdate(
                status="pending",
                chat_history=chat,
                question=submitted,
                answer_text="",
                rows=[],
                sources=[],
                sql="",
                visible_chat_history=list(chat),
                conversation=prior_conversation,
            ),
            pending=PendingQuery(
                turn_id=uuid.uuid4().hex,
                message=submitted,
                chat_history=chat,
                conversation=prior_conversation,
            ),
        )

    def complete(self, pending: PendingQuery | None) -> QueryUiUpdate:
        """Finish a pending query as completed or failed without leaking stale details."""
        if pending is None:
            return QueryUiUpdate(
                status="idle",
                chat_history=[],
                question=self._default_question,
                answer_text="",
                rows=[],
                sources=[],
                sql="",
                visible_chat_history=[],
                conversation=[],
            )

        try:
            execution = self._execute(pending.message, conversation=pending.conversation)
            result = execution.answer
            status: QueryStatus = "completed"
        except TimeoutError as exc:
            result = timeout_answer(exc)
            execution = RequestExecution(answer=result, trace=None)
            status = "failed"
        except (
            AttributeError,
            ConnectionError,
            IndexError,
            KeyError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as exc:
            logger.exception("Query transaction failed for %r", pending.message)
            result = request_failure_answer(exc)
            execution = RequestExecution(answer=result, trace=None)
            status = "failed"

        presentation = self._presenter.present(result)
        chat_history = list(pending.chat_history)
        chat_history.extend(
            [
                {"role": "user", "content": pending.message},
                {"role": "assistant", "content": presentation.chat_message},
            ]
        )
        conversation = list(pending.conversation)
        conversation.append(presentation.conversation_turn(pending.message))
        return QueryUiUpdate(
            status=status,
            chat_history=chat_history,
            question=pending.message,
            answer_text=presentation.answer_text,
            rows=presentation.rows,
            sources=presentation.sources,
            sql=presentation.sql,
            visible_chat_history=list(chat_history),
            conversation=conversation,
            execution=execution,
        )

    def run(
        self,
        message: str | None,
        chat_history: list[dict[str, str]] | None,
        conversation: list[dict[str, Any]] | None,
    ) -> QueryUiUpdate:
        """Convenience path for adapters that do not split pending and completion."""
        begun = self.begin(message, chat_history, conversation)
        if begun.pending is None:
            return begun.update
        return self.complete(begun.pending)


def request_failure_answer(exc: Exception) -> StructuredAnswer:
    return local_request_failure_outcome(exc)


def timeout_answer(exc: TimeoutError) -> StructuredAnswer:
    return timeout_outcome(exc)
