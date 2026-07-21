"""Exercise the packaged public contract through its network-disabled HTTP server."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from baseball_rag.public_release_config import canonical_json_bytes

BASE_URL = "http://127.0.0.1"
PROOF_SCHEMA_VERSION = "ground-ball-release-container-proof-v2"
PUBLIC_INTERFACE_REVISION = "ground-ball-public-interface-v1"


def _get(path: str) -> tuple[int, dict[str, Any]]:
    return _request(path, None)


def _post(path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    return _request(path, payload)


def _request(path: str, payload: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        BASE_URL + path,
        data=None if payload is None else json.dumps(payload).encode("utf-8"),
        headers={} if payload is None else {"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        response = urllib.request.urlopen(request, timeout=10)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        document = json.loads(response.read())
        if not isinstance(document, dict):
            raise AssertionError(f"Non-object response from {path}")
        return response.status, document


def run_probe() -> dict[str, object]:
    checks: list[str] = []
    status, health = _get("/health")
    assert status == 200 and health == {"status": "ok"}
    checks.append("health")

    status, readiness = _get("/api/release-readiness")
    assert status == 200
    assert readiness["duckdb"]["database"] == ":memory:"
    assert readiness["runtime_configuration"]["scope"] == "local_ci"
    checks.append("release-readiness-local-ci")

    status, capabilities = _get("/api/capabilities")
    assert status == 200
    assert [item["capability_id"] for item in capabilities["retrosheet_capabilities"]] == [
        "pitcher_strikeout_side"
    ]
    checks.append("published-capabilities")

    status, tommy = _post("/api/query-runs", {"question": "who had the most RBIs in 1962"})
    assert status == 200
    assert tommy["rows"] == [{"player.name": "Tommy Davis", "season": 1962, "batting.RBI": 153}]
    checks.append("tommy-davis-natural")

    expected_ohtani = {
        "player.name": "Shohei Ohtani",
        "season": 2022,
        "batting.HR": 34,
        "pitching.W": 15,
    }
    status, natural = _post(
        "/api/query-runs",
        {
            "question": (
                "how many home runs did ohtani hit in the year he had the most wins as a pitcher"
            )
        },
    )
    assert status == 200 and natural["rows"] == [expected_ohtani]
    structured_recipe = {
        "source": "Batting",
        "grain": "player-season",
        "selections": ["player.name", "season", "batting.HR", "pitching.W"],
        "predicate": {
            "kind": "compare",
            "value": "player.name",
            "operator": "equals",
            "literal": "Shohei Ohtani",
        },
        "ranking": {
            "value": "pitching.W",
            "direction": "highest",
            "count": 1,
            "tie_policy": "include_ties",
            "within": [],
        },
        "output": {"kind": "interactive_page", "size": 50, "offset": 0},
    }
    status, structured = _post("/api/query-runs", {"recipe": structured_recipe})
    assert status == 200 and structured["rows"] == [expected_ohtani]
    assert structured["pagination"] == {"has_more": False, "offset": 0, "size": 50}
    checks.extend(("ohtani-natural-structured-parity", "paging-envelope"))

    status, first_turn = _post(
        "/api/query-runs", {"question": "how many RBIs did Shohei Ohtani have in 2022"}
    )
    assert status == 200
    status, follow_up = _post(
        "/api/query-runs",
        {
            "question": "what about his home runs in 2022?",
            "previous_recipe": first_turn["recipe"],
        },
    )
    assert status == 200
    assert follow_up["rows"] == [{"player.name": "Shohei Ohtani", "season": 2022, "batting.HR": 34}]
    checks.append("deterministic-follow-up")

    export_recipe = dict(tommy["recipe"])
    export_recipe["output"] = {"kind": "export", "format": "json"}
    status, exported = _post("/api/query-runs", {"recipe": export_recipe})
    assert status == 200 and exported["kind"] == "exported"
    assert exported["evidence"]["matched_row_count"] == 1
    checks.append("complete-export-envelope")

    for question, template in (
        ("how many times did Nolan Ryan strike out the side in his career", "count"),
        ("when did Nolan Ryan strike out the side in 1973", "game-log"),
        ("which pitchers have the most strike out the side games in their careers", "leaders"),
    ):
        status, result = _post("/api/retrosheet/queries", {"question": question})
        assert status == 200 and result["kind"] == "rows" and result["rows"]
        checks.append(f"retrosheet-{template}")
    for question, identity in (
        ("what is the longest stolen base streak in MLB history", "batting-streak"),
        ("show Rickey Henderson games with at least 2 stolen bases", "batting-game-log"),
        ("show Nolan Ryan games with at least 10 strikeouts", "pitcher-daily-log"),
    ):
        status, result = _post("/api/retrosheet/queries", {"question": question})
        assert status == 422 and "not a published Retrosheet capability" in result["detail"]
        checks.append(f"retrosheet-rejects-{identity}")

    proof = {
        "checks": checks,
        "interface": {
            "public_interface_revision": PUBLIC_INTERFACE_REVISION,
            "query_endpoint": "/api/query-runs",
            "retrosheet_endpoint": "/api/retrosheet/queries",
        },
        "runtime_configuration": {
            "network_policy": "none",
            "public_mode": True,
            "release_bundle": "ground-ball-release-bundle",
            "scope": readiness["runtime_configuration"]["scope"],
        },
        "schema_version": PROOF_SCHEMA_VERSION,
        "status": "pass",
    }
    return validate_release_container_proof(canonical_json_bytes(proof))


def validate_release_container_proof(payload: bytes) -> dict[str, object]:
    """Validate canonical, identity-free container contract proof bytes."""
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Release container proof is malformed.") from exc
    expected_keys = {
        "checks",
        "interface",
        "runtime_configuration",
        "schema_version",
        "status",
    }
    interface = document.get("interface") if isinstance(document, dict) else None
    runtime = document.get("runtime_configuration") if isinstance(document, dict) else None
    if (
        not isinstance(document, dict)
        or set(document) != expected_keys
        or payload != canonical_json_bytes(document)
        or document.get("schema_version") != PROOF_SCHEMA_VERSION
        or document.get("status") != "pass"
        or not isinstance(document.get("checks"), list)
        or not document["checks"]
        or any(not isinstance(item, str) or not item for item in document["checks"])
        or interface
        != {
            "public_interface_revision": PUBLIC_INTERFACE_REVISION,
            "query_endpoint": "/api/query-runs",
            "retrosheet_endpoint": "/api/retrosheet/queries",
        }
        or runtime
        != {
            "network_policy": "none",
            "public_mode": True,
            "release_bundle": "ground-ball-release-bundle",
            "scope": "local_ci",
        }
    ):
        raise ValueError("Release container proof is invalid.")
    return document


def main() -> int:
    print(canonical_json_bytes(run_probe()).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
