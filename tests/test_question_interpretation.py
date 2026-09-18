"""Portable model interpretation keeps factual authority in the shared product."""

import pytest

from baseball_rag.question_interpretation import interpretation_request, run_question_input


def test_an_injected_model_can_request_grounded_research_without_writing_the_answer():
    calls = []

    def interpret(question, previous):
        calls.append((question, previous))
        return {
            "kind": "research",
            "request": {"topic": "definition", "statistic": "OPS", "count": 1},
        }

    result = run_question_input(question="Help me understand OPS", interpret=interpret)
    assert len(calls) == 1
    assert result["kind"] == "answer"
    assert result["facts"][0]["source_ids"] == ["definition-OPS"]
    assert "OPS" in result["facts"][0]["text"]
    assert (
        result["sources"][0]["url"]
        == "https://www.mlb.com/glossary/standard-stats/on-base-plus-slugging"
    )
    assert result["sources"][0]["provider"] == "mlb_glossary"


@pytest.mark.parametrize(
    "proposal",
    [
        {
            "kind": "research",
            "request": {"topic": "definition", "statistic": "OPS", "answer": "fake"},
        },
        {"kind": "answer", "text": "invented facts", "sources": ["https://example.com"]},
        {"kind": "research", "request": {"topic": "pregame", "team": "Unknown", "count": 5}},
    ],
)
def test_model_cannot_invent_facts_sources_or_unsupported_capabilities(proposal):
    result = run_question_input(
        question="Tell me something interesting about baseball", interpret=lambda *_: proposal
    )
    assert result["kind"] == "rejected"
    assert "invented facts" not in str(result)


def test_plain_historical_query_remains_available_without_a_model():
    result = run_question_input(question="how many home runs did Aaron Judge hit in 2023")
    assert result["kind"] == "rows"
    assert result["rows"][0]["batting.HR"] == 37


def test_model_prompt_is_portable_and_contains_research_capabilities():
    request = interpretation_request("five details about the Braves game", None)
    assert set(request) == {"messages", "response_format"}
    schema = request["response_format"]["json_schema"]
    assert any(branch["properties"]["kind"] == {"const": "research"} for branch in schema["oneOf"])


def test_same_local_http_route_accepts_injected_interpretation_without_hosting_code():
    from fastapi.testclient import TestClient

    from baseball_rag.public_app import create_app
    from baseball_rag.question_interpretation import QuestionBindings

    app = create_app(
        public=False,
        question_bindings=QuestionBindings(
            interpret=lambda *_: {
                "kind": "research",
                "request": {"topic": "definition", "statistic": "OPS", "count": 1},
            }
        ),
    )
    client = TestClient(app)
    response = client.post("/api/query-runs", json={"question": "Explain OPS for a new fan"})
    assert response.status_code == 200
    assert response.json()["kind"] == "answer"
    assert client.get("/api/capabilities").json()["assistant"]["enabled"] is True


@pytest.mark.parametrize(
    "question",
    [
        "Give me five Braves talking points for September 23, 2026 "
        "including starting pitchers and injuries",
        "Give me five facts about the Braves and Yankees next games",
        "Give me 12 facts about the Braves game",
        "Give me three interesting details about the Braves game",
        "Give me one interesting fact about the Braves game",
        "Give me five facts about tonight's Braves game",
    ],
)
def test_model_cannot_silently_replace_explicit_constraints_with_a_generic_brief(question):
    from baseball_rag.assistant import ResearchSources

    def must_not_fetch(*_):
        raise AssertionError("Unsupported research must not execute source tools")

    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "pregame", "team": "ATL", "count": 5},
        },
        research_sources=ResearchSources(must_not_fetch, must_not_fetch),
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize(
    "question",
    [
        "Explain WHIP and compare it with ERA",
        "What does batting average mean?",
        "Give me five facts about the Braves and Yankees next games",
        "What was Aaron Judge's OPS?",
    ],
)
def test_definition_plan_cannot_replace_a_different_statistic_or_topic(question):
    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "definition", "statistic": "OPS", "count": 1},
        },
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize(
    "question,team",
    [
        ("Give me five facts about Atlanta's next game", "NYA"),
        ("Give me five facts about Boston and Toronto next games", "ATL"),
        ("Give me five facts about ATL's next game", "NYA"),
        ("Give me five facts about New York's next game", "NYA"),
        ("Give me five facts about the next game", "ATL"),
    ],
)
def test_research_plan_preserves_explicit_city_or_team_id(question, team):
    from baseball_rag.assistant import ResearchSources

    def must_not_fetch(*_):
        raise AssertionError("A mismatched team must not reach source tools")

    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "pregame", "team": team, "count": 5},
        },
        research_sources=ResearchSources(must_not_fetch, must_not_fetch),
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize(
    "question,topic",
    [
        ("Give me five facts about the next Braves game", "team_history"),
        ("Give me five facts from Braves team history", "pregame"),
        ("Tell me five Braves facts from the last decade", "team_history"),
        ("Give me five Braves facts from the past three seasons", "team_history"),
        ("Explain OPS for a new fan", "team_history"),
    ],
)
def test_research_plan_cannot_drop_explicit_topic_or_relative_period(question, topic):
    from baseball_rag.assistant import ResearchSources

    def must_not_fetch(*_):
        raise AssertionError("A mismatched topic must not reach source tools")

    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": topic, "team": "ATL", "count": 5},
        },
        research_sources=ResearchSources(must_not_fetch, must_not_fetch),
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize("team", ["Braves", "Atlanta", "ATL", "New York Yankees"])
def test_polite_request_preserves_unambiguous_team_history(team):
    identity = "NYA" if team == "New York Yankees" else "ATL"
    result = run_question_input(
        question=f"May I have one interesting fact about {team} history?",
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "team_history", "team": identity, "count": 1},
        },
    )
    assert result["kind"] == "answer"
    assert result["context"]["team"] == identity
    assert result["facts"][0]["query_run"]["verification"]["status"] == "verified"


def test_may_as_a_requested_month_still_refuses_date_specific_research():
    result = run_question_input(
        question="Give me one fact about the Braves game in May",
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "pregame", "team": "ATL", "count": 1},
        },
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize(
    "question,statistic",
    [
        ("Explain walks plus hits per inning pitched", "WHIP"),
        ("What is on-base plus slugging?", "OPS"),
        ("What does batting average mean?", "AVG"),
    ],
)
def test_explicit_full_statistic_name_keeps_its_primary_definition(question, statistic):
    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "definition", "statistic": statistic, "count": 1},
        },
    )
    assert result["kind"] == "answer"
    assert result["title"] == statistic
    assert result["sources"][0]["provider"] == "mlb_glossary"
