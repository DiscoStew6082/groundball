"""Tests for structured answer provenance payloads."""

import json
from pathlib import Path

from baseball_rag.audit import unsupported_reason
from baseball_rag.outcomes import (
    ambiguous_outcome,
    local_request_failure_outcome,
    no_data_outcome,
    timeout_outcome,
)
from baseball_rag.provenance import (
    StructuredAnswer,
    compact_consensus_data_manifest,
    compact_data_manifest,
)
from baseball_rag.review_queue import build_review_item


def _write_manifest(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_compact_data_manifest_preserves_primary_fields(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.json"
    _write_manifest(
        manifest,
        {
            "dataset": {"name": "NeuML/baseballdata", "upstream": "Lahman"},
            "download": {"downloaded_at": "2026-04-20"},
            "coverage": {"structured_stat_years": {"min": 1871, "max": 2025}},
            "files": [
                {
                    "path": "data/Batting.csv",
                    "table": "batting",
                    "rows": 123,
                    "year_coverage": {"min": 1871, "max": 2025},
                    "sha256": "abc",
                    "source_url": "ignored",
                }
            ],
        },
    )
    monkeypatch.setattr("baseball_rag.provenance.manifest_path", lambda: manifest)

    compact = compact_data_manifest()

    assert compact == {
        "dataset": {"name": "NeuML/baseballdata", "upstream": "Lahman"},
        "download": {"downloaded_at": "2026-04-20"},
        "coverage": {"structured_stat_years": {"min": 1871, "max": 2025}},
        "files": [
            {
                "path": "data/Batting.csv",
                "table": "batting",
                "rows": 123,
                "year_coverage": {"min": 1871, "max": 2025},
                "sha256": "abc",
            }
        ],
        "source_authorities": [
            {
                "name": "Lahman",
                "role": "primary",
                "authority": "factual_stat_authority",
                "dataset": "NeuML/baseballdata",
                "upstream": "Lahman",
                "optional": False,
                "scopes": [
                    "structured_stat_answers",
                    "grounded_database_answers",
                    "player_identity",
                    "biography_stat_claim_primary_verification",
                ],
            }
        ],
    }


def test_consensus_manifest_includes_available_retrosheet_manifest(tmp_path, monkeypatch):
    primary = tmp_path / "manifest.json"
    secondary = tmp_path / "secondary_sources" / "retrosheet" / "manifest.json"
    _write_manifest(
        primary,
        {
            "dataset": {"name": "NeuML/baseballdata", "upstream": "Lahman Baseball Database"},
            "download": {},
            "coverage": {},
            "files": [],
        },
    )
    _write_manifest(
        secondary,
        {
            "dataset": {
                "name": "Retrosheet CSV daily logs",
                "source_url": "https://www.retrosheet.org/downloads/csvdownloads.html",
            },
            "download": {"downloaded_at": "2026-05-22"},
            "coverage": {"year_coverage": {"min": 1901, "max": 2025}},
            "files": [
                {
                    "path": "data/secondary_sources/retrosheet/batting.csv",
                    "table": "retrosheet_batting",
                    "rows": 10,
                    "year_coverage": {"min": 1901, "max": 2025},
                    "sha256": "def",
                }
            ],
        },
    )
    monkeypatch.setattr("baseball_rag.provenance.manifest_path", lambda: primary)
    monkeypatch.setattr(
        "baseball_rag.provenance.secondary_manifest_path",
        lambda source: secondary,
    )

    compact = compact_consensus_data_manifest()

    assert compact["dataset"]["name"] == "NeuML/baseballdata"
    assert compact["consensus_sources"] == [
        {
            "name": "Lahman",
            "role": "primary",
            "dataset": "NeuML/baseballdata",
            "upstream": "Lahman Baseball Database",
        },
        {
            "name": "Retrosheet",
            "role": "secondary",
            "dataset": "Retrosheet event/stat consensus",
            "upstream": "Retrosheet",
        },
    ]
    assert compact["source_authorities"] == [
        {
            "name": "Lahman",
            "role": "primary",
            "authority": "factual_stat_authority",
            "dataset": "NeuML/baseballdata",
            "upstream": "Lahman Baseball Database",
            "optional": False,
            "scopes": [
                "structured_stat_answers",
                "grounded_database_answers",
                "player_identity",
                "biography_stat_claim_primary_verification",
            ],
        },
        {
            "name": "Retrosheet",
            "role": "secondary",
            "authority": "optional_consensus_evidence",
            "dataset": "Retrosheet event/stat consensus",
            "upstream": "Retrosheet",
            "optional": True,
            "scopes": ["biography_stat_claim_consensus"],
        },
    ]
    retrosheet = compact["secondary_manifests"]["retrosheet"]
    assert retrosheet["available"] is True
    assert retrosheet["dataset"]["name"] == "Retrosheet CSV daily logs"
    assert retrosheet["files"] == [
        {
            "path": "data/secondary_sources/retrosheet/batting.csv",
            "table": "retrosheet_batting",
            "rows": 10,
            "year_coverage": {"min": 1901, "max": 2025},
            "sha256": "def",
        }
    ]


def test_consensus_manifest_does_not_treat_event_projection_as_stat_consensus(
    tmp_path, monkeypatch
):
    primary = tmp_path / "manifest.json"
    secondary = tmp_path / "secondary_sources" / "retrosheet" / "manifest.json"
    _write_manifest(
        primary,
        {
            "dataset": {"name": "NeuML/baseballdata", "upstream": "Lahman Baseball Database"},
            "download": {},
            "coverage": {},
            "files": [],
        },
    )
    _write_manifest(
        secondary,
        {
            "dataset": {"name": "Retrosheet event-derived local aggregates"},
            "download": {"downloaded_at": "2026-07-03"},
            "coverage": {"year_coverage": {"min": 1910, "max": 2025}},
            "files": [
                {
                    "path": "data/secondary_sources/retrosheet/pitcher_strikeout_side_events.csv",
                    "table": "retrosheet_pitcher_strikeout_side_events",
                    "rows": 49608,
                    "year_coverage": {"min": 1910, "max": 2025},
                    "sha256": "abc",
                }
            ],
        },
    )
    monkeypatch.setattr("baseball_rag.provenance.manifest_path", lambda: primary)
    monkeypatch.setattr(
        "baseball_rag.provenance.secondary_manifest_path",
        lambda source: secondary,
    )

    retrosheet = compact_consensus_data_manifest()["secondary_manifests"]["retrosheet"]

    assert retrosheet["available"] is False
    assert "retrosheet_batting" in retrosheet["unavailable_reason"]


def test_structured_answer_serializes_metadata():
    answer = StructuredAnswer(
        answer="Tommy Davis led MLB with 153 RBI.",
        intent="stat_query",
        metadata={"route": "stat_query", "latency_ms": 12.5},
        review={"queued": True, "reason": "unsupported", "item_id": "review_abc"},
    )

    assert answer.to_dict()["metadata"] == {"route": "stat_query", "latency_ms": 12.5}
    assert answer.to_dict()["review"] == {
        "queued": True,
        "reason": "unsupported",
        "item_id": "review_abc",
    }


def test_ambiguous_outcome_sets_audit_and_review_reason_without_prose_sniffing():
    answer = ambiguous_outcome(
        answer="Multiple matching players were found.",
        intent="player_biography",
        warnings=["Choose a fuller name."],
    )

    assert answer.unsupported is True
    assert answer.unsupported_reason == "ambiguous"
    assert answer.review_reason == "ambiguous"
    assert unsupported_reason(answer) == "ambiguous"

    item = build_review_item("who was Johnson", answer)

    assert item is not None
    assert item.reason == "ambiguous"


def test_no_data_outcome_is_unsupported_but_reviews_as_unsupported():
    answer = no_data_outcome(
        answer="No results found.",
        intent="stat_query",
        warnings=["No alternate answer was returned."],
    )

    assert answer.unsupported is True
    assert answer.unsupported_reason == "no_data"
    assert answer.review_reason is None
    assert build_review_item("who led MLB in vibes", answer).reason == "unsupported"


def test_timeout_and_local_request_failures_share_llm_unavailable_reason():
    timeout = timeout_outcome(TimeoutError("slow"))
    failure = local_request_failure_outcome(ValueError("bad shape"))

    assert timeout.unsupported_reason == "llm_unavailable"
    assert failure.unsupported_reason == "llm_unavailable"
    assert timeout.warnings == ["slow"]
    assert failure.warnings == ["bad shape"]
