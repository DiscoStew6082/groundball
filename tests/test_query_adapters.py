"""Clean transport Adapters over Query Recipe and Query Run."""

import pytest

from baseball_rag.query.adapters import catalog_payload, run_query_input


def test_natural_language_and_structured_input_return_the_same_recipe_and_plan():
    natural = run_query_input(question="who had the most RBIs in 1962")
    structured = run_query_input(recipe=natural["recipe"])

    assert natural["kind"] == "rows"
    assert structured["kind"] == "rows"
    assert natural["recipe"] == structured["recipe"]
    assert natural["plan"] == structured["plan"]
    assert natural["rows"] == [{"player.name": "Tommy Davis", "season": 1962, "batting.RBI": 153}]
    assert natural["evidence"]["parameterized_sql"]
    assert natural["evidence"]["bound_values"] == [1962]
    assert natural["verification"] == {
        "status": "unavailable",
        "reason": "No passing Coverage Report exists for this catalog and data release.",
        "coverage_report": None,
    }


def test_adapter_exposes_clarification_rejection_no_data_and_export_as_discriminated_outcomes():
    clarification = run_query_input(question="who had the most strikeouts in 2024")
    rejection = run_query_input(question="sum of home runs plus stolen bases")
    no_data = run_query_input(
        recipe={
            "source": "Batting",
            "grain": "player-season",
            "selections": ["player.name", "season", "batting.HR"],
            "predicate": {
                "kind": "all",
                "predicates": [
                    {"kind": "compare", "value": "season", "operator": "equals", "literal": 2024},
                    {
                        "kind": "compare",
                        "value": "batting.HR",
                        "operator": "greater_or_equal",
                        "literal": 100,
                    },
                ],
            },
        }
    )
    exported = run_query_input(
        recipe={
            "source": "Batting",
            "grain": "player-season",
            "selections": ["player.name", "season", "batting.RBI"],
            "predicate": {
                "kind": "compare",
                "value": "season",
                "operator": "equals",
                "literal": 1962,
            },
            "ranking": {
                "value": "batting.RBI",
                "direction": "highest",
                "count": 1,
                "tie_policy": "include_ties",
                "within": [],
            },
            "output": {"kind": "export", "format": "csv"},
        }
    )

    assert clarification["kind"] == "needs_clarification"
    assert "batting or pitching" in clarification["question"].lower()
    assert [choice["label"] for choice in clarification["choices"]] == ["Pitching", "Batting"]
    assert clarification["choices"][0]["recipe"]["source"] == "Pitching"
    assert clarification["choices"][1]["recipe"]["source"] == "Batting"
    assert rejection["kind"] == "rejected"
    assert no_data["kind"] == "no_data"
    assert no_data["rows"] == []
    assert no_data["evidence"]["matched_row_count"] == 0
    assert exported["kind"] == "exported"
    assert exported["export"]["format"] == "csv"
    assert "Tommy Davis" in exported["export"]["content"]
    exported_round_trip = run_query_input(recipe=exported["recipe"])
    assert exported_round_trip["kind"] == "exported"
    assert exported_round_trip["recipe"] == exported["recipe"]


def test_catalog_payload_drives_raw_field_discovery_without_physical_relationship_keys():
    payload = catalog_payload(source="Batting", search="gidp")

    assert payload["catalog_revision"] == "published-query-catalog-v3"
    assert payload["fields"] == [
        {
            "identity": "Batting.GIDP",
            "source": "Batting",
            "column": "GIDP",
            "ordinal": 21,
            "duckdb_type": "BIGINT",
            "data_type": "integer",
            "operations": [
                "select",
                "equals",
                "not_equals",
                "greater_than",
                "greater_or_equal",
                "less_than",
                "less_or_equal",
                "range",
                "group",
                "sort",
                "export",
            ],
        }
    ]
    assert all("keys" not in relationship for relationship in payload["relationships"])


@pytest.mark.parametrize(
    "recipe",
    [
        {
            "source": "Batting",
            "selections": ["Batting.playerID"],
            "predicate": {
                "kind": "compare",
                "value": "Batting.playerID",
                "operator": "equals",
                "literal": "aaronha01",
                "sql": "DROP TABLE batting",
            },
        },
        {
            "source": "Batting",
            "grain": "player-season",
            "selections": ["player.id", "season", "batting.HR"],
            "ranking": {
                "value": "batting.HR",
                "direction": "highest",
                "count": 1,
                "tie_policy": "include_ties",
                "raw_sql": "HR DESC",
            },
        },
        {
            "source": "Batting",
            "selections": ["Batting.playerID"],
            "output": {"kind": "interactive_page", "size": 100, "offset": 0, "sql": "x"},
        },
    ],
)
def test_every_nested_recipe_object_rejects_unknown_executable_looking_keys(recipe):
    with pytest.raises(ValueError, match="Unknown Query Recipe"):
        run_query_input(recipe=recipe)
