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
        RetrosheetEventCapability(
            capability_id="batting_stat_streak",
            title="Batting stat game streaks",
            local_table="retrosheet_batting",
            data_source="Retrosheet game-level batting logs",
            supported_query_families=(
                "All-time longest stolen-base game streak",
                "Named player longest stolen-base game streak",
                "Named player longest postseason stolen-base game streak",
                "All-time longest hit streak",
                "Named player longest hit streak",
                "All-time or named player longest home-run game streak",
                "All-time or named player longest RBI game streak",
                "All-time or named player longest run-scored streak",
            ),
            supported_filters=(
                "player full name",
                "regular season",
                "postseason",
            ),
            unsupported_nearby_families=(
                "Team batting stat streaks",
                "Multi-stat batting streaks",
                "Play-level or inning-level batting streaks",
                "Consecutive successful steal attempts without caught stealing",
                "Base-specific steal streaks",
            ),
            unsupported_patterns=(
                re.compile(
                    r"\bteams?\b.*\b(?:stolen bases?|hitting|hits?|home runs?|"
                    r"homers?|hrs?|rbis?|runs? batted in|runs?[- ]scored|"
                    r"scored runs?)\b.*\bstreak\b|"
                    r"\b(?:stolen bases?|hitting|hits?|home runs?|homers?|hrs?|"
                    r"rbis?|runs? batted in|runs?[- ]scored|scored runs?)\b.*"
                    r"\bstreak\b.*\bteams?\b"
                ),
                re.compile(
                    r"\b(?:hit|hitting|hits?|home runs?|homers?|hrs?|rbis?|"
                    r"runs? batted in|runs?[- ]scored|scored runs?|stolen bases?)\b"
                    r".*\b(?:and|plus|with)\b.*\b(?:hit|hitting|hits?|home runs?|"
                    r"homers?|hrs?|rbis?|runs? batted in|runs?[- ]scored|"
                    r"scored runs?|stolen bases?)\b.*\bstreak\b"
                ),
                re.compile(
                    r"\b(?:stolen bases?|hitting|hits?|home runs?|homers?|hrs?|"
                    r"rbis?|runs? batted in|runs?[- ]scored|scored runs?)\b.*"
                    r"\bstreak\b.*\b(?:play|plays|plate appearance|at bat|"
                    r"inning|innings)\b"
                ),
                re.compile(
                    r"\bstolen bases?\b.*\bstreak\b.*\b(?:caught stealing|"
                    r"without being caught|without getting caught)\b"
                ),
                re.compile(
                    r"\bstolen bases?\b.*\bstreak\b.*\b(?:stealing|steal|stolen)\s+"
                    r"(?:second|third|home)\b"
                ),
            ),
        ),
        RetrosheetEventCapability(
            capability_id="pitcher_daily_strikeout_game_log",
            title="Pitcher daily strikeout game logs",
            local_table="retrosheet_pitching",
            data_source="Retrosheet game-level daily pitching logs",
            supported_query_families=(
                "Named pitcher strikeout game log",
                "Named pitcher strikeout-threshold game log",
            ),
            supported_filters=(
                "pitcher full name",
                "pitching strikeouts",
                "threshold",
                "year",
                "regular season",
                "postseason",
            ),
            unsupported_nearby_families=(
                "Pitch-level pitching details",
                "Inning-level pitching events",
                "Team pitching game logs",
            ),
            unsupported_patterns=(
                re.compile(
                    r"\b(?:pitch[- ]by[- ]pitch|pitch-level|pitch level|pitch counts?|pitches)\b"
                    r".*\b(?:strikeouts?|game logs?|pitching logs?)\b|"
                    r"\b(?:strikeouts?|game logs?|pitching logs?)\b.*"
                    r"\b(?:pitch[- ]by[- ]pitch|pitch-level|pitch level|pitch counts?|pitches)\b"
                ),
                re.compile(
                    r"\b(?:inning by inning|inning-level|inning level|innings?)\b"
                    r".*\b(?:strikeouts?|game logs?|pitching logs?)\b|"
                    r"\b(?:strikeouts?|game logs?|pitching logs?)\b.*"
                    r"\b(?:inning by inning|inning-level|inning level|innings?)\b"
                ),
                re.compile(
                    r"\bteams?\b.*\bpitching\b.*\b(?:game logs?|logs?)\b|"
                    r"\bpitching\b.*\b(?:game logs?|logs?)\b.*\bteams?\b"
                ),
            ),
        ),
        RetrosheetEventCapability(
            capability_id="player_batting_game_log",
            title="Player batting daily game logs",
            local_table="retrosheet_batting",
            data_source="Retrosheet game-level daily batting logs",
            supported_query_families=(
                "Named player batting stat game log",
                "Named player batting stat threshold game log",
                "Named player batting stat season game log",
                "Named player postseason batting stat game log",
            ),
            supported_filters=(
                "player full name",
                "batting stat",
                "threshold",
                "year",
                "regular season",
                "postseason",
            ),
            unsupported_nearby_families=(
                "Team batting game logs",
                "Multi-stat batting game logs",
                "Play-level or inning-level batting details",
                "Base-specific stolen-base details",
            ),
            unsupported_patterns=(
                re.compile(
                    r"\bteams?\b.*\b(?:stolen bases?|hits?|home runs?|homers?|"
                    r"hrs?|rbis?|runs? batted in|runs?[- ]scored|scored runs?)\b"
                    r".*\b(?:games?|game logs?|logs?)\b|"
                    r"\b(?:stolen bases?|hits?|home runs?|homers?|hrs?|rbis?|"
                    r"runs? batted in|runs?[- ]scored|scored runs?)\b.*"
                    r"\b(?:games?|game logs?|logs?)\b.*\bteams?\b"
                ),
                re.compile(
                    r"\b(?:stolen bases?|hits?|home runs?|homers?|hrs?|rbis?|"
                    r"runs? batted in|runs?[- ]scored|scored runs?)\b"
                    r".*\b(?:and|plus|with)\b.*\b(?:stolen bases?|hits?|"
                    r"home runs?|homers?|hrs?|rbis?|runs? batted in|runs?[- ]scored|"
                    r"scored runs?)\b.*\b(?:games?|game logs?|logs?)\b|"
                    r"\b(?:games?|game logs?|logs?)\b.*\b(?:stolen bases?|hits?|"
                    r"home runs?|homers?|hrs?|rbis?|runs? batted in|runs?[- ]scored|"
                    r"scored runs?)\b.*\b(?:and|plus|with)\b.*\b(?:stolen bases?|"
                    r"hits?|home runs?|homers?|hrs?|rbis?|runs? batted in|"
                    r"runs?[- ]scored|scored runs?)\b"
                ),
                re.compile(
                    r"\b(?:play by play|play-level|play level|plate appearance|"
                    r"at bat|inning by inning|inning-level|inning level|innings?)\b"
                    r".*\b(?:stolen bases?|hits?|home runs?|homers?|hrs?|rbis?|"
                    r"runs? batted in|runs?[- ]scored|scored runs?|game logs?)\b|"
                    r"\b(?:stolen bases?|hits?|home runs?|homers?|hrs?|rbis?|"
                    r"runs? batted in|runs?[- ]scored|scored runs?|game logs?)\b.*"
                    r"\b(?:play by play|play-level|play level|plate appearance|"
                    r"at bat|inning by inning|inning-level|inning level|innings?)\b"
                ),
                re.compile(
                    r"\b(?:stealing|steal|stolen)\s+(?:second|third|home)\b.*"
                    r"\b(?:games?|game logs?|logs?)\b|"
                    r"\b(?:games?|game logs?|logs?)\b.*"
                    r"\b(?:stealing|steal|stolen)\s+(?:second|third|home)\b"
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
