from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from baseball_rag.query import QueryPlanV1, QueryRecipe, Ready, prepare
from baseball_rag.query.coverage import (
    COVERAGE_REPORT_PATH,
    REQUIRED_GATE_IDS,
    CoverageProofUnavailableError,
    canonical_proof_id,
    current_proof_identity,
    load_passing_coverage_report,
    render_coverage_markdown,
)
from baseball_rag.query.data_identity import semantic_manifest_sha256


def _passing_report() -> dict[str, object]:
    identity = current_proof_identity()
    gates = [
        {
            "identity": gate_id,
            "status": "passing",
            "covered": 1,
            "total": 1,
            "failures": [],
            "obligations": [{"identity": f"{gate_id}:fixture", "status": "passing"}],
            "details": {},
        }
        for gate_id in REQUIRED_GATE_IDS
    ]
    report = {
        "schema_version": "query-coverage-report-v1",
        "status": "passing",
        "proof_identity": identity,
        "summary": {"covered": 6, "total": 6, "uncovered": 0},
        "sources": [],
        "gates": gates,
        "failures": [],
    }
    report["proof_id"] = canonical_proof_id(report)
    return report


def test_passing_coverage_report_requires_exact_current_proof(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "coverage-report.json"
    report_path.write_text(json.dumps(_passing_report()), encoding="utf-8")
    monkeypatch.setattr("baseball_rag.query.coverage.COVERAGE_REPORT_PATH", report_path)

    report = load_passing_coverage_report()
    assert report["status"] == "passing"

    stale = _passing_report()
    stale["proof_identity"] = {**stale["proof_identity"], "compiler_sha256": "stale"}
    stale["proof_id"] = canonical_proof_id(stale)
    report_path.write_text(json.dumps(stale), encoding="utf-8")
    with pytest.raises(CoverageProofUnavailableError, match="stale"):
        load_passing_coverage_report()


def test_failed_or_uncovered_coverage_report_is_not_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    report_path = tmp_path / "coverage-report.json"
    report = _passing_report()
    report["status"] = "failing"
    report["failures"] = ["formula golden failed"]
    report["summary"] = {"covered": 5, "total": 6, "uncovered": 1}
    report["proof_id"] = canonical_proof_id(report)
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.setattr("baseball_rag.query.coverage.COVERAGE_REPORT_PATH", report_path)

    with pytest.raises(CoverageProofUnavailableError, match="not passing"):
        load_passing_coverage_report()


def test_human_report_is_rendered_from_the_canonical_read_model() -> None:
    report = _passing_report()
    markdown = render_coverage_markdown(report)

    assert "# Ground Ball Query Coverage Report" in markdown
    assert "Verified for this data release" in markdown
    assert current_proof_identity()["catalog_revision"] in markdown
    assert "catalog_schema_identity" in markdown
    assert "1 / 1" in markdown
    assert "6 / 6" in markdown


def test_checked_in_report_location_is_packaged_with_query_module() -> None:
    assert COVERAGE_REPORT_PATH.name == "coverage-report.json"
    assert COVERAGE_REPORT_PATH.parent.name == "coverage"


def test_semantic_manifest_identity_ignores_download_metadata_but_not_data() -> None:
    manifest = {
        "dataset": {"release_id": "release-1"},
        "download": {"downloaded_at": "today"},
        "files": [
            {
                "path": "data/People.csv",
                "table": "people",
                "rows": 2,
                "year_coverage": None,
                "sha256": "abc",
                "source_url": "https://example.test/People.csv",
            }
        ],
    }
    changed_download = {**manifest, "download": {"downloaded_at": "tomorrow"}}
    changed_rows = {
        **manifest,
        "files": [{**manifest["files"][0], "rows": 3}],
    }

    assert semantic_manifest_sha256(manifest) == semantic_manifest_sha256(changed_download)
    assert semantic_manifest_sha256(manifest) != semantic_manifest_sha256(changed_rows)


def test_query_plan_json_is_closed_and_type_strict() -> None:
    planned = prepare(QueryRecipe(source="People", selections=("People.playerID",)))
    assert isinstance(planned, Ready)
    payload = planned.plan.as_dict()

    with pytest.raises(ValueError, match="unknown fields"):
        QueryPlanV1.from_json(json.dumps({**payload, "sql": "DROP TABLE people"}))

    bad_output = {**payload, "output": {**payload["output"], "size": True}}
    with pytest.raises(ValueError, match="integer"):
        QueryPlanV1.from_json(json.dumps(bad_output))

    bad_plan = replace(planned.plan, version="query-plan-v0")
    assert bad_plan != QueryPlanV1.from_json(planned.plan.to_json())
