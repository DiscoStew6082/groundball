"""The shared assistant answers with records, not model-authored factual prose."""

from datetime import UTC, datetime, timedelta

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
    data = {
        "id": "2601483",
        "home_team_id": "HOU",
        "home_team": "Houston Astros",
        "away_team_id": "ATL",
        "away_team": "Atlanta Braves",
        "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "status": "NS",
        "venue": "Daikin Park",
        "source": record(
            "fixture",
            "TheSportsDB fixture",
            "https://www.thesportsdb.com/event/2601483",
            {"event_id": "2601483"},
        ),
    }
    data["source"]["record"]["normalized"] = {
        key: data[key]
        for key in ("id", "home_team_id", "away_team_id", "starts_at", "status", "venue")
    }
    return data


@pytest.mark.parametrize("fault", ["stale", "future_observation", "unbound", "wrong_team"])
def test_pregame_refuses_stale_or_unbound_fixture_evidence(fault):
    def invalid_fixture(team):
        data = fixture(team)
        if fault == "stale":
            data["source"]["observed_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        elif fault == "future_observation":
            data["source"]["observed_at"] = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
        elif fault == "unbound":
            del data["source"]["record"]["normalized"]
        else:
            data["source"]["record"]["normalized"]["home_team_id"] = "NYA"
        return data

    answer = research_answer(
        {"topic": "pregame", "team": "ATL", "count": 1},
        sources=ResearchSources(invalid_fixture, meetings),
    )
    assert answer["kind"] == "unavailable"
    assert "fixture" not in answer


@pytest.mark.parametrize(
    "shape", ["wide_array", "large_string", "too_many_fields", "invalid_start"]
)
def test_pregame_refuses_oversized_adapter_envelopes(shape):
    def oversized_fixture(team):
        data = fixture(team)
        if shape == "wide_array":
            data["untrusted_extra"] = [0] * 129
        elif shape == "large_string":
            data["untrusted_extra"] = "x" * 200_001
        elif shape == "invalid_start":
            data["starts_at"] = 123
        else:
            data.update({f"extra_{index}": index for index in range(65)})
        return data

    result = research_answer(
        {"topic": "pregame", "team": "ATL", "count": 1},
        sources=ResearchSources(oversized_fixture, meetings),
    )
    assert result["kind"] == "unavailable"


@pytest.mark.parametrize(
    "shape", ["many_meetings", "deep_record", "cyclic_record", "missing_source", "list_source"]
)
def test_series_refuses_invalid_meeting_envelopes(shape):
    def invalid_meetings(team, opponent):
        data = meetings(team, opponent)
        if shape == "many_meetings":
            return data * 129
        if shape in {"missing_source", "list_source"}:
            data[0]["source"] = None if shape == "missing_source" else []
            return data
        record = data[0]["source"]["record"]
        if shape == "cyclic_record":
            record["extra"] = record
        else:
            extra = "leaf"
            for _ in range(20):
                extra = {"child": extra}
            record["extra"] = extra
        return data

    result = research_answer(
        {"topic": "series_meeting", "team": "ATL", "opponent": "HOU", "season": 2021},
        sources=ResearchSources(fixture, invalid_meetings),
    )
    assert result["kind"] == "unavailable"


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
                {
                    "year": 2021,
                    "round": "World Series",
                    "games": [
                        ["20211026", "0", "ATL", "HOU", 6, 2],
                        ["20211027", "0", "ATL", "HOU", 2, 7],
                        ["20211029", "0", "HOU", "ATL", 0, 2],
                        ["20211030", "0", "HOU", "ATL", 2, 3],
                        ["20211031", "0", "HOU", "ATL", 9, 5],
                        ["20211102", "0", "ATL", "HOU", 7, 0],
                    ],
                },
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
