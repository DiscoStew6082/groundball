"""Support matrix for local Retrosheet event-derived query capabilities."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

_STRIKEOUT_SIDE_PHRASE = r"(?:\b(?:strike|struck) out the side\b|\bstrikeout[- ]side\b)"


@dataclass(frozen=True)
class RetrosheetEventCapability:
    """One modeled Retrosheet event-derived query family."""

    capability_id: str
    title: str
    local_table: str
    data_source: str
    supported_query_families: tuple[str, ...]
    supported_filters: tuple[str, ...]
    unsupported_nearby_families: tuple[str, ...]
    unsupported_patterns: tuple[re.Pattern[str], ...]

    def matches_unsupported_nearby_query(self, question: str) -> bool:
        lower_question = question.lower()
        return any(pattern.search(lower_question) for pattern in self.unsupported_patterns)

    def as_matrix_row(self) -> Mapping[str, object]:
        """Return a stable row for docs, diagnostics, or future UI display."""
        return {
            "capability_id": self.capability_id,
            "title": self.title,
            "local_table": self.local_table,
            "data_source": self.data_source,
            "supported_query_families": self.supported_query_families,
            "supported_filters": self.supported_filters,
            "unsupported_nearby_families": self.unsupported_nearby_families,
        }


@lru_cache(maxsize=1)
def retrosheet_event_capabilities() -> tuple[RetrosheetEventCapability, ...]:
    """Return the currently supported local Retrosheet event query matrix."""
    return (
        RetrosheetEventCapability(
            capability_id="pitcher_strikeout_side",
            title="Pitcher strikeout-side counts",
            local_table="retrosheet_pitcher_strikeout_side_events",
            data_source="Retrosheet event-derived local projection",
            supported_query_families=(
                "Named pitcher career strikeout-side count",
                "Named pitcher season strikeout-side count",
                "Named pitcher strikeout-side game log",
                "Named pitcher strikeout-side count or game log by opponent team",
                "Pitcher career strikeout-side leaderboard",
            ),
            supported_filters=(
                "pitcher full name",
                "career",
                "year",
                "game log",
                "opponent team",
            ),
            unsupported_nearby_families=(
                "Inherited runners or entering with runners on base",
                "Pitch counts or immaculate innings",
                "Called/swinging strikeout splits",
                "Postseason-only splits",
                "Batter or park filters",
            ),
            unsupported_patterns=(
                re.compile(
                    r"\b(?:enter(?:ed|s)?|came in|come in|came into|come into|"
                    r"inherited|inherit)\b.*\b(?:runners?|men) on(?: base)?\b|"
                    r"\b(?:inherited|inherit) runners?\b"
                ),
                re.compile(
                    _STRIKEOUT_SIDE_PHRASE + r".*\b(?:pitch counts?|pitches|"
                    r"immaculate innings?)\b|"
                    r"\b(?:pitch counts?|pitches|immaculate innings?)\b.*"
                    + _STRIKEOUT_SIDE_PHRASE
                    + r"|"
                    r"\bimmaculate innings?\b"
                ),
                re.compile(
                    _STRIKEOUT_SIDE_PHRASE + r".*\b(?:called|looking|swinging)\b|"
                    r"\b(?:called|looking|swinging)\b.*" + _STRIKEOUT_SIDE_PHRASE
                ),
                re.compile(
                    _STRIKEOUT_SIDE_PHRASE + r".*\b(?:postseason|playoffs?|"
                    r"world series)\b|"
                    r"\b(?:postseason|playoffs?|world series)\b.*" + _STRIKEOUT_SIDE_PHRASE
                ),
                re.compile(
                    _STRIKEOUT_SIDE_PHRASE + r".*\b(?:batter|park|stadium|ballpark)\b|"
                    r"\b(?:batter|park|stadium|ballpark)\b.*" + _STRIKEOUT_SIDE_PHRASE
                ),
            ),
        ),
    )


def retrosheet_event_support_matrix() -> tuple[Mapping[str, object], ...]:
    """Return the Retrosheet event support matrix as serializable rows."""
    return tuple(capability.as_matrix_row() for capability in retrosheet_event_capabilities())


def supported_retrosheet_event_summary() -> str:
    """Return a short human summary of currently supported Retrosheet event queries."""
    supported = [
        family
        for capability in retrosheet_event_capabilities()
        for family in capability.supported_query_families
    ]
    return "; ".join(supported)


def unsupported_retrosheet_event_reason(question: str) -> str | None:
    """Return a deterministic unsupported reason for nearby unmodeled event queries."""
    for capability in retrosheet_event_capabilities():
        if capability.matches_unsupported_nearby_query(question):
            return (
                "Retrosheet event data is local, but this event query is not modeled yet. "
                f"Supported Retrosheet event queries currently cover: "
                f"{supported_retrosheet_event_summary()}."
            )
    return None
