"""Typed statistics preserve meaning through the existing verified query path."""

from dataclasses import replace

import pytest

from baseball_rag import query_intent
from baseball_rag.query.adapters import (
    recipe_from_dict,
    recipe_to_dict,
    resolve_natural_recipe,
    run_query_input,
)
from baseball_rag.query.contracts import QueryRecipe
from baseball_rag.query_intent import StatsIntentClarificationError, translate_stats_intent


def intent(**changes):
    return {
        "source": "Batting",
        "subject": "players",
        "players": ["Mike Trout"],
        "exclude_players": [],
        "teams": [],
        "exclude_teams": [],
        "period": {"kind": "seasons", "years": [2021, 2023]},
        "statistics": ["batting.HR"],
        "ranking": None,
        "unsupported_conditions": [],
        **changes,
    }


def execute(request):
    recipe = resolve_natural_recipe(recipe_from_dict(translate_stats_intent(request)))
    assert isinstance(recipe, QueryRecipe)
    result = run_query_input(recipe=recipe_to_dict(recipe))
    assert result["kind"] == "rows", result
    assert result["verification"]["status"] == "verified"
    return result["rows"]


def test_discrete_seasons_do_not_include_intervening_years():
    rows = execute(intent())
    assert {(row["season"], row["batting.HR"]) for row in rows} == {(2021, 8), (2023, 18)}


def test_range_ranking_and_exclusion_keep_every_requested_condition():
    rows = execute(
        intent(
            players=["Aaron Judge", "Matt Olson"],
            exclude_players=["Matt Olson"],
            period={"kind": "range", "start": 2021, "end": 2023},
            ranking={"value": "batting.HR", "direction": "highest", "count": 1},
        )
    )
    assert [(row["player.name"], row["season"], row["batting.HR"]) for row in rows] == [
        ("Aaron Judge", 2022, 62)
    ]


def test_team_totals_and_player_totals_on_a_team_use_different_grains():
    request = intent(players=[], teams=["ATL"], period={"kind": "seasons", "years": [2023]})
    teams = execute({**request, "subject": "teams"})
    assert [(row["team.id"], row["batting.HR"]) for row in teams] == [("ATL", 307)]
    players = execute(
        {
            **request,
            "ranking": {
                "value": "batting.HR",
                "direction": "highest",
                "count": 1,
            },
        }
    )
    assert [(row["player.name"], row["batting.HR"]) for row in players] == [("Matt Olson", 54)]


@pytest.mark.parametrize(
    "changes",
    [
        {"unsupported_conditions": ["home games only"]},
        {"period": {"kind": "range", "start": 2023, "end": 2021}},
        {"period": {"kind": "seasons", "years": [True]}},
        {"period": {"kind": "seasons", "years": [2023], "postseason": True}},
        {"subject": "teams", "players": ["Aaron Judge"]},
        {"statistics": ["player.birth_year"]},
        {
            "statistics": ["batting.HR"],
            "ranking": {
                "value": "batting.RBI",
                "direction": "highest",
                "count": 1,
            },
        },
        {"condition": "at home"},
    ],
)
def test_invalid_or_unrepresented_conditions_cannot_silently_change_the_question(changes):
    with pytest.raises(ValueError):
        translate_stats_intent(intent(**changes))


@pytest.mark.parametrize(
    "source,player,statistic,expected",
    [
        ("Batting", "Hank Aaron", "batting.HR", 755),
        ("Pitching", "Cy Young", "pitching.W", 511),
        ("Fielding", "Ozzie Smith", "fielding.A", 8375),
    ],
)
def test_career_totals_preserve_all_three_published_disciplines(
    source, player, statistic, expected
):
    rows = execute(
        intent(source=source, players=[player], statistics=[statistic], period={"kind": "career"})
    )
    assert len(rows) == 1
    assert rows[0][statistic] == expected


def test_missing_season_remains_a_clarification_instead_of_an_all_time_query():
    with pytest.raises(StatsIntentClarificationError) as caught:
        translate_stats_intent(intent(period={"kind": "unspecified"}))
    assert caught.value.code == "missing_season"


def test_catalog_disallows_summing_player_games_into_team_games():
    with pytest.raises(ValueError, match="not published at grain"):
        translate_stats_intent(
            intent(subject="teams", players=[], teams=["ATL"], statistics=["batting.G"])
        )


@pytest.mark.parametrize(
    "period",
    [
        {"kind": "seasons", "years": [2023, 2026]},
        {"kind": "range", "start": 2023, "end": 2026},
    ],
)
def test_uncovered_years_do_not_return_a_verified_partial_answer(period):
    with pytest.raises(ValueError, match="coverage"):
        execute(intent(players=["Aaron Judge"], period=period))


def test_unknown_team_exclusion_cannot_become_a_noop():
    with pytest.raises(ValueError, match="team"):
        execute(
            intent(
                players=[],
                exclude_teams=["BRAVES"],
                period={"kind": "seasons", "years": [2023]},
                ranking={"value": "batting.HR", "direction": "highest", "count": 1},
            )
        )


def test_rate_leader_requires_the_planners_eligibility_clarification():
    with pytest.raises(StatsIntentClarificationError) as caught:
        translate_stats_intent(
            intent(
                players=[],
                statistics=["batting.AVG"],
                ranking={"value": "batting.AVG", "direction": "highest", "count": 1},
            )
        )
    assert caught.value.code == "missing_scope"


def test_innings_keep_the_published_baseball_format():
    rows = execute(
        intent(
            source="Pitching",
            players=["Clayton Kershaw"],
            statistics=["pitching.IP"],
            period={"kind": "seasons", "years": [2014]},
        )
    )
    assert rows[0]["pitching.IP"] == 198.1


def test_prepared_runtime_manifest_preserves_coverage_without_acquisition_metadata(monkeypatch):
    runtime = query_intent.published_data_runtime()
    manifest = {key: runtime.manifest[key] for key in ("dataset", "files")}
    monkeypatch.setattr(
        query_intent, "published_data_runtime", lambda: replace(runtime, manifest=manifest)
    )
    rows = execute(intent())
    assert {(row["season"], row["batting.HR"]) for row in rows} == {(2021, 8), (2023, 18)}
    with pytest.raises(ValueError, match="coverage"):
        execute(intent(period={"kind": "seasons", "years": [2023, 2026]}))
