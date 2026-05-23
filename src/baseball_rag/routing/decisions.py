"""Ordered route-decision execution for the router implementation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from baseball_rag.routing.contracts import RoutedCase

RouteDecision = Callable[[], RoutedCase | None]


@dataclass(frozen=True)
class RouteDecisionChain:
    """Run ordered routing Adapters until one produces route facts."""

    decisions: tuple[RouteDecision, ...]
    fallback: RouteDecision

    def decide(self) -> RoutedCase:
        for decision in self.decisions:
            routed = decision()
            if routed is not None:
                return routed
        fallback_route = self.fallback()
        if fallback_route is None:
            raise RuntimeError("route decision fallback returned no route")
        return fallback_route
