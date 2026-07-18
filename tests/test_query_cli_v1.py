"""CLI Adapter for Query Recipe, Query Run, and catalog discovery."""

import json

import pytest

from baseball_rag.cli import main


def test_cli_natural_language_query_prints_the_canonical_query_run(capsys):
    main(["query", "who had the most RBIs in 1962"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["kind"] == "rows"
    assert payload["recipe"]["source"] == "Batting"
    assert payload["plan"]["version"] == "query-plan-v1"
    assert payload["rows"][0]["player.name"] == "Tommy Davis"
    assert payload["evidence"]["catalog_revision"] == payload["plan"]["catalog_revision"]


def test_cli_structured_recipe_and_field_discovery_share_the_transport_contract(capsys):
    recipe = json.dumps(
        {
            "source": "Batting",
            "selections": ["Batting.playerID", "Batting.yearID", "Batting.GIDP"],
            "predicate": {
                "kind": "compare",
                "value": "Batting.playerID",
                "operator": "equals",
                "literal": "pujolal01",
            },
        }
    )
    main(["query", "--recipe-json", recipe])
    run = json.loads(capsys.readouterr().out)
    assert run["kind"] == "rows"
    assert "Batting.GIDP" in run["rows"][0]

    main(["fields", "--source", "Batting", "--search", "gidp"])
    catalog = json.loads(capsys.readouterr().out)
    assert [item["identity"] for item in catalog["fields"]] == ["Batting.GIDP"]


def test_cli_has_no_legacy_bare_question_mode():
    with pytest.raises(SystemExit):
        main(["who had the most RBIs in 1962"])
