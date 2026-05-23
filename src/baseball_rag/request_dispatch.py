"""Request dispatch and conversation context assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from baseball_rag.conversation import ConversationResolution, attach_context_metadata
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.routing import (
    GeneralExplanationCase,
    GroundedDatabaseQuestionCase,
    PlayerBiographyCase,
    RoutedCase,
    StatQueryCase,
)
from baseball_rag.unsupported_policy import unsupported_policy_outcome


@dataclass(frozen=True)
class AnswerHandlers:
    """Concrete answer handlers for routed request cases."""

    stat_query: Callable[[StatQueryCase], StructuredAnswer]
    player_biography: Callable[[str, PlayerBiographyCase], StructuredAnswer]
    grounded_database_question: Callable[[str, GroundedDatabaseQuestionCase], StructuredAnswer]
    general_explanation: Callable[[str, GeneralExplanationCase], StructuredAnswer]


@dataclass(frozen=True)
class RequestAnswerDispatcher:
    """Resolve, route, dispatch, and annotate one user request."""

    resolve_followup: Callable[[str, list[dict[str, Any]] | None], ConversationResolution]
    route_question: Callable[[str], RoutedCase]
    handlers: AnswerHandlers

    def answer(
        self,
        question: str,
        *,
        conversation: list[dict[str, Any]] | None = None,
    ) -> StructuredAnswer:
        """Return a structured answer for one user question."""
        resolution = self.resolve_followup(question, conversation)
        routed_question = resolution.resolved_question
        policy_result = unsupported_policy_outcome(routed_question)
        if policy_result is not None:
            return policy_result
        decision = self.route_question(routed_question)

        result = self._dispatch(routed_question, decision)
        self._attach_context_metadata(
            result,
            original_question=question,
            resolution=resolution,
            decision=decision,
        )
        return result

    def _dispatch(
        self,
        routed_question: str,
        decision: RoutedCase,
    ) -> StructuredAnswer:
        if isinstance(decision, StatQueryCase):
            return self.handlers.stat_query(decision)
        if isinstance(decision, PlayerBiographyCase):
            return self.handlers.player_biography(routed_question, decision)
        if isinstance(decision, GroundedDatabaseQuestionCase):
            return self.handlers.grounded_database_question(routed_question, decision)
        if isinstance(decision, GeneralExplanationCase):
            return self.handlers.general_explanation(routed_question, decision)
        raise TypeError(f"Unsupported routed case type: {type(decision).__name__}")

    def _attach_context_metadata(
        self,
        result: StructuredAnswer,
        *,
        original_question: str,
        resolution: ConversationResolution,
        decision: RoutedCase,
    ) -> None:
        attach_context_metadata(
            result,
            original_question=original_question,
            resolution=resolution,
            decision=decision,
        )
