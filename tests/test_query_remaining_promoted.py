"""People, pitching, and fielding promoted semantics through public query interfaces."""

from math import isclose

from baseball_rag.query import (
    All,
    Any,
    Compare,
    NeedsClarification,
    QueryRecipe,
    RankSpec,
    Ready,
    Rejected,
    Rows,
    SortSpec,
    ValueRef,
    execute,
    interpret_recipe,
    prepare,
    published_values,
)


def test_remaining_promoted_catalog_declares_complete_rollup_matrix():
    values = {value.identity: value for value in published_values()}
    people_facts = {
        "player.birth_year",
        "player.birth_month",
        "player.birth_day",
        "player.birth_city",
        "player.birth_state",
        "player.birth_country",
        "player.death_year",
        "player.death_month",
        "player.death_day",
        "player.death_city",
        "player.death_state",
        "player.death_country",
        "player.bats",
        "player.throws",
        "player.height",
        "player.weight",
        "player.debut",
        "player.final_game",
    }
    assert people_facts <= values.keys()
    assert all(values[identity].kind == "fact" for identity in people_facts)
    assert all(values[identity].rollup == "not_aggregatable" for identity in people_facts)
    assert {
        "pitching.W",
        "pitching.L",
        "pitching.G",
        "pitching.GS",
        "pitching.CG",
        "pitching.SHO",
        "pitching.SV",
        "pitching.IP",
        "pitching.H",
        "pitching.ER",
        "pitching.HR",
        "pitching.BB",
        "pitching.SO",
        "pitching.ERA",
        "pitching.WHIP",
    } <= values.keys()
    assert values["pitching.G"].allowed_grains == (
        "player-team-season",
        "player-season",
        "player-career",
    )
    assert values["pitching.ERA"].rollup == "recompute"
    assert values["pitching.ERA"].null_policy == "preserve_unknown"
    assert values["pitching.WHIP"].rollup == "recompute"
    assert {
        "fielding.G",
        "fielding.GS",
        "fielding.innings",
        "fielding.PO",
        "fielding.A",
        "fielding.E",
        "fielding.DP",
        "fielding.FPCT",
    } <= values.keys()
    assert values["fielding.G"].allowed_grains == (
        "player-position-season",
        "player-position-career",
    )
    assert "team-season" not in values["fielding.DP"].allowed_grains
    assert "league-season" not in values["fielding.DP"].allowed_grains
    assert values["fielding.FPCT"].rollup == "recompute"
    assert values["fielding.FPCT"].null_policy == "preserve_unknown"


def test_people_almanac_facts_are_exact_player_record_values_only():
    planned = prepare(
        QueryRecipe(
            source="People",
            grain="player-record",
            selections=(
                "player.id",
                "player.birth_year",
                "player.birth_city",
                "player.bats",
                "player.throws",
                "player.height",
                "player.weight",
                "player.debut",
                "player.debut_year",
                "player.final_game",
            ),
            predicate=Compare("player.id", "equals", "jeterde01"),
        )
    )

    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    assert dict(executed.rows[0]) == {
        "player.id": "jeterde01",
        "player.birth_year": 1974,
        "player.birth_city": "Pequannock",
        "player.bats": "R",
        "player.throws": "R",
        "player.height": 75,
        "player.weight": 195,
        "player.debut": "1995-05-29",
        "player.debut_year": 1995,
        "player.final_game": "2014-09-28",
    }
    aggregated = prepare(
        QueryRecipe(
            source="People",
            grain="player-season",
            selections=("player.birth_year",),
        )
    )
    assert isinstance(aggregated, Rejected)
    temporal = prepare(
        QueryRecipe(
            source="People",
            grain="player-record",
            selections=("player.id", "player.debut"),
            predicate=All(
                (
                    Compare("player.id", "equals", "jeterde01"),
                    Compare("player.debut", "before", "2000-01-01"),
                )
            ),
        )
    )
    assert isinstance(temporal, Ready)
    assert isinstance(execute(temporal.plan), Rows)


def test_given_name_matches_without_changing_display_name():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.name", "batting.HR"),
            predicate=Compare("player.name", "equals", "George Herman Ruth"),
        )
    )

    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    assert [dict(row) for row in executed.rows] == [{"player.name": "Babe Ruth", "batting.HR": 714}]


def test_pitching_rates_recompute_from_outs_and_components():
    planned = prepare(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=(
                "player.id",
                "season",
                "pitching.W",
                "pitching.IP",
                "pitching.H",
                "pitching.ER",
                "pitching.BB",
                "pitching.SO",
                "pitching.ERA",
                "pitching.WHIP",
            ),
            predicate=All(
                (
                    Compare("player.id", "equals", "scherma01"),
                    Compare("season", "equals", 2021),
                )
            ),
        )
    )

    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    row = executed.rows[0]
    assert row["pitching.W"] == 15
    assert row["pitching.SO"] == 236
    assert row["pitching.IP"] == 179.1
    assert isclose(row["pitching.ERA"], 27 * 49 / 538)
    assert isclose(row["pitching.WHIP"], 3 * (36 + 119) / 538)
    forbidden_games = prepare(
        QueryRecipe(
            source="Pitching",
            grain="team-season",
            selections=("season", "team.id", "pitching.G"),
        )
    )
    assert isinstance(forbidden_games, Rejected)


def test_fielding_position_rollups_and_percentage_are_exact():
    planned = prepare(
        QueryRecipe(
            source="Fielding",
            grain="player-position-season",
            selections=(
                "player.id",
                "season",
                "position",
                "fielding.G",
                "fielding.GS",
                "fielding.innings",
                "fielding.PO",
                "fielding.A",
                "fielding.E",
                "fielding.DP",
                "fielding.FPCT",
            ),
            predicate=All(
                (
                    Compare("player.id", "equals", "machama01"),
                    Compare("season", "equals", 2018),
                    Compare("position", "equals", "SS"),
                )
            ),
        )
    )

    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    row = executed.rows[0]
    assert (row["fielding.G"], row["fielding.GS"], row["fielding.DP"]) == (147, 145, 73)
    assert row["fielding.innings"] == 1261.1
    assert isclose(row["fielding.FPCT"], (194 + 357) / (194 + 357 + 12))

    team_games = prepare(
        QueryRecipe(
            source="Fielding",
            grain="team-season",
            selections=("season", "team.id", "fielding.G"),
        )
    )
    league_dp = prepare(
        QueryRecipe(
            source="Fielding",
            grain="league-season",
            selections=("season", "league", "fielding.DP"),
        )
    )
    assert isinstance(team_games, Rejected)
    assert isinstance(league_dp, Rejected)
    across_positions = prepare(
        QueryRecipe(
            source="Fielding",
            grain="player-season",
            selections=("player.id", "season", "fielding.G"),
        )
    )
    assert isinstance(across_positions, Rejected)

    broader = prepare(
        QueryRecipe(
            source="Fielding",
            grain="player-season",
            selections=(
                "player.id",
                "season",
                "fielding.PO",
                "fielding.A",
                "fielding.E",
                "fielding.FPCT",
            ),
            predicate=All(
                (
                    Compare("player.id", "equals", "machama01"),
                    Compare("season", "equals", 2018),
                )
            ),
        )
    )
    assert isinstance(broader, Ready)
    broader_rows = execute(broader.plan)
    assert isinstance(broader_rows, Rows)
    assert isclose(broader_rows.rows[0]["fielding.FPCT"], 604 / 617)


def test_shared_strikeout_abbreviation_clarifies_or_uses_explicit_context():
    ambiguous = interpret_recipe("who had the most strikeouts in 2024")
    assert isinstance(ambiguous, NeedsClarification)
    assert "batting or pitching" in ambiguous.question.lower()

    pitching = interpret_recipe("which pitcher had the most strikeouts in 2024")
    assert isinstance(pitching, QueryRecipe)
    planned = prepare(pitching)
    assert isinstance(planned, Ready)
    assert planned.plan.source == "Pitching"
    assert planned.plan.ranking is not None
    assert planned.plan.ranking.value == "pitching.SO"
    batting = interpret_recipe("which batter had the most strikeouts in 2024")
    assert isinstance(batting, QueryRecipe)
    batting_plan = prepare(batting)
    assert isinstance(batting_plan, Ready)
    assert batting_plan.plan.source == "Batting"
    assert batting_plan.plan.ranking is not None
    assert batting_plan.plan.ranking.value == "batting.SO"
    bare_games = interpret_recipe("who had the most G in 2024")
    assert isinstance(bare_games, NeedsClarification)
    fielding = interpret_recipe("which fielder played the most G in 2024")
    assert isinstance(fielding, NeedsClarification)
    assert "position" in fielding.question.lower()
    shortstop = interpret_recipe("which shortstop played the most G in 2024")
    assert isinstance(shortstop, QueryRecipe)
    shortstop_plan = prepare(shortstop)
    assert isinstance(shortstop_plan, Ready)
    assert shortstop_plan.plan.source == "Fielding"
    assert shortstop_plan.plan.ranking is not None
    assert shortstop_plan.plan.ranking.value == "fielding.G"


def test_bare_pitching_rate_leaderboard_requires_a_sample_floor():
    planned = prepare(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=("player.id", "season", "pitching.ERA"),
            predicate=Compare("season", "equals", 2024),
            ranking=RankSpec("pitching.ERA", "lowest", 1, "include_ties"),
        )
    )

    assert isinstance(planned, NeedsClarification)


def test_exact_filtered_tiny_rates_need_no_sample_floor_and_zero_outs_are_null():
    tiny_pitching = prepare(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=("player.id", "pitching.IP", "pitching.ERA", "pitching.WHIP"),
            predicate=All(
                (
                    Compare("player.id", "equals", "andrecl02"),
                    Compare("season", "equals", 2024),
                )
            ),
        )
    )
    tiny_fielding = prepare(
        QueryRecipe(
            source="Fielding",
            grain="player-position-season",
            selections=("player.id", "position", "fielding.FPCT"),
            predicate=All(
                (
                    Compare("player.id", "equals", "colliis01"),
                    Compare("season", "equals", 2024),
                    Compare("position", "equals", "2B"),
                )
            ),
        )
    )
    zero_outs = prepare(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=("player.id", "pitching.ERA", "pitching.WHIP"),
            predicate=All(
                (
                    Compare("player.id", "equals", "edwarca01"),
                    Compare("season", "equals", 2024),
                )
            ),
        )
    )

    assert isinstance(tiny_pitching, Ready)
    pitching_rows = execute(tiny_pitching.plan)
    assert isinstance(pitching_rows, Rows)
    assert pitching_rows.rows[0]["pitching.IP"] == 0.1
    assert pitching_rows.rows[0]["pitching.ERA"] == 27.0
    assert pitching_rows.rows[0]["pitching.WHIP"] == 3.0
    assert isinstance(tiny_fielding, Ready)
    fielding_rows = execute(tiny_fielding.plan)
    assert isinstance(fielding_rows, Rows)
    assert isclose(fielding_rows.rows[0]["fielding.FPCT"], 2 / 3)
    assert isinstance(zero_outs, Ready)
    zero_rows = execute(zero_outs.plan)
    assert isinstance(zero_rows, Rows)
    assert zero_rows.rows[0]["pitching.ERA"] is None
    assert zero_rows.rows[0]["pitching.WHIP"] is None


def test_unavailable_source_counts_remain_unknown_instead_of_becoming_zero():
    planned = prepare(
        QueryRecipe(
            source="Fielding",
            grain="player-position-season",
            selections=(
                "player.id",
                "season",
                "position",
                "fielding.GS",
                "fielding.innings",
                "fielding.PO",
                "fielding.A",
                "fielding.E",
                "fielding.DP",
                "fielding.FPCT",
            ),
            predicate=All(
                (
                    Compare("player.id", "equals", "abreueu01"),
                    Compare("season", "equals", 1925),
                    Compare("position", "equals", "1B"),
                )
            ),
        )
    )

    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    row = executed.rows[0]
    assert row["fielding.innings"] == 0.0
    assert all(
        row[identity] is None
        for identity in (
            "fielding.GS",
            "fielding.PO",
            "fielding.A",
            "fielding.E",
            "fielding.DP",
            "fielding.FPCT",
        )
    )


def test_baseball_innings_filters_accept_only_exact_thirds_notation():
    invalid = prepare(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=("player.id", "pitching.IP"),
            predicate=Compare("pitching.IP", "greater_or_equal", 10.3),
        )
    )
    valid = prepare(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=("player.id", "pitching.IP"),
            predicate=Compare("pitching.IP", "greater_or_equal", 10.2),
        )
    )

    assert isinstance(invalid, Rejected)
    assert isinstance(valid, Ready)


def test_shared_structured_aliases_resolve_from_source_context():
    pitching = prepare(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=("player.id", "season", "SO"),
        )
    )
    batting = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.id", "season", "SO"),
        )
    )
    fielding = prepare(
        QueryRecipe(
            source="Fielding",
            grain="player-position-season",
            selections=("player.id", "season", "position", "G"),
        )
    )

    assert isinstance(pitching, Ready)
    assert pitching.plan.selections[-1] == "pitching.SO"
    assert isinstance(batting, Ready)
    assert batting.plan.selections[-1] == "batting.SO"
    assert isinstance(fielding, Ready)
    assert fielding.plan.selections[-1] == "fielding.G"


def test_catalog_owned_promoted_grouping_replaces_player_grain_keys():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.bats", "batting.HR"),
            groupings=("player.bats",),
            ordering=(SortSpec("batting.HR", "descending"),),
        )
    )

    assert isinstance(planned, Ready)
    assert planned.plan.groupings == ("player.bats",)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    assert [(row["player.bats"], row["batting.HR"]) for row in executed.rows] == [
        ("R", 197634),
        ("L", 117034),
        ("B", 30061),
        (None, 981),
    ]

    filtered = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.bats", "batting.HR"),
            groupings=("player.bats",),
            predicate=Compare(
                "player.birth_country",
                "one_of",
                ("USA", "D.R."),
            ),
            ordering=(SortSpec("batting.HR", "descending"),),
        )
    )
    assert isinstance(filtered, Ready)
    filtered_rows = execute(filtered.plan)
    assert isinstance(filtered_rows, Rows)
    assert [(row["player.bats"], row["batting.HR"]) for row in filtered_rows.rows] == [
        ("R", 172514),
        ("L", 107148),
        ("B", 22667),
        (None, 823),
    ]

    mixed_stage = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.bats", "batting.HR"),
            groupings=("player.bats",),
            predicate=Any(
                (
                    Compare("player.birth_country", "equals", "USA"),
                    Compare("batting.HR", "greater_than", 190000),
                )
            ),
        )
    )
    assert isinstance(mixed_stage, Rejected)
    assert "cannot mix" in mixed_stage.reason.lower()

    hidden_ordering = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.bats", "batting.HR"),
            groupings=("player.bats",),
            ordering=(SortSpec("player.birth_country", "ascending"),),
        )
    )
    assert isinstance(hidden_ordering, Rejected)

    hidden_partition = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.bats", "batting.HR"),
            groupings=("player.bats",),
            ranking=RankSpec(
                "batting.HR",
                "highest",
                1,
                "include_ties",
                within=("player.birth_country",),
            ),
        )
    )
    assert isinstance(hidden_partition, Rejected)

    mixed_value_ref = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.bats", "batting.HR"),
            groupings=("player.bats",),
            predicate=Compare(
                "player.birth_year",
                "equals",
                ValueRef("batting.HR"),
            ),
        )
    )
    assert isinstance(mixed_value_ref, Rejected)

    post_only_any = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season-league",
            selections=(
                "season",
                "league",
                "batting.HR",
                "batting.HR.league_max",
            ),
            groupings=("season", "league"),
            predicate=Any(
                (
                    Compare("batting.HR", "greater_than", 40),
                    Compare(
                        "batting.HR",
                        "equals",
                        ValueRef("batting.HR.league_max"),
                    ),
                )
            ),
        )
    )
    assert isinstance(post_only_any, Ready)

    source_comparison = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.bats", "batting.HR"),
            groupings=("player.bats",),
            predicate=Compare(
                "player.birth_country",
                "equals",
                ValueRef("player.birth_state"),
            ),
        )
    )
    assert isinstance(source_comparison, Ready)
    source_rows = execute(source_comparison.plan)
    assert isinstance(source_rows, Rows)
    assert len(source_rows.rows) <= 4

    unpublished = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-career",
            selections=("player.birth_city", "batting.HR"),
            groupings=("player.birth_city",),
        )
    )
    assert isinstance(unpublished, Rejected)
