"""Stable route facts shared by routing callers and implementations."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, TypeAlias


class TimePeriodType(str, Enum):
    """Discriminated union tag for time period extraction."""

    SINGLE = "single"
    DECADE = "decade"
    RANGE = "range"
    RELATIVE = "relative"


@dataclass
class TimePeriod:
    """Extracted time filter from a natural language query."""

    type: TimePeriodType = TimePeriodType.SINGLE
    value: int | list[int] | dict = field(default_factory=lambda: 0)
    resolved_start: int | None = None
    resolved_end: int | None = None


@dataclass(frozen=True)
class StatQueryCase:
    """Validated route facts for deterministic stat answers."""

    stat: str
    time_period: TimePeriod | None = None
    position: str | None = None
    player_name: str | None = None
    raw_question: str = ""
    intent: Literal["stat_query"] = "stat_query"


@dataclass(frozen=True)
class PlayerBiographyCase:
    """Validated route facts for player biography answers."""

    player_name: str | None = None
    raw_question: str = ""
    intent: Literal["player_biography"] = "player_biography"


@dataclass(frozen=True)
class GroundedDatabaseQuestionCase:
    """Validated route facts for grounded database answers."""

    raw_question: str = ""
    time_period: TimePeriod | None = None
    intent: Literal["grounded_database_question"] = "grounded_database_question"


@dataclass(frozen=True)
class GeneralExplanationCase:
    """Validated route facts for grounded general explanations."""

    raw_question: str = ""
    stat: str | None = None
    intent: Literal["general_explanation"] = "general_explanation"


RoutedCase: TypeAlias = (
    StatQueryCase | PlayerBiographyCase | GroundedDatabaseQuestionCase | GeneralExplanationCase
)
Intent: TypeAlias = Literal[
    "stat_query",
    "player_biography",
    "grounded_database_question",
    "general_explanation",
]


def routed_case(
    *,
    intent: Intent,
    raw_question: str,
    stat: str | None = None,
    time_period: TimePeriod | None = None,
    position: str | None = None,
    player_name: str | None = None,
) -> RoutedCase:
    """Build the narrow route case for an intent."""
    if intent == "stat_query":
        if stat is None:
            raise ValueError("stat_query routes require a stat")
        return StatQueryCase(
            stat=stat,
            time_period=time_period,
            position=position,
            player_name=player_name,
            raw_question=raw_question,
        )
    if intent == "player_biography":
        return PlayerBiographyCase(player_name=player_name, raw_question=raw_question)
    if intent == "grounded_database_question":
        return GroundedDatabaseQuestionCase(raw_question=raw_question, time_period=time_period)
    if intent == "general_explanation":
        return GeneralExplanationCase(raw_question=raw_question, stat=stat)
    raise ValueError(f"Unsupported routed intent: {intent}")
