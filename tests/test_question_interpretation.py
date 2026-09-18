"""Portable model interpretation keeps factual authority in the shared product."""

import pytest

from baseball_rag.question_interpretation import interpretation_request, run_question_input


@pytest.mark.parametrize(
    "names,expected",
    [
        (["Aaron Judge", "Ronald Acuna Jr."], {"Aaron Judge": 37, "Ronald Acuña": 41}),
        (["Aaron Judge", "Zephyrus Moonbat"], None),
        (["Aaron Judge", "Smith"], None),
    ],
)
@pytest.mark.parametrize("form", ["one_of", "any"])
def test_multi_player_comparison_resolves_each_name_before_returning_verified_totals(
    names, expected, form
):
    names_predicate = (
        {
            "kind": "compare",
            "value": "player.name",
            "operator": "one_of",
            "literal": names,
        }
        if form == "one_of"
        else {
            "kind": "any",
            "predicates": [
                {"kind": "compare", "value": "player.name", "operator": "equals", "literal": name}
                for name in names
            ],
        }
    )
    result = run_question_input(
        question=f"Who hit more homers in 2023, {' or '.join(names)}?",
        interpret=lambda *_: {
            "kind": "recipe",
            "recipe": {
                "source": "Batting",
                "grain": "player-season",
                "selections": ["player.name", "season", "batting.HR"],
                "predicate": {
                    "kind": "all",
                    "predicates": [
                        {
                            "kind": "compare",
                            "value": "season",
                            "operator": "equals",
                            "literal": 2023,
                        },
                        names_predicate,
                    ],
                },
            },
        },
    )
    if expected is None:
        assert result["kind"] == "needs_clarification"
        assert not result.get("rows")
        return
    assert result["kind"] == "rows"
    assert {row["player.name"]: row["batting.HR"] for row in result["rows"]} == expected
    assert result["verification"]["status"] == "verified"


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


@pytest.mark.parametrize("suffix,total", [("Jr.", 22), ("Sr.", 4)])
def test_suffix_disambiguation_keeps_the_selected_player_identity(suffix, total):
    result = run_question_input(question=f"how many home runs did Ken Griffey {suffix} hit in 1990")
    assert result["kind"] == "rows"
    assert len(result["rows"]) == 1
    assert result["rows"][0]["batting.HR"] == total


def test_model_season_list_and_name_exclusion_keep_all_requested_conditions():
    result = run_question_input(
        question="Show Aaron Judge and Matt Olson homers for 2022 and 2023, excluding Matt Olson",
        interpret=lambda *_: {
            "kind": "recipe",
            "recipe": {
                "source": "Batting",
                "grain": "player-season",
                "selections": ["player.name", "season", "batting.HR"],
                "predicate": {
                    "kind": "all",
                    "predicates": [
                        {
                            "kind": "any",
                            "predicates": [
                                {
                                    "kind": "compare",
                                    "value": "season",
                                    "operator": "equals",
                                    "literal": year,
                                }
                                for year in [2022, 2023]
                            ],
                        },
                        {
                            "kind": "compare",
                            "value": "player.name",
                            "operator": "one_of",
                            "literal": ["Aaron Judge", "Matt Olson"],
                        },
                        {
                            "kind": "not",
                            "predicate": {
                                "kind": "compare",
                                "value": "player.name",
                                "operator": "equals",
                                "literal": "Matt Olson",
                            },
                        },
                    ],
                },
            },
        },
    )
    assert result["kind"] == "rows"
    assert {(row["player.name"], row["season"]): row["batting.HR"] for row in result["rows"]} == {
        ("Aaron Judge", 2022): 62,
        ("Aaron Judge", 2023): 37,
    }


def test_excluded_name_alias_is_resolved_inside_negation():
    result = run_question_input(
        question="Compare Aaron Judge and Ronald Acuna Jr. homers in 2023, excluding Acuna",
        interpret=lambda *_: {
            "kind": "recipe",
            "recipe": {
                "source": "Batting",
                "grain": "player-season",
                "selections": ["player.name", "season", "batting.HR"],
                "predicate": {
                    "kind": "all",
                    "predicates": [
                        {
                            "kind": "compare",
                            "value": "season",
                            "operator": "equals",
                            "literal": 2023,
                        },
                        {
                            "kind": "compare",
                            "value": "player.name",
                            "operator": "one_of",
                            "literal": ["Aaron Judge", "Ronald Acuna Jr."],
                        },
                        {
                            "kind": "not",
                            "predicate": {
                                "kind": "compare",
                                "value": "player.name",
                                "operator": "equals",
                                "literal": "Ronald Acuna Jr.",
                            },
                        },
                    ],
                },
            },
        },
    )
    assert result["kind"] == "rows"
    assert result["rows"] == [{"player.name": "Aaron Judge", "season": 2023, "batting.HR": 37}]


@pytest.mark.parametrize("count", ["a dozen", "2 really interesting"])
def test_research_must_preserve_counts_with_common_modifiers(count):
    result = run_question_input(
        question=f"Give me {count} facts about Braves history",
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "team_history", "team": "ATL", "count": 5},
        },
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize(
    "question",
    [
        "Who hit more homers in 2023, Aaron Judge or Ronald Acuna Jr.?",
        "Who led MLB in home runs in 2023, excluding Aaron Judge?",
        "Show Aaron Judge home-run totals for both 2022 and 2023",
    ],
)
def test_model_cannot_return_verified_numbers_after_dropping_a_person_exclusion_or_year(question):
    from baseball_rag.query.adapters import adapt_natural_query, recipe_to_dict

    proposal = recipe_to_dict(adapt_natural_query("how many home runs did Aaron Judge hit in 2023"))
    result = run_question_input(
        question=question, interpret=lambda *_: {"kind": "recipe", "recipe": proposal}
    )
    assert result["kind"] == "rejected"
    assert not result.get("rows")


@pytest.mark.parametrize("period", ["this year", "the current season"])
def test_current_period_cannot_be_replaced_with_a_historical_season(period):
    result = run_question_input(
        question=f"Who has the most homers {period}?",
        interpret=lambda *_: {
            "kind": "recipe",
            "recipe": {
                "source": "Batting",
                "grain": "player-season",
                "selections": ["player.name", "season", "batting.HR"],
                "predicate": {
                    "kind": "compare",
                    "value": "season",
                    "operator": "equals",
                    "literal": 2023,
                },
                "ranking": {
                    "value": "batting.HR",
                    "direction": "highest",
                    "count": 1,
                    "tie_policy": "include_ties",
                    "within": [],
                },
            },
        },
    )
    assert result["kind"] == "rejected"
    assert not result.get("rows")


@pytest.mark.parametrize(
    "value,literals,question",
    [
        (
            "player.name",
            ["Aaron Judge", "Ronald Acuna Jr."],
            "Compare Aaron Judge and Ronald Acuna Jr. homers in 2023",
        ),
        ("season", [2022, 2023], "Compare Aaron Judge homers in 2022 and 2023"),
    ],
)
def test_comparison_cannot_become_an_impossible_conjunction(value, literals, question):
    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "recipe",
            "recipe": {
                "source": "Batting",
                "grain": "player-season",
                "selections": ["player.name", "season", "batting.HR"],
                "predicate": {
                    "kind": "all",
                    "predicates": [
                        {
                            "kind": "compare",
                            "value": "season",
                            "operator": "equals",
                            "literal": 2023,
                        },
                        {
                            "kind": "compare",
                            "value": "player.name",
                            "operator": "equals",
                            "literal": "Aaron Judge",
                        },
                        *[
                            {
                                "kind": "compare",
                                "value": value,
                                "operator": "equals",
                                "literal": literal,
                            }
                            for literal in literals
                        ],
                    ],
                },
            },
        },
    )
    assert result["kind"] == "rejected"
    assert not result.get("rows")


def test_exclusion_must_apply_to_every_branch_of_the_proposed_query():
    result = run_question_input(
        question="Compare Aaron Judge and Matt Olson homers in 2023, excluding Matt Olson",
        interpret=lambda *_: {
            "kind": "recipe",
            "recipe": {
                "source": "Batting",
                "grain": "player-season",
                "selections": ["player.name", "season", "batting.HR"],
                "predicate": {
                    "kind": "all",
                    "predicates": [
                        {
                            "kind": "compare",
                            "value": "season",
                            "operator": "equals",
                            "literal": 2023,
                        },
                        {
                            "kind": "any",
                            "predicates": [
                                {
                                    "kind": "compare",
                                    "value": "player.name",
                                    "operator": "one_of",
                                    "literal": ["Aaron Judge", "Matt Olson"],
                                },
                                {
                                    "kind": "not",
                                    "predicate": {
                                        "kind": "compare",
                                        "value": "player.name",
                                        "operator": "equals",
                                        "literal": "Matt Olson",
                                    },
                                },
                            ],
                        },
                    ],
                },
            },
        },
    )
    assert result["kind"] == "rejected"
    assert not result.get("rows")


def test_model_prompt_is_portable_and_contains_research_capabilities():
    request = interpretation_request("five details about the Braves game", None)
    assert set(request) == {"messages", "response_format"}
    schema = request["response_format"]["json_schema"]
    assert any(branch["properties"]["kind"] == {"const": "research"} for branch in schema["oneOf"])


def test_definition_cannot_be_replaced_by_a_statistical_table(monkeypatch):
    from baseball_rag import question_interpretation as core

    monkeypatch.setattr(
        core, "_run_natural_recipe", lambda *_: pytest.fail("Wrong answer type executed")
    )
    result = run_question_input(
        question="Explain OPS for a new fan",
        interpret=lambda *_: {
            "kind": "recipe",
            "recipe": {
                "source": "Batting",
                "grain": "player-season",
                "selections": ["batting.OPS"],
                "predicate": None,
                "ranking": None,
                "ordering": [],
                "groupings": [],
                "output": {"kind": "interactive_page", "offset": 0, "size": 25},
            },
        },
    )
    assert result["kind"] == "rejected"


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


@pytest.mark.parametrize(
    "question,statistic,count",
    [
        ("Who leads MLB in stolen bases this year?", "HR", 1),
        ("Who are the top five home run leaders this season?", "HR", 1),
        ("Who leads MLB in home runs and RBI this year?", "HR", 1),
        ("Who had the most home runs last season?", "HR", 1),
    ],
)
def test_current_leader_plan_cannot_change_statistic_count_or_period(question, statistic, count):
    from datetime import UTC, datetime

    from baseball_rag.assistant import ResearchSources

    def must_not_fetch(*_):
        pytest.fail("Mismatched current research reached external source")

    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "research",
            "request": {
                "topic": "current_leaders",
                "team": None,
                "statistic": statistic,
                "season": datetime.now(UTC).year,
                "count": count,
            },
        },
        research_sources=ResearchSources(must_not_fetch, must_not_fetch, must_not_fetch),
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize(
    "question",
    [
        "Who has more homers this year, Aaron Judge or Shohei Ohtani?",
        "Who leads the National League in home runs this year?",
    ],
)
def test_current_leaders_cannot_drop_player_or_league_scope(question):
    from baseball_rag.assistant import ResearchSources

    def must_not_fetch(*_):
        pytest.fail("Narrow request became a league-wide leaderboard")

    result = run_question_input(
        question=question,
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "current_leaders", "team": None, "statistic": "HR", "count": 1},
        },
        research_sources=ResearchSources(must_not_fetch, must_not_fetch, must_not_fetch),
    )
    assert result["kind"] == "rejected"


def test_comparison_recipe_cannot_drop_requested_explanation():
    from baseball_rag.query_intent import translate_stats_intent

    recipe = translate_stats_intent(
        {
            "source": "Batting",
            "subject": "players",
            "players": ["Aaron Judge", "Shohei Ohtani"],
            "exclude_players": [],
            "teams": [],
            "exclude_teams": [],
            "period": {"kind": "seasons", "years": [2023]},
            "statistics": ["batting.OPS"],
            "ranking": None,
            "unsupported_conditions": [],
        }
    )
    result = run_question_input(
        question="Compare Aaron Judge and Shohei Ohtani OPS in 2023 and explain the difference.",
        interpret=lambda *_: {"kind": "recipe", "recipe": recipe},
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize("statistic", ["OPS", "WHIP"])
def test_definition_followup_uses_matching_reference_context(statistic):
    result = run_question_input(
        question="Explain that statistic again.",
        previous_context={"version": 1, "topic": "definition", "statistic": statistic},
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "definition", "statistic": statistic, "count": 1},
        },
    )
    assert result["kind"] == "answer"
    assert result["context"]["statistic"] == statistic


@pytest.mark.parametrize(
    "context", [None, {"version": 1, "topic": "definition", "statistic": "WHIP"}]
)
def test_definition_followup_rejects_missing_or_conflicting_reference(context):
    result = run_question_input(
        question="Explain that statistic again.",
        previous_context=context,
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "definition", "statistic": "OPS", "count": 1},
        },
    )
    assert result["kind"] == "rejected"


@pytest.mark.parametrize("scope", ["World Series", "postseason", "playoff"])
def test_series_scope_cannot_be_replaced_by_general_team_history(scope):
    result = run_question_input(
        question=f"Give me three interesting details about Braves {scope} history.",
        interpret=lambda *_: {
            "kind": "research",
            "request": {"topic": "team_history", "team": "ATL", "count": 3},
        },
    )
    assert result["kind"] == "rejected"
