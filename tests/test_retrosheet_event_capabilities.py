"""Tests for the Retrosheet event support matrix."""

import pytest

from baseball_rag.retrosheet_event_capabilities import (
    retrosheet_event_capabilities,
    supported_retrosheet_event_summary,
    unsupported_retrosheet_event_reason,
)


def test_retrosheet_event_matrix_documents_strikeout_side_projection():
    capabilities = retrosheet_event_capabilities()

    assert len(capabilities) == 1
    capability = capabilities[0]
    assert capability.capability_id == "pitcher_strikeout_side"
    assert capability.local_table == "retrosheet_pitcher_strikeout_side_events"
    assert capability.supported_query_families == (
        "Named pitcher career strikeout-side count",
        "Named pitcher season strikeout-side count",
        "Pitcher career strikeout-side leaderboard",
    )
    assert capability.supported_filters == ("pitcher full name", "career", "year")
    assert capability.unsupported_nearby_families == (
        "Inherited runners or entering with runners on base",
        "Pitch counts or immaculate innings",
        "Called/swinging strikeout splits",
        "Postseason-only splits",
        "Opponent, batter, team, park, game-specific, or game-log filters",
    )


@pytest.mark.parametrize(
    "question",
    [
        "how often did Rollie Fingers come in with men on base",
        "how many immaculate innings did Rollie Fingers throw",
        "how many called strikeout-side innings did Rollie Fingers have",
        "how often did Rollie Fingers strike out the side in the postseason",
        "how many times did Rollie Fingers strike out the side against the Yankees",
        "how many times did Rollie Fingers strike out the side in a game in 1972",
    ],
)
def test_retrosheet_event_matrix_builds_policy_reason_for_nearby_queries(question):
    reason = unsupported_retrosheet_event_reason(question)

    assert reason is not None
    assert "Retrosheet event data is local" in reason
    assert supported_retrosheet_event_summary() in reason
