"""Public-behavior tests for the catalog-driven query system."""

from dataclasses import FrozenInstanceError, replace
from inspect import signature

import pytest

from baseball_rag.query import (
    Compare,
    ExecutionUnavailable,
    QueryPlanV1,
    QueryRecipe,
    RankSpec,
    Ready,
    Rejected,
    Rows,
    SortSpec,
    discover_fields,
    execute,
    prepare,
    published_sources,
)


def test_raw_people_birth_city_query_crosses_catalog_plan_execution_and_evidence():
    """A discovered raw field should produce an evidence-complete Query Run."""
    planned = prepare(
        QueryRecipe(
            source="People",
            selections=("People.playerID", "People.birthCity"),
            predicate=Compare(
                value="People.birthCity",
                operator="equals",
                literal="Brooklyn",
            ),
        )
    )

    assert isinstance(planned, Ready)
    assert planned.plan.to_json() == planned.plan.to_json()

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert executed.rows
    assert {row["People.birthCity"] for row in executed.rows} == {"Brooklyn"}
    assert "koufasa01" in {row["People.playerID"] for row in executed.rows}
    assert "?" in executed.evidence.parameterized_sql
    assert "Brooklyn" not in executed.evidence.parameterized_sql
    assert executed.evidence.bound_values == ("Brooklyn",)
    assert executed.evidence.catalog_revision == planned.plan.catalog_revision
    assert executed.evidence.data_release
    assert executed.evidence.sources[0].identity == "People"
    assert executed.evidence.row_count == len(executed.rows)


def test_query_plan_has_canonical_json_round_trip():
    planned = prepare(
        QueryRecipe(
            source="People",
            selections=("People.birthCity",),
            predicate=Compare("People.birthCity", "equals", "Brooklyn"),
        )
    )
    assert isinstance(planned, Ready)

    serialized = planned.plan.to_json()

    assert serialized == (
        '{"catalog_revision":"published-query-catalog-v1","grain":"raw_rows",'
        '"ordering":[],"output":"interactive_page","predicate":{"kind":"compare",'
        '"literal":"Brooklyn","operator":"equals","value":"People.birthCity"},'
        '"ranking":null,"relationships":[],"selections":["People.birthCity"],'
        '"source":"People","version":"query-plan-v1"}'
    )
    assert QueryPlanV1.from_json(serialized) == planned.plan


def test_published_source_and_raw_field_views_are_immutable_and_registry_backed():
    sources = published_sources()
    fields = discover_fields(source="People")

    assert tuple(source.identity for source in sources) == (
        "People",
        "Batting",
        "Pitching",
        "Fielding",
        "TeamReference",
    )
    assert sources[-1].reference_version == "season-aware-v1"
    assert tuple(field.identity for field in fields) == (
        "People.playerID",
        "People.birthCity",
    )
    assert not hasattr(sources[0], "relation")
    assert not hasattr(sources[0], "asset")


def test_adversarial_filter_literal_is_bound_without_changing_sql():
    literal = "Brooklyn' OR 1=1 --"
    planned = prepare(
        QueryRecipe(
            source="People",
            selections=("People.birthCity",),
            predicate=Compare("People.birthCity", "equals", literal),
        )
    )
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert not isinstance(executed, ExecutionUnavailable)
    assert literal not in executed.evidence.parameterized_sql
    assert executed.evidence.bound_values == (literal,)


def test_stale_catalog_and_field_references_fail_before_sql_execution():
    planned = prepare(QueryRecipe(source="People", selections=("People.birthCity",)))
    assert isinstance(planned, Ready)

    stale_catalog = execute(
        replace(planned.plan, catalog_revision="old-catalog"),
    )
    stale_field = execute(
        replace(planned.plan, selections=("People.removedField",)),
    )
    rejected_recipe = prepare(
        QueryRecipe(
            source="People",
            selections=("People.birthCity",),
            catalog_revision="old-catalog",
        )
    )

    assert isinstance(stale_catalog, ExecutionUnavailable)
    assert isinstance(stale_field, ExecutionUnavailable)
    assert isinstance(rejected_recipe, Rejected)


def test_execute_rejects_plan_sections_the_tracer_does_not_publish():
    planned = prepare(QueryRecipe(source="People", selections=("People.playerID",)))
    assert isinstance(planned, Ready)

    unsupported_plans = (
        replace(planned.plan, grain="player_career"),
        replace(planned.plan, relationships=("People-to-Batting",)),
        replace(planned.plan, ranking={"value": "People.playerID"}),
        replace(planned.plan, ordering=({"value": "People.playerID"},)),
        replace(planned.plan, output="export"),
    )

    assert all(isinstance(execute(plan), ExecutionUnavailable) for plan in unsupported_plans)
    assert tuple(signature(execute).parameters) == ("plan",)


def test_text_field_rejects_non_text_literals_during_planning():
    planned = prepare(
        QueryRecipe(
            source="People",
            selections=("People.playerID",),
            predicate=Compare("People.birthCity", "equals", 42),
        )
    )

    assert isinstance(planned, Rejected)
    assert "text literal" in planned.reason


@pytest.mark.parametrize("literal", ["1936", 1936.0, True, None])
def test_integer_field_rejects_non_integer_literals_during_planning(literal):
    planned = prepare(
        QueryRecipe(
            source="TeamReference",
            selections=("TeamReference.yearID",),
            predicate=Compare("TeamReference.yearID", "equals", literal),
        )
    )

    assert isinstance(planned, Rejected)
    assert "integer literal" in planned.reason


def test_query_plan_nested_specs_are_immutable_values():
    plan = QueryPlanV1(
        version="query-plan-v1",
        catalog_revision="published-query-catalog-v1",
        source="People",
        grain="raw_rows",
        selections=("People.playerID",),
        predicate=None,
        ranking=RankSpec(
            value="People.playerID",
            direction="highest",
            count=1,
            tie_policy="include_ties",
        ),
        ordering=(SortSpec(value="People.playerID", direction="ascending"),),
    )

    with pytest.raises(FrozenInstanceError):
        plan.ranking.value = "People.birthCity"
    with pytest.raises(FrozenInstanceError):
        plan.ordering[0].direction = "descending"

    restored = QueryPlanV1.from_json(plan.to_json())
    assert restored == plan


def test_query_plan_deserialization_rejects_untyped_literal_objects():
    serialized = (
        '{"catalog_revision":"published-query-catalog-v1","grain":"raw_rows",'
        '"ordering":[],"output":"interactive_page","predicate":{"kind":"compare",'
        '"literal":{"sql":"DROP TABLE people"},"operator":"equals",'
        '"value":"People.birthCity"},"ranking":null,"relationships":[],'
        '"selections":["People.playerID"],"source":"People",'
        '"version":"query-plan-v1"}'
    )

    with pytest.raises(ValueError, match="typed scalar"):
        QueryPlanV1.from_json(serialized)


def test_season_aware_team_reference_is_a_real_versioned_published_source():
    planned = prepare(
        QueryRecipe(
            source="TeamReference",
            selections=(
                "TeamReference.yearID",
                "TeamReference.teamID",
                "TeamReference.name",
            ),
        )
    )
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert {
        (row["TeamReference.yearID"], row["TeamReference.teamID"], row["TeamReference.name"])
        for row in executed.rows
        if row["TeamReference.yearID"] == 1936 and row["TeamReference.teamID"] == "BSN"
    } == {(1936, "BSN", "Boston Bees")}
    assert executed.evidence.sources[0].identity == "TeamReference"
    assert executed.evidence.sources[0].release == "season-aware-v1"
