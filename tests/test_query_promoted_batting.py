"""Promoted batting semantics through the canonical Query Recipe and Query Plan."""

from math import isclose

from baseball_rag.query import (
    All,
    Compare,
    NeedsClarification,
    QueryRecipe,
    RankSpec,
    Ready,
    Rejected,
    Rows,
    SortSpec,
    ValueRef,
    build_named_recipe,
    execute,
    interpret_recipe,
    prepare,
    published_relationships,
    published_values,
)


def test_natural_language_and_structured_1962_rbi_recipes_share_one_plan():
    manual = QueryRecipe(
        source="Batting",
        grain="player-season",
        selections=("player.name", "season", "batting.RBI"),
        predicate=Compare("season", "equals", 1962),
        ranking=RankSpec(
            value="batting.RBI",
            direction="highest",
            count=1,
            tie_policy="include_ties",
        ),
    )
    interpreted = interpret_recipe("who had the most RBIs in 1962")
    assert isinstance(interpreted, QueryRecipe)

    manual_plan = prepare(manual)
    interpreted_plan = prepare(interpreted)

    assert isinstance(manual_plan, Ready)
    assert isinstance(interpreted_plan, Ready)
    assert interpreted_plan.plan == manual_plan.plan
    executed = execute(manual_plan.plan)
    assert isinstance(executed, Rows)
    assert [(row["player.name"], row["batting.RBI"]) for row in executed.rows] == [
        ("Tommy Davis", 153)
    ]


def test_promoted_batting_catalog_publishes_exact_values_and_friendly_relationships():
    values = {value.identity: value for value in published_values()}
    assert {
        "batting.G",
        "batting.AB",
        "batting.R",
        "batting.H",
        "batting.2B",
        "batting.3B",
        "batting.HR",
        "batting.RBI",
        "batting.SB",
        "batting.CS",
        "batting.BB",
        "batting.SO",
        "batting.AVG",
        "batting.OBP",
        "batting.SLG",
        "batting.OPS",
    } <= set(values)
    assert values["batting.G"].allowed_grains == (
        "player-team-season",
        "player-season",
        "player-career",
    )
    assert {
        "batting.HBP",
        "batting.SF",
        "batting.SH",
        "batting.PA",
        "batting.HR.league_max",
        "batting.RBI.league_max",
        "batting.AVG.league_max",
    }.isdisjoint(values)
    relationships = published_relationships()
    assert [(item.identity, item.left_source, item.right_source) for item in relationships] == [
        ("people-to-batting", "People", "Batting"),
        ("team-reference-to-batting", "TeamReference", "Batting"),
    ]
    assert all(not hasattr(item, "keys") for item in relationships)


def test_editable_40_40_recipe_is_catalog_owned_and_exact():
    recipe = build_named_recipe("batting.40-40")
    assert isinstance(recipe, QueryRecipe)
    planned = prepare(recipe)
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert [
        (row["player.name"], row["season"], row["batting.HR"], row["batting.SB"])
        for row in executed.rows
    ] == [
        ("Jose Canseco", 1988, 42, 40),
        ("Barry Bonds", 1996, 42, 40),
        ("Alex Rodriguez", 1998, 42, 46),
        ("Alfonso Soriano", 2006, 46, 41),
        ("Ronald Acuña", 2023, 41, 73),
        ("Shohei Ohtani", 2024, 54, 59),
    ]


def test_judge_2022_rates_recompute_from_summed_components():
    manual = QueryRecipe(
        source="Batting",
        grain="player-season",
        selections=(
            "player.name",
            "season",
            "batting.AB",
            "batting.H",
            "batting.2B",
            "batting.3B",
            "batting.HR",
            "batting.BB",
            "batting.HBP",
            "batting.SF",
            "batting.AVG",
            "batting.OBP",
            "batting.SLG",
            "batting.OPS",
        ),
        predicate=All(
            (
                Compare("player.name", "equals", "Aaron Judge"),
                Compare("season", "equals", 2022),
            )
        ),
    )
    interpreted = interpret_recipe("Aaron Judge's 2022 OPS")
    assert isinstance(interpreted, QueryRecipe)
    assert interpreted == manual
    planned = prepare(manual)
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    row = executed.rows[0]
    assert tuple(row[key] for key in ("batting.AB", "batting.H", "batting.HR")) == (
        570,
        177,
        62,
    )
    assert isclose(row["batting.AVG"], 177 / 570)
    assert isclose(row["batting.OBP"], (177 + 111 + 6) / (570 + 111 + 6 + 5))
    assert isclose(row["batting.SLG"], 391 / 570)
    assert isclose(row["batting.OPS"], row["batting.OBP"] + row["batting.SLG"])
    calculation = next(
        item for item in executed.evidence.calculations if item.identity == "batting.OPS"
    )
    assert calculation.formula == "OBP + SLG"
    assert calculation.inputs == (
        "Batting.H",
        "Batting.BB",
        "Batting.HBP",
        "Batting.AB",
        "Batting.SF",
        "Batting.2B",
        "Batting.3B",
        "Batting.HR",
    )
    ops = next(value for value in published_values() if value.identity == "batting.OPS")
    assert ops.formula == "OBP + SLG"
    assert ops.rollup == "recompute"


def test_rate_leaderboard_clarifies_without_and_runs_with_explicit_floor():
    bare = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.name", "season", "batting.AVG"),
            predicate=Compare("season", "equals", 1894),
            ranking=RankSpec("batting.AVG", "highest", 1, "include_ties"),
        )
    )
    assert isinstance(bare, NeedsClarification)

    explicit = interpret_recipe("highest batting average in 1894, minimum 400 at-bats")
    assert isinstance(explicit, QueryRecipe)
    planned = prepare(explicit)
    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    assert executed.rows[0]["player.name"] == "Hugh Duffy"
    assert 400 in executed.evidence.bound_values
    assert "400" not in executed.evidence.parameterized_sql


def test_broader_team_grain_recomputes_rates_and_games_do_not_roll_up():
    team_games = prepare(
        QueryRecipe(
            source="Batting",
            grain="team-season",
            selections=("team.name", "season", "batting.G"),
        )
    )
    assert isinstance(team_games, Rejected)

    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="team-season",
            selections=(
                "team.name",
                "season",
                "batting.AB",
                "batting.H",
                "batting.2B",
                "batting.3B",
                "batting.HR",
                "batting.BB",
                "batting.HBP",
                "batting.SF",
                "batting.OBP",
                "batting.SLG",
                "batting.OPS",
            ),
            predicate=All(
                (
                    Compare("team.name", "equals", "New York Yankees"),
                    Compare("season", "equals", 2022),
                )
            ),
        )
    )
    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    row = executed.rows[0]
    obp = (row["batting.H"] + row["batting.BB"] + row["batting.HBP"]) / (
        row["batting.AB"] + row["batting.BB"] + row["batting.HBP"] + row["batting.SF"]
    )
    total_bases = (
        row["batting.H"]
        - row["batting.2B"]
        - row["batting.3B"]
        - row["batting.HR"]
        + 2 * row["batting.2B"]
        + 3 * row["batting.3B"]
        + 4 * row["batting.HR"]
    )
    slg = total_bases / row["batting.AB"]
    assert isclose(row["batting.OBP"], obp)
    assert isclose(row["batting.SLG"], slg)
    assert isclose(row["batting.OPS"], obp + slg)


def test_arbitrary_formula_is_rejected_before_execution():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.name", "formula:batting.HR+batting.SB"),
        )
    )

    assert isinstance(planned, Rejected)
    assert "published" in planned.reason.lower()


def test_named_30_30_and_500_home_run_clubs_use_aggregated_grains():
    thirty = build_named_recipe("batting.30-30")
    five_hundred = build_named_recipe("batting.500-home-runs")
    assert isinstance(thirty, QueryRecipe)
    assert isinstance(five_hundred, QueryRecipe)
    thirty_plan = prepare(thirty)
    five_hundred_plan = prepare(five_hundred)
    assert isinstance(thirty_plan, Ready)
    assert isinstance(five_hundred_plan, Ready)

    thirty_run = execute(thirty_plan.plan)
    five_hundred_run = execute(five_hundred_plan.plan)

    assert isinstance(thirty_run, Rows)
    assert len(thirty_run.rows) == 79
    assert isinstance(five_hundred_run, Rows)
    assert len(five_hundred_run.rows) == 28
    assert five_hundred_run.rows[-1]["player.name"] == "Eddie Murray"
    assert five_hundred_run.rows[-1]["batting.HR"] == 504


def test_ranking_includes_every_tie_at_the_cutoff_by_default():
    recipe = QueryRecipe(
        source="Batting",
        grain="player-season",
        selections=("player.id", "player.name", "season", "batting.HR"),
        predicate=Compare("season", "equals", 2021),
        ranking=RankSpec("batting.HR", "highest", 1, "include_ties"),
    )
    planned = prepare(recipe)
    assert isinstance(planned, Ready)

    tied = execute(planned.plan)
    exact_plan = prepare(
        QueryRecipe(
            source=recipe.source,
            grain=recipe.grain,
            selections=recipe.selections,
            predicate=recipe.predicate,
            ranking=RankSpec("batting.HR", "highest", 1, "exact_count"),
        )
    )
    assert isinstance(exact_plan, Ready)
    exact = execute(exact_plan.plan)

    assert isinstance(tied, Rows)
    assert [(row["player.id"], row["batting.HR"]) for row in tied.rows] == [
        ("guerrvl02", 48),
        ("perezsa02", 48),
    ]
    assert isinstance(exact, Rows)
    assert [(row["player.id"], row["batting.HR"]) for row in exact.rows] == [("guerrvl02", 48)]


def test_season_aware_team_and_people_relationships_are_plan_and_evidence_sources():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-team-season",
            selections=(
                "player.name",
                "season",
                "team.name",
                "batting.HR",
            ),
            predicate=All(
                (
                    Compare("player.name", "equals", "Hank Aaron"),
                    Compare("season", "equals", 1954),
                )
            ),
            ordering=(SortSpec("team.name", "ascending"),),
        )
    )
    assert isinstance(planned, Ready)
    assert planned.plan.relationships == (
        "people-to-batting",
        "team-reference-to-batting",
    )

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert [dict(row) for row in executed.rows] == [
        {
            "player.name": "Hank Aaron",
            "season": 1954,
            "team.name": "Milwaukee Braves",
            "batting.HR": 13,
        }
    ]
    assert {source.identity for source in executed.evidence.sources} == {
        "Batting",
        "People",
        "TeamReference",
    }


def test_triple_crown_requires_an_exact_reviewed_eligibility_record():
    uncovered = build_named_recipe("batting.triple-crown", year=1932, league="AL")
    assert isinstance(uncovered, NeedsClarification)

    recipe = build_named_recipe("batting.triple-crown", year=2012, league="AL")
    assert isinstance(recipe, QueryRecipe)
    planned = prepare(recipe)
    assert isinstance(planned, Ready)
    assert type(planned.plan).from_json(planned.plan.to_json()) == planned.plan

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert [
        (row["player.name"], row["season"], row["league"], row["batting.HR"], row["batting.RBI"])
        for row in executed.rows
    ] == [("Miguel Cabrera", 2012, "AL", 44, 139)]
    assert executed.evidence.bound_values.count(502) == 2
    assert "MAX(CASE WHEN" in executed.evidence.parameterized_sql


def test_window_comparison_without_required_eligibility_clarifies_while_planning():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season-league",
            selections=("player.name", "season", "league", "batting.AVG"),
            predicate=All(
                (
                    Compare("season", "equals", 2012),
                    Compare("league", "equals", "AL"),
                    Compare(
                        "batting.AVG",
                        "equals",
                        ValueRef("batting.AVG.league_max"),
                    ),
                )
            ),
        )
    )

    assert isinstance(planned, NeedsClarification)
    assert "eligibility" in planned.question.lower()


def test_grain_relationships_are_inferred_without_explicit_player_selection():
    season = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("season", "batting.RBI"),
            predicate=Compare("season", "equals", 1962),
            ranking=RankSpec("batting.RBI", "highest", 1, "exact_count"),
        )
    )
    career = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("batting.HR",),
            ranking=RankSpec("batting.HR", "highest", 1, "exact_count"),
        )
    )

    assert isinstance(season, Ready)
    assert season.plan.relationships == ("people-to-batting",)
    season_rows = execute(season.plan)
    assert isinstance(season_rows, Rows)
    assert season_rows.rows[0]["batting.RBI"] == 153
    assert isinstance(career, Ready)
    assert career.plan.relationships == ("people-to-batting",)
    career_rows = execute(career.plan)
    assert isinstance(career_rows, Rows)
    assert career_rows.rows[0]["batting.HR"] == 762


def test_ranking_within_accepts_dimensions_only():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("season", "batting.HR"),
            ranking=RankSpec(
                "batting.HR",
                "highest",
                1,
                "include_ties",
                within=("batting.AVG",),
            ),
        )
    )

    assert isinstance(planned, Rejected)
    assert "dimension" in planned.reason.lower()

    valid = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("season", "batting.HR"),
            ranking=RankSpec(
                "batting.HR",
                "highest",
                1,
                "include_ties",
                within=("season",),
            ),
        )
    )
    assert isinstance(valid, Ready)
    assert valid.plan.ranking is not None
    assert valid.plan.ranking.value == "batting.HR"
    assert valid.plan.ranking.within == ("season",)
