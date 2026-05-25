"""Ordered route-decision execution for the router implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from baseball_rag.routing.contracts import RoutedCase


@dataclass(frozen=True)
class RouteDecisionAttempt:
    """One decision Adapter result with optional evidence text."""

    route: RoutedCase | None
    reason: str | None = None
    fallback_reason: str | None = None


RouteDecisionResult = RoutedCase | RouteDecisionAttempt | None
RouteDecision = Callable[[], RouteDecisionResult]


@dataclass(frozen=True)
class RouteDecisionStep:
    """Named Adapter in the ordered routing decision chain."""

    name: str
    decide: RouteDecision
    decline_reason: str = "no_match"


@dataclass(frozen=True)
class RouteDecisionEvidence:
    """Inspectable evidence for one route decision step."""

    step: str
    matched: bool
    intent: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class RouteDecisionOutcome:
    """Route facts plus ordered evidence for why that route won."""

    routed_case: RoutedCase
    winner: str
    steps: tuple[RouteDecisionEvidence, ...]
    fallback_reason: str | None = None

    @property
    def route(self) -> RoutedCase:
        """Compatibility alias for callers that prefer the shorter name."""
        return self.routed_case


@dataclass(frozen=True)
class RouteDecisionChain:
    """Run ordered routing Adapters until one produces route facts."""

    decisions: tuple[RouteDecisionStep | RouteDecision, ...]
    fallback: RouteDecisionStep | RouteDecision

    def decide(self) -> RoutedCase:
        return self.decide_with_evidence().routed_case

    def decide_with_evidence(self) -> RouteDecisionOutcome:
        evidence: list[RouteDecisionEvidence] = []
        for index, item in enumerate(self.decisions, start=1):
            step = _coerce_step(item, name=f"decision_{index}")
            attempt = _coerce_attempt(step.decide())
            if attempt.route is not None:
                evidence.append(_matched_evidence(step, attempt))
                return RouteDecisionOutcome(
                    routed_case=attempt.route,
                    winner=step.name,
                    steps=tuple(evidence),
                )
            evidence.append(
                RouteDecisionEvidence(
                    step=step.name,
                    matched=False,
                    reason=attempt.reason or step.decline_reason,
                )
            )

        fallback = _coerce_step(self.fallback, name="terminal")
        attempt = _coerce_attempt(fallback.decide())
        if attempt.route is None:
            raise RuntimeError("terminal route returned no route")
        evidence.append(_matched_evidence(fallback, attempt))
        return RouteDecisionOutcome(
            routed_case=attempt.route,
            winner=fallback.name,
            steps=tuple(evidence),
            fallback_reason=attempt.fallback_reason,
        )


def _coerce_step(item: RouteDecisionStep | RouteDecision, *, name: str) -> RouteDecisionStep:
    if isinstance(item, RouteDecisionStep):
        return item
    return RouteDecisionStep(name, item)


def _coerce_attempt(result: RouteDecisionResult) -> RouteDecisionAttempt:
    if isinstance(result, RouteDecisionAttempt):
        return result
    return RouteDecisionAttempt(route=result)


def _matched_evidence(
    step: RouteDecisionStep,
    attempt: RouteDecisionAttempt,
) -> RouteDecisionEvidence:
    intent = attempt.route.intent if attempt.route is not None else None
    return RouteDecisionEvidence(
        step=step.name,
        matched=True,
        intent=intent,
        reason=attempt.reason,
    )
