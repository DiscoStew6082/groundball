"""Request dispatch and conversation context assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from baseball_rag.conversation import ConversationResolution
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.retrieval.strategies import RetrievalStrategy


@dataclass(frozen=True)
class AnswerHandlers:
    """Concrete answer handlers for routed request cases."""

    stat_query: Callable[[Any], StructuredAnswer]
    player_biography: Callable[..., StructuredAnswer]
    freeform_query: Callable[[str, Any], StructuredAnswer]
    general_explanation: Callable[..., StructuredAnswer]


@dataclass(frozen=True)
class RequestAnswerDispatcher:
    """Resolve, route, dispatch, and annotate one user request."""

    initialize: Callable[[], None]
    resolve_followup: Callable[[str, list[dict[str, Any]] | None], ConversationResolution]
    route_question: Callable[[str], Any]
    handlers: AnswerHandlers

    def answer(
        self,
        question: str,
        *,
        retrieval_strategy: str | RetrievalStrategy | None = None,
        conversation: list[dict[str, Any]] | None = None,
    ) -> StructuredAnswer:
        """Return a structured answer for one user question."""
        self.initialize()
        resolution = self.resolve_followup(question, conversation)
        routed_question = resolution.resolved_question
        decision = self.route_question(routed_question)

        result = self._dispatch(
            routed_question,
            decision,
            retrieval_strategy=retrieval_strategy,
        )
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
        decision: Any,
        *,
        retrieval_strategy: str | RetrievalStrategy | None,
    ) -> StructuredAnswer:
        if decision.intent == "stat_query":
            return self.handlers.stat_query(decision)
        if decision.intent == "player_biography":
            return self.handlers.player_biography(
                routed_question,
                decision,
                retrieval_strategy=retrieval_strategy,
            )
        if decision.intent == "freeform_query":
            return self.handlers.freeform_query(routed_question, decision)
        return self.handlers.general_explanation(
            routed_question,
            decision,
            retrieval_strategy=retrieval_strategy,
        )

    def _attach_context_metadata(
        self,
        result: StructuredAnswer,
        *,
        original_question: str,
        resolution: ConversationResolution,
        decision: Any,
    ) -> None:
        if resolution.source_turn is not None:
            result.metadata["original_question"] = original_question
            result.metadata["context_question"] = resolution.resolved_question
            result.metadata["context_source"] = resolution.source_turn
        if result.unsupported:
            return
        if resolution.referenced_player_name is not None:
            result.metadata["context_player_name"] = resolution.referenced_player_name
        elif decision.intent == "player_biography" and decision.player_name:
            result.metadata["context_player_name"] = decision.player_name
