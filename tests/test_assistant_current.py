"""Current answers require fresh, consistently scoped retained source records."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from baseball_rag.assistant import ResearchSources, research_answer, validate_answer_context


def bound(data, *, observed=None):
    data = deepcopy(data)
    data["source"] = {
        "id": "mlb",
        "title": "MLB current records",
        "url": "https://statsapi.mlb.com/api/v1/stats/leaders",
        "observed_at": (observed or datetime.now(UTC)).isoformat(),
        "record": {"normalized": deepcopy(data)},
    }
    return data


def leaders():
    return {
        "season": datetime.now(UTC).year,
        "statistic": "HR",
        "rows": [
            {
                "rank": rank,
                "player_id": index + 1,
                "player_name": name,
                "team_id": "ATL",
                "team_name": "Atlanta Braves",
                "value": value,
            }
            for index, (rank, name, value) in enumerate(
                [(1, "First Player", 45), (2, "Second Player", 44), (2, "Third Player", 44)]
            )
        ],
    }


def answer(data, *, topic="current_leaders", count=2):
    request = {"topic": topic, "count": count}
    request.update({"statistic": "HR"} if topic == "current_leaders" else {"team": "ATL"})
    return research_answer(
        request,
        sources=ResearchSources(
            next_fixture=lambda _: None,
            postseason_meetings=lambda *_: [],
            batting_leaders=lambda *_: data,
            probable_pitchers=lambda _: data,
        ),
    )


def test_current_leaders_include_cutoff_ties_and_preserve_evidence():
    data = bound(leaders())
    result = answer(data)
    assert result["kind"] == "answer"
    assert all(row["player_name"] in result["facts"][0]["text"] for row in data["rows"])
    assert result["sources"][0]["record"]["normalized"]["rows"] == data["rows"]


def test_normalized_rows_cannot_differ_from_retained_source_records():
    data = bound(leaders())
    data["rows"][0]["value"] = 999
    assert answer(data)["kind"] == "unavailable"


@pytest.mark.parametrize(
    "change",
    [
        {"value": 45.5},
        {"rank": 2},
        {"player_id": True},
        {"team_name": "Houston Astros"},
        {"player_name": " "},
    ],
)
def test_invalid_leader_values_and_identities_are_unavailable(change):
    data = leaders()
    data["rows"][0].update(change)
    assert answer(bound(data))["kind"] == "unavailable"


def test_only_ties_may_extend_the_requested_leader_count():
    data = leaders()
    data["rows"][2].update(value=43, rank=3)
    assert answer(bound(data))["kind"] == "unavailable"


def probables():
    return {
        "game_id": 123,
        "home_team_id": "HOU",
        "away_team_id": "ATL",
        "home_team": "Houston Astros",
        "away_team": "Atlanta Braves",
        "starts_at": (datetime.now(UTC) + timedelta(hours=3)).isoformat(),
        "status": "probable",
        "home_pitcher": {"id": 99, "name": "Listed Pitcher"},
        "away_pitcher": None,
    }


def test_probable_pitcher_and_unannounced_pitcher_remain_distinct():
    result = answer(bound(probables()), topic="probable_pitchers")
    assert result["kind"] == "answer" and result["fixture"]["status"] == "probable"
    assert len(result["facts"]) == 2
    assert any("Listed Pitcher" in fact["text"] for fact in result["facts"])
    only_braves = answer(bound(probables()), topic="probable_pitchers", count=1)
    assert len(only_braves["facts"]) == 1
    assert "Listed Pitcher" not in only_braves["facts"][0]["text"]


@pytest.mark.parametrize(
    "change",
    [
        {"starts_at": (datetime.now(UTC) + timedelta(days=8)).isoformat()},
        {"home_team": "Atlanta Braves"},
        {"game_id": True},
        {"away_pitcher": {}},
        {"away_pitcher": {"id": 99, "name": "Listed Pitcher"}},
    ],
)
def test_probable_scope_or_missing_identity_cannot_become_a_fact(change):
    data = probables()
    data.update(change)
    assert answer(bound(data), topic="probable_pitchers")["kind"] == "unavailable"


@pytest.mark.parametrize("minutes", [-11, 2])
def test_current_observation_must_be_fresh_and_not_in_the_future(minutes):
    data = bound(leaders(), observed=datetime.now(UTC) + timedelta(minutes=minutes))
    assert answer(data)["kind"] == "unavailable"


@pytest.mark.parametrize("bad", [[], {}, object()])
def test_context_nonscalar_team_is_a_validation_error(bad):
    with pytest.raises(ValueError):
        validate_answer_context({"version": 1, "topic": "pregame", "team": bad})
