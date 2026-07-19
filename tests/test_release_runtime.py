"""Offline cold-boot contract for the immutable Release Bundle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from baseball_rag.release_bundle import assemble_release_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40
pytestmark = pytest.mark.release_proof


def test_release_bundle_cold_boot_is_offline_in_memory_and_proof_exact(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    identity = assemble_release_bundle(ROOT, bundle, source_commit=SOURCE_COMMIT)
    script = """
import json
import socket

def blocked(*args, **kwargs):
    raise AssertionError("release cold boot attempted network access")

socket.socket.connect = blocked
socket.create_connection = blocked

from fastapi.testclient import TestClient
from baseball_rag.api.server import app, configure_public_admission
from baseball_rag.public_admission import AdmissionState, InMemoryCasStore

class SharedProofStore:
    def __init__(self):
        self.inner = InMemoryCasStore(AdmissionState())

    @property
    def deployment_shared(self):
        return True

    def read(self):
        return self.inner.read()

    def compare_and_swap(self, version, state):
        return self.inner.compare_and_swap(version, state)

coordinator = configure_public_admission(
    store=SharedProofStore(),
    digest_key=b"offline-release-proof-key-material",
)
if not coordinator.initialize_current_budget():
    raise AssertionError("release proof could not create the initial monthly budget")

with TestClient(app) as client:
    ready_response = client.get("/api/release-readiness")
    answer_response = client.post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
    )
    retrosheet_responses = [
        client.post("/api/retrosheet/queries", json={"question": question})
        for question in (
        "how many times did Nolan Ryan strike out the side in his career",
        "when did Nolan Ryan strike out the side in 1973",
        "which pitchers have the most strike out the side games in their careers",
        )
    ]
    capabilities_response = client.get("/api/capabilities")
    for response in (
        ready_response,
        answer_response,
        capabilities_response,
        *retrosheet_responses,
    ):
        response.raise_for_status()

ready = ready_response.json()
answer = answer_response.json()
retrosheet = [response.json() for response in retrosheet_responses]
capabilities = capabilities_response.json()
print(json.dumps({
    "readiness": ready,
    "answer": answer["rows"],
    "retrosheet": [
        {
            "template": result["template"],
            "rows": len(result["rows"]),
            "first": result["rows"][0],
        }
        for result in retrosheet
    ],
    "capabilities": capabilities["retrosheet_capabilities"],
}, sort_keys=True))
"""
    environment = {
        **os.environ,
        "GROUNDBALL_PUBLIC_DEMO": "1",
        "GROUNDBALL_RELEASE_BUNDLE": str(bundle),
        "GROUNDBALL_SOURCE_COMMIT": SOURCE_COMMIT,
    }
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(completed.stdout)

    assert result["readiness"]["release_bundle_digest"] == identity.digest
    assert result["readiness"]["duckdb"] == {
        "database": ":memory:",
        "relations": [
            "batting",
            "fielding",
            "people",
            "pitching",
            "retrosheet_pitcher_strikeout_side_events",
            "retrosheet_team_reference",
            "team_reference",
        ],
    }
    assert result["readiness"]["coverage_report"]["status"] == "passing"
    assert result["answer"] == [{"batting.RBI": 153, "player.name": "Tommy Davis", "season": 1962}]
    assert [item["template"] for item in result["retrosheet"]] == [
        "pitcher_strikeout_side_count",
        "pitcher_strikeout_side_game_log",
        "pitcher_strikeout_side_leaders",
    ]
    assert all(item["rows"] > 0 for item in result["retrosheet"])
    assert result["retrosheet"][0]["first"]["career_strikeout_side_count"] == 324
    assert [item["capability_id"] for item in result["capabilities"]] == ["pitcher_strikeout_side"]
    assert not list(bundle.rglob("*.duckdb"))
