"""Public interpretation contracts preserve catalog scope and factual authority."""

from __future__ import annotations

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from baseball_rag import question_interpretation as interpretation
from baseball_rag.db.player_identity import PlayerCandidate, PlayerResolution
from baseball_rag.query.adapters import adapt_natural_query, catalog_payload, recipe_to_dict
from baseball_rag.query.contracts import QueryRecipe


def _recipe(year=2023, name="Aaron Judge"):
    parsed = adapt_natural_query(f"how many home runs did {name} hit in {year}")
    assert isinstance(parsed, QueryRecipe)
    return recipe_to_dict(parsed)


@pytest.fixture
def execution(monkeypatch):
    """Observe the factual boundary without constructing an unrelated database."""
    calls = []
    monkeypatch.setattr(
        interpretation,
        "published_data_runtime",
        lambda: SimpleNamespace(connection=object(), connection_lock=nullcontext()),
    )
    monkeypatch.setattr(
        interpretation, "resolve_player_by_name", lambda name, _: PlayerResolution(name, [])
    )
    monkeypatch.setattr(interpretation, "find_player_mentions", lambda *_: [])
    monkeypatch.setattr(
        interpretation,
        "run_public_query_input",
        lambda **kwargs: calls.append(kwargs) or {"kind": "no_data", "recipe": kwargs["recipe"]},
    )
    return calls


def test_compact_catalog_preserves_every_identity_and_its_supported_scope():
    original = catalog_payload()
    compact = interpretation._compact_catalog()
    assert compact["catalog_revision"] == original["catalog_revision"]
    assert compact["sources"] == [source["identity"] for source in original["sources"]]
    assert compact["relationships"] == original["relationships"]
    fields = {
        identity: (source, data_type, compact["operation_sets"][operations])
        for source, data_type, operations, identities in compact["raw_field_groups"]
        for identity in identities
    }
    assert fields == {
        field["identity"]: (field["source"], field["data_type"], field["operations"])
        for field in original["fields"]
    }
    values = [dict(zip(compact["value_columns"], row, strict=True)) for row in compact["values"]]
    assert {value["identity"] for value in values} == {
        value["identity"] for value in original["values"]
    }
    for expected, actual in zip(original["values"], values, strict=True):
        assert expected["operations"] == compact["operation_sets"][actual["operations_index"]]
        assert expected["allowed_grains"] == compact["grain_sets"][actual["grains_index"]]
        for key in (
            "identity",
            "friendly_name",
            "aliases",
            "kind",
            "data_type",
            "formula",
            "rollup",
            "null_policy",
        ):
            assert actual[key] == expected[key]


def test_model_comparison_grammar_preserves_field_specific_operator_capabilities():
    schema = interpretation.interpretation_request("Compare players", None)["response_format"][
        "json_schema"
    ]
    comparisons = []

    def visit(node):
        if isinstance(node, dict):
            properties = node.get("properties", {})
            if properties.get("kind") == {"const": "compare"}:
                comparisons.append(properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)

    def allowed(identity):
        return {
            operator
            for comparison in comparisons
            if identity in comparison["value"].get("enum", [])
            for operator in comparison["operator"]["enum"]
        }

    assert allowed("player.name") == {"equals", "one_of"}
    assert "range" in allowed("season")
    assert "one_of" not in allowed("season")
    assert "not_equals" not in allowed("player.name")


def test_model_name_list_grammar_does_not_allow_seasons_as_player_names():
    schema = interpretation.interpretation_request("Compare players", None)["response_format"][
        "json_schema"
    ]
    choices = schema["$defs"]["predicate"]["anyOf"]
    name_lists = [
        branch["properties"]["literal"]
        for branch in choices
        if "player.name" in branch["properties"].get("value", {}).get("enum", [])
        and "one_of" in branch["properties"]["operator"]["enum"]
    ]
    assert name_lists
    for literal in name_lists:
        assert literal["type"] == "array"
        assert literal["items"]["type"] == "string"
        assert literal["minItems"] == 1


@pytest.mark.parametrize(
    "encoded",
    [
        "{",
        '```json\n{"kind":"recipe"}\n```',
        '{"kind":"rejected","kind":"recipe"}',
        '{"recipe":{"source":"Batting","source":"Pitching"}}',
        '{"value":NaN}',
        '{"value":Infinity}',
        '{"value":-Infinity}',
        '{"value":1e999}',
        b'{"question":"\xff"}',
    ],
)
def test_json_decoder_rejects_ambiguous_malformed_or_nonfinite_input(encoded):
    with pytest.raises(ValueError):
        interpretation.decode_interpretation_json(encoded)
    assert interpretation.decode_interpretation_json('{"value":1.5,"missing":null}') == {
        "value": 1.5,
        "missing": None,
    }


@pytest.mark.parametrize(
    "proposal",
    [
        {"kind": "rejected", "reason": "Unverified assertion"},
        {"kind": "clarification", "question": "Unverified assertion"},
        {"kind": "clarification", "code": "missing_player", "question": "Unverified assertion"},
        {"kind": "recipe", "recipe": _recipe(), "answer": "Unverified assertion"},
        {"kind": "recipe", "recipe": {**_recipe(), "sql": "select 1"}},
        {"kind": "recipe", "recipe": {**_recipe(), "selections": ["batting.unpublished"]}},
    ],
)
def test_model_prose_and_unpublished_query_fields_never_reach_execution(execution, proposal):
    result = interpretation.run_question_input(
        question="Judge homers?", interpret=lambda *_: proposal
    )
    assert result["kind"] == "rejected"
    assert "Unverified assertion" not in json.dumps(result)
    assert "rows" not in result and "evidence" not in result
    assert execution == []


@pytest.mark.parametrize(
    "code",
    ["missing_player", "missing_season", "missing_statistic", "missing_scope", "missing_team"],
)
def test_missing_context_uses_trusted_clarification_without_executing(execution, code):
    calls = []

    def interpret(question, previous):
        calls.append((question, previous))
        return {"kind": "clarification", "code": code}

    result = interpretation.run_question_input(question="Judge homers?", interpret=interpret)
    assert calls == [("Judge homers?", None)]
    assert result["kind"] == "needs_clarification"
    assert result["question"] and result["choices"] == []
    assert result["recipe"] is None and result["plan"] is None
    assert execution == []


@pytest.mark.parametrize("model_path", [False, True])
def test_ambiguous_entity_clarifies_before_either_natural_path_executes(
    execution, monkeypatch, model_path
):
    monkeypatch.setattr(
        interpretation,
        "resolve_player_by_name",
        lambda name, _: PlayerResolution(
            name,
            [
                PlayerCandidate("smith01", "One Smith", None, None),
                PlayerCandidate("smith02", "Two Smith", None, None),
            ],
        ),
    )
    model_calls = []

    def interpret(*args):
        model_calls.append(args)
        return {"kind": "recipe", "recipe": _recipe(name="Smith")}

    term = "homers" if model_path else "home runs"
    result = interpretation.run_question_input(
        question=f"how many {term} did Smith hit in 2023",
        interpret=interpret,
    )
    assert result["kind"] == "needs_clarification"
    assert len(model_calls) == int(model_path)
    assert execution == []


def test_unique_natural_entity_is_canonicalized_but_explicit_recipe_is_preserved(
    execution, monkeypatch
):
    monkeypatch.setattr(
        interpretation,
        "resolve_player_by_name",
        lambda name, _: PlayerResolution(
            name,
            [
                PlayerCandidate("ohtansh01", "Shohei Ohtani", None, None),
            ],
        ),
    )
    interpretation.run_question_input(question="how many home runs did Ohtani hit in 2023")
    assert execution[0]["recipe"]["predicate"]["predicates"][0]["literal"] == "Shohei Ohtani"
    explicit = _recipe(name="Ohtani")
    interpretation.run_question_input(recipe=explicit)
    assert execution[1] == {"recipe": explicit}


def test_invalid_previous_context_is_refused_before_interpretation_or_execution(execution):
    calls = []
    with pytest.raises(ValueError):
        interpretation.run_question_input(
            question="and the year before?",
            previous_recipe={"sql": "select 1"},
            interpret=lambda *args: calls.append(args),
        )
    assert calls == [] and execution == []


def test_followup_receives_validated_recipe_context_and_executes_validated_result(execution):
    calls = []
    previous = _recipe()

    def interpret(question, context):
        calls.append((question, context))
        return {"kind": "recipe", "recipe": _recipe(2022)}

    result = interpretation.run_question_input(
        question="and the year before?",
        previous_recipe=previous,
        interpret=interpret,
    )
    assert calls == [("and the year before?", previous)]
    assert execution == [{"recipe": _recipe(2022)}]
    assert result["kind"] == "no_data"
