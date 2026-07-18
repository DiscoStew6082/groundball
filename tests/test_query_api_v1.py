"""FastAPI Adapter for the clean Query Recipe and Query Run contracts."""

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


def test_catalog_endpoint_discovers_raw_gidp_and_old_query_routes_are_absent():
    response = client.get("/api/query-catalog", params={"source": "Batting", "search": "GIDP"})

    assert response.status_code == 200
    assert [field["identity"] for field in response.json()["fields"]] == ["Batting.GIDP"]
    assert client.post("/query", json={"question": "40-40"}).status_code == 405
    assert client.post("/api/query", json={"question": "40-40"}).status_code == 405


def test_capabilities_publish_the_new_composition_root_only():
    payload = client.get("/api/capabilities").json()

    assert payload["query"] == {
        "endpoint": "/api/query-runs",
        "catalog_endpoint": "/api/query-catalog",
        "natural_language": True,
        "structured_recipe": True,
    }


def test_retrosheet_queries_remain_separate_and_never_fallback_from_primary_questions(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.request_execution.execute_public_demo_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Retrosheet query re-entered the legacy request router")
        ),
    )
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
