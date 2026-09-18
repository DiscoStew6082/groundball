"""The shared assistant answers with records, not model-authored factual prose."""

from datetime import UTC, datetime

import pytest

from baseball_rag.assistant import ResearchSources, research_answer
from baseball_rag.source_attribution import RETROSHEET_CREDIT


def record(identity, title, url, fields):
    return {
        "id": identity,
        "title": title,
        "url": url,
        "observed_at": datetime.now(UTC).isoformat(),
        "record": fields,
    }


def fixture(team):
    assert team == "ATL"
    return {
        "id": "2601483",
        "home_team_id": "HOU",
        "home_team": "Houston Astros",
        "away_team_id": "ATL",
        "away_team": "Atlanta Braves",
        "starts_at": "2099-09-19T00:10:00Z",
        "status": "NS",
        "venue": "Daikin Park",
        "source": record(
            "fixture",
            "TheSportsDB fixture",
            "https://www.thesportsdb.com/event/2601483",
            {"event_id": "2601483"},
        ),
    }


def meetings(team, opponent):
    assert (team, opponent) == ("ATL", "HOU")
    return [
        {
            "year": 2021,
            "winner_id": "ATL",
            "loser_id": "HOU",
            "winner_wins": 4,
            "loser_wins": 2,
            "source": record(
                "ws2021",
                "Retrosheet 2021 World Series",
                "https://www.retrosheet.org/boxesetc/2021/YPS_2021.htm",
                {"winner": "ATL", "loser": "HOU", "wins": [4, 2]},
            ),
        }
    ]


def test_briefing_uses_real_query_evidence_and_credits_retrosheet():
    answer = research_answer(
        {"topic": "pregame", "team": "ATL", "count": 5}, sources=ResearchSources(fixture, meetings)
    )
    assert answer["kind"] == "answer"
    assert len(answer["facts"]) == 5
    assert "4–2" in answer["facts"][0]["text"]
    assert any("307" in fact["text"] for fact in answer["facts"])
    assert any("73" in fact["text"] and "41" in fact["text"] for fact in answer["facts"])
    database_facts = [fact for fact in answer["facts"] if "query_run" in fact]
    assert database_facts
    assert all(fact["query_run"]["verification"]["status"] == "verified" for fact in database_facts)
    assert all(
        set(fact["source_ids"]) <= {source["id"] for source in answer["sources"]}
        for fact in answer["facts"]
    )
    assert any(credit["text"] == RETROSHEET_CREDIT for credit in answer["attributions"])
    assert all(source["fingerprint"] for source in answer["sources"])


def test_missing_fixture_does_not_manufacture_opponent_or_current_facts():
    answer = research_answer(
        {"topic": "pregame", "team": "ATL", "count": 5},
        sources=ResearchSources(lambda _: None, meetings),
    )
    assert answer["kind"] == "unavailable"
    assert "facts" not in answer


@pytest.mark.parametrize(
    "proposal",
    [
        {"topic": "pregame", "team": "imaginary", "count": 5},
        {"topic": "pregame", "team": "ATL", "count": True},
        {"topic": "pregame", "team": "ATL", "count": 6},
        {"topic": "pregame", "team": "ATL", "count": 5, "answer": "invented"},
    ],
)
def test_invalid_model_research_request_cannot_supply_facts(proposal):
    with pytest.raises(ValueError):
        research_answer(proposal, sources=ResearchSources(fixture, meetings))


def test_historical_team_context_does_not_require_network_or_credit_unused_source():
    answer = research_answer({"topic": "team_history", "team": "ATL", "count": 3})
    assert answer["kind"] == "answer"
    assert len(answer["facts"]) == 3
    assert answer["fixture"] is None
    assert not any(credit["provider"] == "retrosheet" for credit in answer["attributions"])


def test_missing_postseason_source_gives_partial_evidence_not_invented_meeting():
    def unavailable(*_):
        raise OSError("source offline")

    answer = research_answer(
        {"topic": "pregame", "team": "ATL", "count": 5},
        sources=ResearchSources(fixture, unavailable),
    )
    assert answer["kind"] == "answer"
    assert len(answer["facts"]) < 5
    assert answer["limitations"]
    assert not any(credit["provider"] == "retrosheet" for credit in answer["attributions"])
