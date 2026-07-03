"""Tests for the Retrosheet event support matrix."""

import pytest

from baseball_rag.retrosheet_event_capabilities import (
    retrosheet_event_capabilities,
    supported_retrosheet_event_summary,
    unsupported_retrosheet_event_reason,
)


def test_retrosheet_event_matrix_documents_strikeout_side_projection():
    capabilities = retrosheet_event_capabilities()

    assert len(capabilities) == 2
    capability = capabilities[0]
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


def test_retrosheet_event_matrix_documents_stolen_base_streaks():
    capability = retrosheet_event_capabilities()[1]

    assert capability.capability_id == "stolen_base_streak"
    assert capability.local_table == "retrosheet_batting"
    assert capability.supported_query_families == (
        "All-time longest stolen-base game streak",
        "Named player longest stolen-base game streak",
        "Named player longest postseason stolen-base game streak",
    )
    assert capability.supported_filters == (
        "player full name",
        "regular season",
        "postseason",
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
        "what is the longest stolen base streak without being caught stealing",
        "longest stolen base streak stealing third base",
    ],
)
def test_retrosheet_event_matrix_builds_policy_reason_for_nearby_queries(question):
    reason = unsupported_retrosheet_event_reason(question)

    assert reason is not None
    assert "Retrosheet event data is local" in reason
    assert supported_retrosheet_event_summary() in reason
