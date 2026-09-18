"""Conversation and compound requests retain verified evidence at the public seam."""

from datetime import UTC, datetime

import pytest

from baseball_rag.assistant import ResearchSources, compose_answers, research_answer
from baseball_rag.public_results import run_public_query_input
from baseball_rag.question_interpretation import run_question_input


def comparison():
    return {
        "source": "Batting",
        "grain": "player-season",
        "selections": ["player.name", "season", "batting.OPS"],
        "predicate": {
            "kind": "all",
            "predicates": [
                {
                    "kind": "compare",
                    "value": "player.name",
                    "operator": "one_of",
                    "literal": ["Aaron Judge", "Shohei Ohtani"],
                },
                {"kind": "compare", "value": "season", "operator": "equals", "literal": 2023},
            ],
        },
    }


def test_comparison_and_explanation_share_verified_results_and_sources():
    answer = run_question_input(
        question="Compare Aaron Judge and Shohei Ohtani OPS in 2023 and explain the difference.",
        interpret=lambda *_: {
            "kind": "plan",
            "steps": [
                {"kind": "recipe", "recipe": comparison()},
                {
                    "kind": "research",
                    "request": {"topic": "definition", "statistic": "OPS", "count": 1},
                },
            ],
            "unsupported_conditions": [],
        },
    )
    assert answer["kind"] == "answer"
    query_facts = [fact for fact in answer["facts"] if "query_run" in fact]
    assert query_facts and query_facts[0]["query_run"]["verification"]["status"] == "verified"
    rows = query_facts[0]["query_run"]["rows"]
    assert {row["player.name"] for row in rows} == {"Aaron Judge", "Shohei Ohtani"}
    assert all(row["season"] == 2023 for row in rows)
    assert any(source["provider"] == "mlb_glossary" for source in answer["sources"])
    assert all(
        set(fact["source_ids"]) <= {s["id"] for s in answer["sources"]} for fact in answer["facts"]
    )
    assert answer["recipe"]["grain"] == "player-season"


def test_compound_request_cannot_hide_an_unavailable_part():
    answer = run_question_input(
        question="Compare Aaron Judge and Shohei Ohtani OPS in 2023 and include their injuries.",
        interpret=lambda *_: {
            "kind": "plan",
            "steps": [{"kind": "recipe", "recipe": comparison()}],
            "unsupported_conditions": ["injuries"],
        },
    )
    assert answer["kind"] == "rejected"
    assert not answer.get("facts") and not answer.get("rows")


def test_research_followup_uses_references_and_refetches_source_records():
    calls = []

    def meeting(team, opponent):
        calls.append((team, opponent))
        return [
            {
                "year": 2021,
                "winner_id": "ATL",
                "loser_id": "HOU",
                "winner_wins": 4,
                "loser_wins": 2,
                "source": {
                    "id": "ws2021",
                    "title": "2021 World Series",
                    "url": "https://www.retrosheet.org/boxesetc/2021/YPS_2021.htm",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "record": {
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
                },
            }
        ]

    seen = []

    def interpret(question, previous):
        seen.append(previous)
        return {
            "kind": "research",
            "request": {
                "topic": "series_meeting",
                "team": "ATL",
                "opponent": "HOU",
                "season": 2021,
                "count": 1,
            },
        }

    context = {"version": 1, "topic": "pregame", "team": "ATL", "opponent": "HOU", "season": 2021}
    answer = run_question_input(
        question="Tell me more about that World Series meeting.",
        previous_context=context,
        interpret=interpret,
        research_sources=ResearchSources(lambda _: None, meeting),
    )
    assert answer["kind"] == "answer" and calls == [("ATL", "HOU")]
    assert seen[0]["previous_context"] == context
    assert answer["facts"][0]["source_ids"] == ["ws2021"]


def test_browser_context_cannot_introduce_factual_prose():
    with pytest.raises(ValueError):
        run_question_input(
            question="Tell me more.",
            previous_context={
                "version": 1,
                "topic": "pregame",
                "team": "ATL",
                "facts": ["Invented"],
            },
            interpret=lambda *_: pytest.fail("Unvalidated context reached the model"),
        )


@pytest.mark.parametrize("date,away,home", [("20221026", "ATL", "HOU"), ("20211026", "BOS", "NYA")])
def test_series_details_cannot_include_games_from_a_different_season_or_matchup(date, away, home):
    def meeting(*_):
        return [
            {
                "year": 2021,
                "winner_id": "ATL",
                "loser_id": "HOU",
                "winner_wins": 4,
                "loser_wins": 2,
                "source": {
                    "id": "ws2021",
                    "title": "2021 World Series",
                    "url": "https://www.retrosheet.org/boxesetc/2021/YPS_2021.htm",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "record": {
                        "year": 2021,
                        "round": "World Series",
                        "games": [
                            [date, "0", away, home, 6, 2],
                            ["20211027", "0", "ATL", "HOU", 2, 7],
                            ["20211029", "0", "HOU", "ATL", 0, 2],
                            ["20211030", "0", "HOU", "ATL", 2, 3],
                            ["20211031", "0", "HOU", "ATL", 9, 5],
                            ["20211102", "0", "ATL", "HOU", 7, 0],
                        ],
                    },
                },
            }
        ]

    answer = research_answer(
        {"topic": "series_meeting", "team": "ATL", "opponent": "HOU", "season": 2021, "count": 2},
        sources=ResearchSources(lambda _: None, meeting),
    )
    assert answer["kind"] == "unavailable"
    assert not answer.get("facts")


@pytest.mark.parametrize("failure", ["changed_result", "last_page_only"])
def test_comparison_requires_complete_rows_matching_query_evidence(failure):
    recipe = comparison()
    if failure == "last_page_only":
        recipe["output"] = {"kind": "interactive_page", "size": 25, "offset": 1}
    run = run_public_query_input(recipe=recipe)
    assert run["verification"]["status"] == "verified"
    if failure == "changed_result":
        run["rows"][0]["batting.OPS"] = 99.0
    answer = compose_answers([run])
    assert answer["kind"] == "unavailable"
    assert not answer.get("facts")


def test_composition_preserves_unambiguous_definition_context():
    definition = research_answer({"topic": "definition", "statistic": "OPS", "count": 1})
    answer = compose_answers([run_public_query_input(recipe=comparison()), definition])
    assert answer["context"] == {"version": 1, "topic": "definition", "statistic": "OPS"}


@pytest.mark.parametrize("failure", ["empty", "too_many_parts", "missing_source", "failed_part"])
def test_composition_refuses_incomplete_or_unbounded_requests(failure):
    answer = research_answer({"topic": "definition", "statistic": "OPS", "count": 1})
    parts = [answer]
    if failure == "empty":
        parts = []
    elif failure == "too_many_parts":
        parts = [answer] * 4
    elif failure == "missing_source":
        answer["sources"] = []
    else:
        parts.append({"kind": "unavailable", "reason": "Source unavailable"})
    result = compose_answers(parts)
    assert result["kind"] != "answer"
    assert not result.get("facts")


def test_series_summary_must_match_the_retained_game_scores():
    def meeting(*_):
        return [
            {
                "year": 2021,
                "winner_id": "ATL",
                "loser_id": "HOU",
                "winner_wins": 4,
                "loser_wins": 2,
                "source": {
                    "id": "ws2021",
                    "title": "2021 World Series",
                    "url": "https://www.retrosheet.org/boxesetc/2021/YPS_2021.htm",
                    "observed_at": datetime.now(UTC).isoformat(),
                    "record": {
                        "year": 2021,
                        "round": "World Series",
                        "games": [["20211026", 0, "ATL", "HOU", 6, 2]],
                    },
                },
            }
        ]

    answer = research_answer(
        {"topic": "series_meeting", "team": "ATL", "opponent": "HOU", "season": 2021, "count": 1},
        sources=ResearchSources(lambda _: None, meeting),
    )
    assert answer["kind"] == "unavailable"
    assert not answer.get("facts")


def test_two_distinct_comparisons_do_not_choose_an_arbitrary_followup_recipe():
    home_runs = {**comparison(), "selections": ["player.name", "season", "batting.HR"]}
    answer = compose_answers(
        [
            run_public_query_input(recipe=comparison()),
            run_public_query_input(recipe=home_runs),
        ]
    )
    assert answer["kind"] == "answer"
    assert "recipe" not in answer


def test_baseball_innings_are_not_subtracted_as_decimal_numbers():
    run = run_public_query_input(
        recipe={
            "source": "Pitching",
            "grain": "player-season",
            "selections": ["player.name", "season", "pitching.IP"],
            "predicate": {
                "kind": "all",
                "predicates": [
                    {
                        "kind": "compare",
                        "value": "player.name",
                        "operator": "one_of",
                        "literal": ["Greg Maddux", "Tom Glavine"],
                    },
                    {"kind": "compare", "value": "season", "operator": "equals", "literal": 1994},
                ],
            },
        }
    )
    answer = compose_answers([run])
    assert answer["kind"] == "answer"
    # Baseball .1/.2 denote outs, not tenths. Preserve the verified innings records
    # without manufacturing an ordinary decimal difference between them.
    assert len(answer["facts"]) == 1
    assert answer["facts"][0]["query_run"]["rows"] == run["rows"]
