"""Request dispatch and conversation context assembly."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from baseball_rag.conversation import ConversationResolution
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.routing import (
    FreeformQueryCase,
    GeneralExplanationCase,
    PlayerBiographyCase,
    RoutedCase,
    RouteResult,
    StatQueryCase,
    routed_case,
)
from baseball_rag.routing.query_router import Intent

_SUPPORTED_INTENTS = {
    "stat_query",
    "player_biography",
    "freeform_query",
    "general_explanation",
}


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
        conversation: list[dict[str, Any]] | None = None,
    ) -> StructuredAnswer:
        """Return a structured answer for one user question."""
        self.initialize()
        resolution = self.resolve_followup(question, conversation)
        routed_question = resolution.resolved_question
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
        if isinstance(decision, FreeformQueryCase):
            return self.handlers.freeform_query(routed_question, decision)
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
        if resolution.source_turn is not None:
            result.metadata["original_question"] = original_question
            result.metadata["context_question"] = resolution.resolved_question
            result.metadata["context_source"] = resolution.source_turn
        if result.unsupported:
            return
        if resolution.referenced_player_name is not None:
            result.metadata["context_player_name"] = resolution.referenced_player_name
        elif isinstance(decision, (PlayerBiographyCase, RouteResult)) and (
            decision.intent == "player_biography" and decision.player_name
        ):
            result.metadata["context_player_name"] = decision.player_name


def _validated_legacy_intent(intent: str) -> Intent:
    if intent not in _SUPPORTED_INTENTS:
        raise ValueError(f"Unsupported routed intent: {intent}")
    return cast(Intent, intent)
