"""Request dispatch and conversation context assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from baseball_rag.conversation import ConversationResolution, attach_context_metadata
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.routing import (
    GeneralExplanationCase,
    GroundedDatabaseQuestionCase,
    PlayerBiographyCase,
    RoutedCase,
    RouteResult,
    StatQueryCase,
    routed_case,
)
from baseball_rag.routing.query_router import Intent
from baseball_rag.unsupported_policy import unsupported_policy_outcome

_SUPPORTED_INTENTS = {
    "stat_query",
    "player_biography",
    "grounded_database_question",
    "general_explanation",
}


@dataclass(frozen=True)
class AnswerHandlers:
    """Concrete answer handlers for routed request cases."""

    stat_query: Callable[[Any], StructuredAnswer]
    player_biography: Callable[..., StructuredAnswer]
    grounded_database_question: Callable[[str, Any], StructuredAnswer]
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
        conversation: list[dict[str, Any]] | None = None,
    ) -> StructuredAnswer:
        """Return a structured answer for one user question."""
        self.initialize()
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
        decision: RoutedCase | RouteResult,
    ) -> StructuredAnswer:
        if isinstance(decision, StatQueryCase):
            return self.handlers.stat_query(decision)
        if isinstance(decision, PlayerBiographyCase):
            return self.handlers.player_biography(routed_question, decision)
        if isinstance(decision, GroundedDatabaseQuestionCase):
            return self.handlers.grounded_database_question(routed_question, decision)
        if isinstance(decision, GeneralExplanationCase):
            return self.handlers.general_explanation(routed_question, decision)
        if not isinstance(decision, RouteResult):
            raise TypeError(f"Unsupported routed case type: {type(decision).__name__}")
        return self._dispatch_legacy_route_result(routed_question, decision)

    def _dispatch_legacy_route_result(
        self,
        routed_question: str,
        decision: RouteResult,
    ) -> StructuredAnswer:
        normalized = routed_case(
            intent=_validated_legacy_intent(decision.intent),
            stat=decision.stat,
            time_period=decision.time_period,
            position=decision.position,
            player_name=decision.player_name,
            raw_question=decision.raw_question,
        )
        return self._dispatch(routed_question, normalized)

    def _attach_context_metadata(
        self,
        result: StructuredAnswer,
        *,
        original_question: str,
        resolution: ConversationResolution,
        decision: Any,
    ) -> None:
        attach_context_metadata(
            result,
            original_question=original_question,
            resolution=resolution,
            decision=decision,
        )


def _validated_legacy_intent(intent: str) -> Intent:
    if intent not in _SUPPORTED_INTENTS:
        raise ValueError(f"Unsupported routed intent: {intent}")
    return cast(Intent, intent)
