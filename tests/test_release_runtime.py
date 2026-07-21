"""Offline cold-boot contract for the immutable Release Bundle."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import baseball_rag.query.runtime as query_runtime
from baseball_rag.release_bundle import assemble_release_bundle

ROOT = Path(__file__).resolve().parents[1]
SOURCE_COMMIT = "a" * 40
pytestmark = pytest.mark.release_proof


@pytest.fixture
def no_installed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROUNDBALL_RELEASE_BUNDLE", raising=False)
    monkeypatch.setenv("GROUNDBALL_DATA_DIR", str(ROOT / "release" / "bundle" / "data"))
    monkeypatch.setattr(query_runtime, "_installed_runtime", None)


def test_uninstalled_runtime_preserves_local_and_release_bundle_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_installed_runtime: None,
) -> None:
    local_data = ROOT / "release" / "bundle" / "data"
    monkeypatch.delenv("GROUNDBALL_RELEASE_BUNDLE", raising=False)
    monkeypatch.setenv("GROUNDBALL_DATA_DIR", str(local_data))
    local = query_runtime.published_data_runtime()

    assert query_runtime.published_data_runtime() is local
    assert local.data_dir == local_data.resolve()

    bundle = tmp_path / "bundle"
    shutil.copytree(ROOT / "release" / "bundle", bundle)
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(bundle))
    release = query_runtime.published_data_runtime()

    assert query_runtime.published_data_runtime() is release
    assert release is not local
    assert release.data_dir == (bundle / "data").resolve()


def test_fresh_subprocess_can_install_its_own_published_runtime(
    no_installed_runtime: None,
) -> None:
    parent = query_runtime.published_data_runtime()
    query_runtime.install_published_data_runtime(parent)
    script = """
from dataclasses import replace
from baseball_rag.query.runtime import install_published_data_runtime, published_data_runtime

child = replace(published_data_runtime(), data_release="child-process")
install_published_data_runtime(child)
print(published_data_runtime() is child, published_data_runtime().data_release)
"""
    environment = {**os.environ}
    environment.pop("GROUNDBALL_RELEASE_BUNDLE", None)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert completed.stdout.strip() == "True child-process"
    assert query_runtime.published_data_runtime() is parent


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
        self.inner = InMemoryCasStore()

    @property
    def deployment_shared(self):
        return True

    def read(self):
        return self.inner.read()

    def compare_and_swap(self, version, state):
        return self.inner.compare_and_swap(version, state)

proof_coordination = SharedProofStore()
coordinator = configure_public_admission(
    store=proof_coordination,
    digest_key=b"offline-release-proof-key-material",
)
if not coordinator.initialize_current_budget():
    raise AssertionError("release proof could not create the initial monthly budget")


def visitor_headers(case):
    return {"cookie": f"groundball_visitor=release-proof-{case}"}


structured_ohtani_recipe = {
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
}

with TestClient(app) as client:
    ready_response = client.get("/api/release-readiness")
    answer_response = client.post(
        "/api/query-runs",
        json={"question": "who had the most RBIs in 1962"},
        headers=visitor_headers("rbi-1962"),
    )
    natural_ohtani_response = client.post(
        "/api/query-runs",
        json={
            "question": (
                "how many home runs did ohtani hit in the year he had the most wins as a pitcher"
            )
        },
        headers=visitor_headers("natural-ohtani"),
    )
    structured_ohtani_response = client.post(
        "/api/query-runs",
        json={"recipe": structured_ohtani_recipe},
        headers=visitor_headers("structured-ohtani"),
    )
    first_turn_response = client.post(
        "/api/query-runs",
        json={"question": "how many RBIs did Shohei Ohtani have in 2022"},
        headers=visitor_headers("ohtani-follow-up"),
    )
    first_turn_response.raise_for_status()
    follow_up_request = {
        "question": "what about his home runs in 2022?",
        "previous_recipe": first_turn_response.json()["recipe"],
    }
    follow_up_response = client.post(
        "/api/query-runs",
        json=follow_up_request,
        headers=visitor_headers("ohtani-follow-up"),
    )
    retrosheet_responses = [
        client.post(
            "/api/retrosheet/queries",
            json={"question": question},
            headers=visitor_headers(case),
        )
        for case, question in (
            (
                "retrosheet-count",
                "how many times did Nolan Ryan strike out the side in his career",
            ),
            (
                "retrosheet-log",
                "when did Nolan Ryan strike out the side in 1973",
            ),
            (
                "retrosheet-leaders",
                "which pitchers have the most strike out the side games in their careers",
            ),
        )
    ]
    unbundled_responses = [
        client.post(
            "/api/retrosheet/queries",
            json={"question": question},
            headers=visitor_headers(case),
        )
        for case, question in (
            (
                "retrosheet-streak",
                "what is the longest stolen base streak in MLB history",
            ),
            (
                "retrosheet-stolen-bases",
                "show Rickey Henderson games with at least 2 stolen bases",
            ),
            (
                "retrosheet-strikeouts",
                "show Nolan Ryan games with at least 10 strikeouts",
            ),
        )
    ]
    capabilities_response = client.get("/api/capabilities")
    for response in (
        ready_response,
        answer_response,
        natural_ohtani_response,
        structured_ohtani_response,
        first_turn_response,
        follow_up_response,
        capabilities_response,
        *retrosheet_responses,
    ):
        response.raise_for_status()

ready = ready_response.json()
answer = answer_response.json()
natural_ohtani = natural_ohtani_response.json()
structured_ohtani = structured_ohtani_response.json()
first_turn = first_turn_response.json()
follow_up = follow_up_response.json()
retrosheet = [response.json() for response in retrosheet_responses]
unbundled = [
    {"status": response.status_code, "detail": response.json().get("detail")}
    for response in unbundled_responses
]
capabilities = capabilities_response.json()
print(json.dumps({
    "readiness": ready,
    "answer": answer["rows"],
    "query_statuses": {
        "natural_ohtani": natural_ohtani_response.status_code,
        "structured_ohtani": structured_ohtani_response.status_code,
        "first_turn": first_turn_response.status_code,
        "follow_up": follow_up_response.status_code,
    },
    "ohtani_natural": natural_ohtani,
    "ohtani_structured": structured_ohtani,
    "first_turn": first_turn,
    "follow_up": follow_up,
    "follow_up_request": follow_up_request,
    "admission_start_counts": sorted(
        len(starts) for _, starts in proof_coordination.inner.read().state.starts_by_visitor
    ),
    "retrosheet": [
        {
            "template": result["template"],
            "rows": len(result["rows"]),
            "first": result["rows"][0],
        }
        for result in retrosheet
    ],
    "capabilities": capabilities["retrosheet_capabilities"],
    "unbundled": unbundled,
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

    assert result["query_statuses"] == {
        "natural_ohtani": 200,
        "structured_ohtani": 200,
        "first_turn": 200,
        "follow_up": 200,
    }
    assert result["admission_start_counts"] == [1] * 9 + [2]
    stable_fields = (
        "kind",
        "recipe",
        "plan",
        "rows",
        "evidence",
        "verification",
        "returned_row_count",
        "total_matched_count",
        "pagination",
    )
    assert {field: result["ohtani_natural"][field] for field in stable_fields} == {
        field: result["ohtani_structured"][field] for field in stable_fields
    }
    assert result["ohtani_natural"]["rows"] == [
        {
            "player.name": "Shohei Ohtani",
            "season": 2022,
            "batting.HR": 34,
            "pitching.W": 15,
        }
    ]
    assert result["first_turn"]["rows"] == [
        {"player.name": "Shohei Ohtani", "season": 2022, "batting.RBI": 95}
    ]
    assert result["follow_up"]["rows"] == [
        {"player.name": "Shohei Ohtani", "season": 2022, "batting.HR": 34}
    ]
    assert result["follow_up"]["verification"]["status"] == "verified"
    assert result["follow_up"]["recipe"]["output"] == {
        "kind": "interactive_page",
        "size": 25,
        "offset": 0,
    }
    assert result["follow_up"]["plan"]["output"] == {
        "kind": "interactive_page",
        "size": 25,
        "offset": 0,
    }
    assert result["follow_up"]["returned_row_count"] == 1
    assert result["follow_up"]["total_matched_count"] == 1
    assert result["follow_up"]["pagination"] == {
        "size": 25,
        "offset": 0,
        "has_more": False,
    }
    assert result["follow_up_request"] == {
        "question": "what about his home runs in 2022?",
        "previous_recipe": result["first_turn"]["recipe"],
    }
    assert "rows" not in result["follow_up_request"]["previous_recipe"]
    assert "history" not in result["follow_up_request"]

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
    assert (
        result["unbundled"]
        == [
            {
                "status": 422,
                "detail": "That question is not a published Retrosheet capability.",
            }
        ]
        * 3
    )
    assert not list(bundle.rglob("*.duckdb"))
