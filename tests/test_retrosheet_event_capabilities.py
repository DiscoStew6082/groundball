"""Tests for the Retrosheet event support matrix."""

import pytest

from baseball_rag.retrosheet_event_capabilities import (
    RetrosheetEventCapability,
    retrosheet_event_capabilities,
    supported_retrosheet_event_summary,
    unsupported_retrosheet_event_reason,
)


def _capability(capability_id: str) -> RetrosheetEventCapability:
    return next(
        capability
        for capability in retrosheet_event_capabilities()
        if capability.capability_id == capability_id
    )


def test_retrosheet_event_matrix_documents_strikeout_side_projection():
    capabilities = retrosheet_event_capabilities()

    assert len(capabilities) == 4
    capability = _capability("pitcher_strikeout_side")
    assert capability.capability_id == "pitcher_strikeout_side"
    assert capability.local_table == "retrosheet_pitcher_strikeout_side_events"
    assert capability.supported_query_families == (
        "Named pitcher career strikeout-side count",
        "Named pitcher season strikeout-side count",
        "Named pitcher strikeout-side game log",
        "Named pitcher strikeout-side count or game log by opponent team",
        "Pitcher career strikeout-side leaderboard",
    )
    assert capability.supported_filters == (
        "pitcher full name",
        "career",
        "year",
        "game log",
        "opponent team",
    )
    assert capability.unsupported_nearby_families == (
        "Inherited runners or entering with runners on base",
        "Pitch counts or immaculate innings",
        "Called/swinging strikeout splits",
        "Postseason-only splits",
        "Batter or park filters",
    )


def test_retrosheet_event_matrix_documents_batting_stat_streaks():
    capability = _capability("batting_stat_streak")

    assert capability.capability_id == "batting_stat_streak"
    assert capability.local_table == "retrosheet_batting"
    assert capability.supported_query_families == (
        "All-time longest stolen-base game streak",
        "Named player longest stolen-base game streak",
        "Named player longest postseason stolen-base game streak",
        "All-time longest hit streak",
        "Named player longest hit streak",
        "All-time or named player longest home-run game streak",
        "All-time or named player longest RBI game streak",
        "All-time or named player longest run-scored streak",
    )
    assert capability.supported_filters == (
        "player full name",
        "regular season",
        "postseason",
    )


def test_retrosheet_event_matrix_documents_pitcher_daily_strikeout_game_logs():
    capability = _capability("pitcher_daily_strikeout_game_log")

    assert capability.capability_id == "pitcher_daily_strikeout_game_log"
    assert capability.local_table == "retrosheet_pitching"
    assert capability.supported_query_families == (
        "Named pitcher strikeout game log",
        "Named pitcher strikeout-threshold game log",
    )
    assert capability.supported_filters == (
        "pitcher full name",
        "pitching strikeouts",
        "threshold",
        "year",
        "regular season",
        "postseason",
    )
    assert capability.unsupported_nearby_families == (
        "Pitch-level pitching details",
        "Inning-level pitching events",
        "Team pitching game logs",
    )


def test_retrosheet_event_matrix_documents_player_batting_game_logs():
    capability = _capability("player_batting_game_log")

    assert capability.capability_id == "player_batting_game_log"
    assert capability.local_table == "retrosheet_batting"
    assert capability.supported_query_families == (
        "Named player batting stat game log",
        "Named player batting stat threshold game log",
        "Named player batting stat season game log",
        "Named player postseason batting stat game log",
    )
    assert capability.supported_filters == (
        "player full name",
        "batting stat",
        "threshold",
        "year",
        "regular season",
        "postseason",
    )
    assert capability.unsupported_nearby_families == (
        "Team batting game logs",
        "Multi-stat batting game logs",
        "Play-level or inning-level batting details",
        "Base-specific stolen-base details",
    )


@pytest.mark.parametrize(
    "question",
    [
        "how often did Rollie Fingers come in with men on base",
        "how many immaculate innings did Rollie Fingers throw",
        "how many called strikeout-side innings did Rollie Fingers have",
        "how often did Rollie Fingers strike out the side in the postseason",
        "how many called strikeout-side innings did Rollie Fingers have at Yankee Stadium",
        "what team has the longest stolen base streak",
        "what team has the longest hitting streak",
        "what is the longest hit and home run streak",
        "what is the longest home run streak by plate appearance",
        "what is the longest RBI streak by inning",
        "what is the longest stolen base streak without being caught stealing",
        "longest stolen base streak stealing third base",
        "show Nolan Ryan pitch-by-pitch strikeout game logs",
        "show Nolan Ryan inning by inning strikeout game logs",
        "show team pitching game logs with at least 10 strikeouts",
        "show team stolen base game logs",
        "show Rickey Henderson games with stolen bases and home runs",
        "show Rickey Henderson play by play stolen base game log",
        "show Rickey Henderson games stealing third base",
    ],
)
def test_retrosheet_event_matrix_builds_policy_reason_for_nearby_queries(question):
    reason = unsupported_retrosheet_event_reason(question)

    assert reason is not None
    assert "Retrosheet event data is local" in reason
    assert supported_retrosheet_event_summary() in reason
