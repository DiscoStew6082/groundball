"""FastAPI Adapter for the clean Query Recipe and Query Run contracts."""

import pytest
from fastapi.testclient import TestClient

from baseball_rag.api.server import app

client = TestClient(app)


def test_query_run_endpoint_accepts_natural_language_and_structured_recipe():
    natural = client.post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
    )
    assert natural.status_code == 200
    natural_payload = natural.json()
    assert natural_payload["kind"] == "rows"
    assert natural_payload["rows"] == [
        {"player.name": "Tommy Davis", "season": 1962, "batting.RBI": 153}
    ]

    structured = client.post(
        "/api/query-runs",
        json={"recipe": natural_payload["recipe"]},
    )
    assert structured.status_code == 200
    assert structured.json()["plan"] == natural_payload["plan"]


def test_query_run_request_requires_exactly_one_clean_input():
    assert client.post("/api/query-runs", json={}).status_code == 422
    assert (
        client.post(
            "/api/query-runs",
            json={"question": "40-40", "recipe": {"source": "Batting"}},
        ).status_code
        == 422
    )
    malformed = client.post(
        "/api/query-runs",
        json={
            "recipe": {
                "source": "Batting",
                "selections": ["Batting.GIDP"],
                "sql": "DROP TABLE batting",
            }
        },
    )
    assert malformed.status_code == 422
    assert "Unknown Query Recipe fields" in malformed.json()["detail"]

    nested = client.post(
        "/api/query-runs",
        json={
            "recipe": {
                "source": "Batting",
                "selections": ["Batting.playerID"],
                "predicate": {
                    "kind": "compare",
                    "value": "Batting.playerID",
                    "operator": "equals",
                    "literal": "aaronha01",
                    "sql": "DROP TABLE batting",
                },
            }
        },
    )
    assert nested.status_code == 422
    assert "Unknown Query Recipe predicate fields" in nested.json()["detail"]


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_query_run_rejects_non_finite_recipe_literals(literal: str):
    response = client.post(
        "/api/query-runs",
        content=(
            '{"recipe":{"source":"Batting","grain":"player-season",'
            '"selections":["batting.AVG"],"predicate":{"kind":"compare",'
            f'"value":"batting.AVG","operator":"greater_than","literal":{literal}'
            "}}}"
        ),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 422
    assert "finite" in response.json()["detail"].lower()


def test_catalog_endpoint_discovers_raw_gidp_and_old_query_routes_are_absent():
    response = client.get("/api/query-catalog", params={"source": "Batting", "search": "GIDP"})

    assert response.status_code == 200
    assert [field["identity"] for field in response.json()["fields"]] == ["Batting.GIDP"]
    assert client.post("/query", json={"question": "40-40"}).status_code == 405
    assert client.post("/api/query", json={"question": "40-40"}).status_code == 405


def test_coverage_report_has_machine_and_dark_human_representations():
    machine = client.get("/api/query-coverage")
    human = client.get("/coverage-report")

    assert machine.status_code == 200
    assert machine.json()["status"] == "passing"
    assert machine.json()["summary"] == {"covered": 5253, "total": 5253, "uncovered": 0}
    assert human.status_code == 200
    assert "Verified for this data release" in human.text
    assert "color-scheme:dark" in human.text


def test_coverage_routes_reject_stale_or_tampered_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from baseball_rag.query.coverage import CoverageProofUnavailableError

    def reject_stale_report():
        raise CoverageProofUnavailableError("Coverage Report proof hash is invalid.")

    monkeypatch.setattr(
        "baseball_rag.query.coverage.load_passing_coverage_report",
        reject_stale_report,
    )

    machine = client.get("/api/query-coverage")
    human = client.get("/coverage-report")

    assert machine.status_code == 503
    assert human.status_code == 503
    assert "proof hash is invalid" in machine.json()["detail"]


def test_capabilities_publish_the_new_composition_root_only():
    payload = client.get("/api/capabilities").json()

    assert payload["query"] == {
        "endpoint": "/api/query-runs",
        "catalog_endpoint": "/api/query-catalog",
        "coverage_endpoint": "/api/query-coverage",
        "coverage_report": "/coverage-report",
        "natural_language": True,
        "structured_recipe": True,
    }
    assert payload["llm_required"] is False
    assert payload["retrosheet_endpoint"] == "/api/retrosheet/queries"


def test_retrosheet_queries_remain_separate_and_never_fallback_from_primary_questions():
    response = client.post(
        "/api/retrosheet/queries",
        json={"question": "how many times did Nolan Ryan strike out the side in his career"},
    )

    assert response.status_code == 200
    assert response.json()["capability"] == "retrosheet"
    assert response.json()["rows"][0]["career_strikeout_side_count"] == 324
    assert (
        "retrosheet_pitcher_strikeout_side_events"
        in response.json()["evidence"]["parameterized_sql"]
    )
    assert (
        client.post(
            "/api/retrosheet/queries",
            json={"question": "who had the most RBIs in 1962"},
        ).status_code
        == 422
    )
