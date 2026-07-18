"""Approved lookup and independently aggregated fact-source relationships."""

from dataclasses import replace

from baseball_rag.query import (
    All,
    Compare,
    ExecutionUnavailable,
    NeedsClarification,
    QueryRecipe,
    Ready,
    Rejected,
    Rows,
    SortSpec,
    execute,
    interpret_recipe,
    prepare,
    published_relationships,
)


def test_all_lookup_relationships_are_published_without_physical_keys():
    relationships = published_relationships()
    assert {item.identity for item in relationships} == {
        "people-to-batting",
        "team-reference-to-batting",
        "people-to-pitching",
        "team-reference-to-pitching",
        "people-to-fielding",
        "team-reference-to-fielding",
    }
    assert all(not hasattr(item, "keys") for item in relationships)


def test_cross_discipline_sources_aggregate_before_shared_grain_join():
    manual = QueryRecipe(
        source="Batting",
        grain="player-season",
        selections=(
            "player.id",
            "player.name",
            "season",
            "batting.HR",
            "pitching.W",
        ),
        predicate=All(
            (
                Compare("batting.HR", "greater_or_equal", 30),
                Compare("pitching.W", "greater_or_equal", 10),
            )
        ),
        ordering=(SortSpec("season", "ascending"),),
    )
    interpreted = interpret_recipe("players with at least 30 HR and 10 pitching wins in one season")
    assert interpreted == manual

    planned = prepare(manual)
    assert isinstance(planned, Ready)
    assert planned.plan.relationships == (
        "people-to-batting",
        "combine-primary-facts",
    )
    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert [
        (
            row["player.id"],
            row["player.name"],
            row["season"],
            row["batting.HR"],
            row["pitching.W"],
        )
        for row in executed.rows
    ] == [
        ("ohtansh01", "Shohei Ohtani", 2022, 34, 15),
        ("ohtansh01", "Shohei Ohtani", 2023, 44, 10),
    ]
    assert {source.identity for source in executed.evidence.sources} == {
        "Batting",
        "People",
        "Pitching",
    }
    sql = executed.evidence.parameterized_sql
    assert 'FROM "batting"' in sql
    assert 'FROM "pitching"' in sql
    assert "JOIN fact_1" in sql


def test_forged_direct_fact_relationship_fails_before_sql():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.id", "season", "batting.HR", "pitching.W"),
        )
    )
    assert isinstance(planned, Ready)
    forged = replace(
        planned.plan,
        relationships=("direct-batting-to-pitching",),
    )

    outcome = execute(forged)

    assert isinstance(outcome, ExecutionUnavailable)


def test_combination_uses_only_fact_sources_referenced_by_the_plan():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.id", "season", "batting.HR", "fielding.PO"),
            predicate=All(
                (
                    Compare("player.id", "equals", "baderha01"),
                    Compare("season", "equals", 2025),
                )
            ),
        )
    )
    assert isinstance(planned, Ready)
    executed = execute(planned.plan)
    assert isinstance(executed, Rows)
    assert dict(executed.rows[0]) == {
        "player.id": "baderha01",
        "season": 2025,
        "batting.HR": 17,
        "fielding.PO": 310,
    }
    assert {source.identity for source in executed.evidence.sources} == {
        "Batting",
        "Fielding",
    }
    assert 'FROM "pitching"' not in executed.evidence.parameterized_sql


def test_cross_discipline_grouping_rejects_during_planning():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.id", "season"),
            groupings=("player.id", "season"),
            predicate=Compare("pitching.W", "greater_or_equal", 10),
        )
    )

    assert isinstance(planned, Rejected)
    assert "named shared grain" in planned.reason


def test_historical_team_question_uses_exact_season_identity_and_name():
    recipe = interpret_recipe("who played for the Braves in 1936")
    assert isinstance(recipe, QueryRecipe)
    planned = prepare(recipe)
    assert isinstance(planned, Ready)
    assert "team-reference-to-batting" in planned.plan.relationships

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert executed.rows
    assert {row["team.id"] for row in executed.rows} == {"BSN"}
    assert {row["team.name"] for row in executed.rows} == {"Boston Bees"}

    ambiguous = interpret_recipe("Braves all time")
    assert isinstance(ambiguous, NeedsClarification)
    assert "historical team identity" in ambiguous.question.lower()
