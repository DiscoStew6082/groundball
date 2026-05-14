"""Tests for the golden eval question runner."""

import json
from pathlib import Path

import yaml

from baseball_rag.provenance import SourceRecord, StructuredAnswer
from evals.questions import (
    EvalReport,
    build_eval_artifact,
    compare_to_baseline,
    format_eval_report,
    format_guardrail_report,
    load_cases,
    main,
    run_cases,
    selected_cases,
    validate_case,
)


def _answer(
    *,
    answer: str = "Davis had 153 RBI",
    intent: str = "stat_query",
    unsupported: bool = False,
    source_type: str = "duckdb",
    rows: list[dict] | None = None,
    unsupported_reason: str | None = None,
    review_reason: str | None = None,
) -> StructuredAnswer:
    return StructuredAnswer(
        answer=answer,
        intent=intent,
        unsupported=unsupported,
        unsupported_reason=unsupported_reason,  # type: ignore[arg-type]
        review_reason=review_reason,  # type: ignore[arg-type]
        sources=[
            SourceRecord(
                type=source_type,  # type: ignore[arg-type]
                label="test source",
                rows=rows if rows is not None else [{"name": "Tommy Davis"}],
                sql="SELECT * FROM batting WHERE yearID = ?",
                data_manifest={"dataset": {}, "files": [], "coverage": {}, "download": {}},
            )
        ],
    )


def test_load_cases_reads_yaml_manifest(tmp_path: Path):
    path = tmp_path / "questions.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "questions": [
                    {
                        "id": "stat_rbi_1962",
                        "question": "who had the most RBIs in 1962",
                        "intent": "stat_query",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert [case.id for case in cases] == ["stat_rbi_1962"]
    assert cases[0].question == "who had the most RBIs in 1962"


def test_selected_cases_defaults_to_ci_safe_stat_queries():
    cases = load_cases()

    selected_ids = {case.id for case in selected_cases(cases)}

    assert "stat_rbi_1962" in selected_ids
    assert "player_bio_babe_ruth" not in selected_ids
    assert "freeform_braves_1936" not in selected_ids


def test_default_selection_rejects_live_llm_cases_even_when_ci_safe_flag_is_set():
    cases = [
        load_cases()[0],
        load_cases()[0].__class__(
            id="bio",
            question="who was Babe Ruth",
            spec={
                "id": "bio",
                "question": "who was Babe Ruth",
                "intent": "player_biography",
                "required_sources": ["duckdb"],
                "ci_safe": True,
            },
        ),
    ]

    assert [case.id for case in selected_cases(cases)] == ["stat_rbi_1962"]
    assert [case.id for case in selected_cases(cases, include_live=True)] == [
        "stat_rbi_1962",
        "bio",
    ]


def test_default_selected_cases_do_not_require_live_services():
    selected = selected_cases(load_cases())

    assert selected
    assert all(not case.requires_live_services() for case in selected)


def test_validate_case_checks_core_expectations():
    case = load_cases()[0]

    failures = validate_case(case, _answer(answer="Tommy Davis finished with 153 RBI"))

    assert failures == []


def test_validate_case_checks_expected_rows_and_parameterized_sql():
    base = load_cases()[0]
    case = base.__class__(
        id="row_match",
        question="500 home run club",
        spec={
            "id": "row_match",
            "question": "500 home run club",
            "intent": "freeform_query",
            "expected_sql_parameterized": True,
            "expected_rows": [{"nameFirst": "Babe", "nameLast": "Ruth", "career_HR": 714}],
        },
    )

    failures = validate_case(
        case,
        _answer(
            answer="Babe Ruth had 714 career HR",
            intent="freeform_query",
            rows=[{"nameFirst": "Babe", "nameLast": "Ruth", "career_HR": 714}],
        ),
    )

    assert failures == []


def test_validate_case_checks_structured_reason_expectations():
    base = load_cases()[0]
    case = base.__class__(
        id="reason_match",
        question="who is in the 500 club",
        spec={
            "id": "reason_match",
            "question": "who is in the 500 club",
            "expected_unsupported": True,
            "expected_unsupported_reason": "ambiguous",
            "expected_review_reason": "ambiguous",
        },
    )

    assert (
        validate_case(
            case,
            _answer(
                unsupported=True,
                unsupported_reason="ambiguous",
                review_reason="ambiguous",
            ),
        )
        == []
    )
    failures = validate_case(
        case,
        _answer(unsupported=True, unsupported_reason="unsupported", review_reason="unsupported"),
    )

    assert "unsupported_reason: expected 'ambiguous', got 'unsupported'" in failures
    assert "review_reason: expected 'ambiguous', got 'unsupported'" in failures


def test_validate_case_reports_mismatches():
    case = load_cases()[0]

    failures = validate_case(
        case,
        _answer(answer="not enough", intent="general_explanation", source_type="system", rows=[]),
    )

    assert "intent: expected 'stat_query', got 'general_explanation'" in failures
    assert "answer missing substring 'Davis'" in failures
    assert "sources missing required type 'duckdb'" in failures
    assert "row count: expected >= 1, got 0" in failures


def test_run_cases_uses_mocked_answer_for_selected_cases_only():
    cases = [
        load_cases()[0],
        load_cases()[0].__class__(
            id="bio",
            question="who was Babe Ruth",
            spec={
                "id": "bio",
                "question": "who was Babe Ruth",
                "intent": "player_biography",
                "required_sources": ["duckdb"],
            },
        ),
    ]
    asked: list[str] = []

    def answer_fn(question: str) -> StructuredAnswer:
        asked.append(question)
        return _answer(answer="Tommy Davis finished with 153 RBI")

    result = run_cases(cases, answer_fn=answer_fn)

    assert result.ok
    assert result.attempted == 1
    assert len(result.skipped) == 1
    assert asked == ["who had the most RBIs in 1962"]


def test_format_eval_report_includes_counts_coverage_and_live_note():
    cases = load_cases()
    result = run_cases(
        cases[:1],
        answer_fn=lambda _question: _answer(answer="Tommy Davis finished with 153 RBI"),
    )
    result.passed.append(
        result.passed[0].__class__(
            case_id="second_case",
            status="passed",
        )
    )
    result.failed.append(
        result.passed[0].__class__(
            case_id="broken_case",
            status="failed",
            failures=["answer missing substring 'Ruth'"],
        )
    )

    report = format_eval_report(
        EvalReport(
            command="python -m evals.questions --report docs/eval-report.md",
            cases=cases,
            include_live=False,
            result=result,
        )
    )

    assert "# Baseball RAG Eval Report" in report
    assert "- Command: `python -m evals.questions --report docs/eval-report.md`" in report
    assert (
        "- Release recommendation: **BLOCK - investigate deterministic eval "
        "failures before release**" in report
    )
    assert "- Passed: 2" in report
    assert "- Failed: 1" in report
    assert "- Pass rate: 66.7%" in report
    assert "- Required pass rate: 85%" in report
    assert "Deterministic/CI-safe mode was used; non-default cases were skipped." in report
    assert "skipped case(s) may require LM Studio" in report
    assert "## Skipped Live Cases" in report
    assert "## Risk Categories" in report
    assert "- Unsupported guardrails:" in report
    assert "stat query: `stat_rbi_1962`" in report
    assert "LLM player biography: `player_bio_babe_ruth`" in report
    assert "- `broken_case`: answer missing substring 'Ruth'" in report


def test_format_eval_report_labels_live_failures_as_full_suite_failures():
    cases = load_cases()
    result = run_cases(
        cases[:1],
        answer_fn=lambda _question: _answer(answer="Tommy Davis finished with 153 RBI"),
    )
    result.failed.append(
        result.passed[0].__class__(
            case_id="live_broken_case",
            status="failed",
            failures=["unsupported: expected True, got False"],
        )
    )

    report = format_eval_report(
        EvalReport(
            command="python -m evals.questions --include-live",
            cases=cases,
            include_live=True,
            result=result,
        )
    )

    assert (
        "- Release recommendation: **BLOCK - investigate full local/live eval "
        "failures before release**" in report
    )
    assert "deterministic eval failures" not in report


def test_build_eval_artifact_labels_live_failures_as_full_suite_failures():
    cases = load_cases()
    result = run_cases(
        cases[:1],
        answer_fn=lambda _question: _answer(answer="Tommy Davis finished with 153 RBI"),
    )
    result.failed.append(
        result.passed[0].__class__(
            case_id="live_broken_case",
            status="failed",
            failures=["unsupported: expected True, got False"],
        )
    )

    artifact = build_eval_artifact(
        EvalReport(
            command="python -m evals.questions --include-live --json-report eval-report.json",
            cases=cases,
            include_live=True,
            result=result,
        ),
        generated_at="2026-04-28T00:00:00+00:00",
    )

    assert (
        artifact["summary"]["release_recommendation"]
        == "BLOCK - investigate full local/live eval failures before release"
    )


def test_build_eval_artifact_includes_summary_versions_and_cases():
    cases = load_cases()
    result = run_cases(
        cases[:1],
        answer_fn=lambda _question: _answer(answer="Tommy Davis finished with 153 RBI"),
    )

    artifact = build_eval_artifact(
        EvalReport(
            command="python -m evals.questions --json-report eval-report.json",
            cases=cases,
            include_live=False,
            result=result,
        ),
        generated_at="2026-04-28T00:00:00+00:00",
    )

    assert artifact["schema_version"] == 1
    assert artifact["summary"]["recommendation"] == "PASS"
    assert artifact["summary"]["passed"] == 1
    assert artifact["versions"]["dataset"]["name"] == "NeuML/baseballdata"
    assert artifact["versions"]["model"]["name"]
    assert artifact["versions"]["prompt"]["version"]
    assert artifact["cases"][0]["case_id"] == "stat_rbi_1962"
    assert artifact["cases"][0]["status"] == "passed"


def test_compare_to_baseline_pass_warn_and_block():
    versions = {
        "dataset": {"hash": "a"},
        "model": {"name": "m1"},
        "prompt": {"version": "p1"},
    }
    current = {
        "summary": {"pass_rate": 1.0},
        "versions": versions,
        "cases": [
            {"case_id": "one", "status": "passed", "failures": []},
            {"case_id": "two", "status": "skipped", "failures": []},
        ],
    }
    assert compare_to_baseline(current, current).recommendation == "PASS"

    drifted = {
        **current,
        "versions": {**versions, "dataset": {"hash": "b"}},
    }
    warn = compare_to_baseline(drifted, current)
    assert warn.recommendation == "WARN"
    assert "dataset version changed" in warn.warnings

    regressed = {
        **current,
        "summary": {"pass_rate": 0.5},
        "cases": [{"case_id": "one", "status": "failed", "failures": ["boom"]}],
    }
    block = compare_to_baseline(regressed, current)
    assert block.recommendation == "BLOCK"
    assert "case one regressed from passed to failed" in block.blockers


def test_format_guardrail_report_groups_coverage_by_risk():
    report = format_guardrail_report(load_cases())

    assert "# Baseball RAG Guardrail Coverage" in report
    assert "## Summary" in report
    assert "- Unsupported guardrails:" in report
    assert "- SQL safety:" in report
    assert "- `unsupported_betting`" in report
    assert "- `stat_sql_injection_stat`" in report
    assert "- `stat_sql_injection_team`" in report
    assert "## Live/Manual Guardrail Cases" in report
    assert "CI-safe deterministic guardrails" in report


def test_main_writes_markdown_report(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "eval-report.md"
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "questions": [
                    {
                        "id": "stat_rbi_1962",
                        "question": "who had the most RBIs in 1962",
                        "intent": "stat_query",
                        "expected_answer_contains": ["Davis", "153", "RBI"],
                        "expected_min_rows": 1,
                        "required_sources": ["duckdb"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def answer_fn(question: str) -> StructuredAnswer:
        assert question == "who had the most RBIs in 1962"
        return _answer(answer="Tommy Davis finished with 153 RBI")

    monkeypatch.setattr(
        "evals.questions.run_cases",
        lambda cases, **_kwargs: run_cases(cases, answer_fn=answer_fn),
    )

    exit_code = main(["--questions", str(questions_path), "--report", str(report_path)])

    assert exit_code == 0
    content = report_path.read_text(encoding="utf-8")
    assert f"- Command: `python -m evals.questions --questions {questions_path} --report" in content
    assert "- Release recommendation: **PASS - deterministic release gate is green**" in content
    assert "- Passed:" in content
    assert "## Failed Cases" in content
    assert "- None" in content


def test_main_writes_json_report_and_compares_baseline(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "eval-report.md"
    json_path = tmp_path / "eval-report.json"
    baseline_path = tmp_path / "baseline.json"
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "questions": [
                    {
                        "id": "stat_rbi_1962",
                        "question": "who had the most RBIs in 1962",
                        "intent": "stat_query",
                        "expected_answer_contains": ["Davis", "153", "RBI"],
                        "expected_min_rows": 1,
                        "required_sources": ["duckdb"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "evals.questions.run_cases",
        lambda cases, **_kwargs: run_cases(
            cases,
            answer_fn=lambda _question: _answer(answer="Tommy Davis finished with 153 RBI"),
        ),
    )

    first_exit = main(["--questions", str(questions_path), "--json-report", str(baseline_path)])
    second_exit = main(
        [
            "--questions",
            str(questions_path),
            "--report",
            str(report_path),
            "--json-report",
            str(json_path),
            "--baseline",
            str(baseline_path),
        ]
    )

    assert first_exit == 0
    assert second_exit == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["baseline_comparison"]["recommendation"] == "PASS"
    assert payload["summary"]["recommendation"] == "PASS"


def test_main_blocks_when_baseline_regresses(tmp_path: Path, monkeypatch):
    json_path = tmp_path / "eval-report.json"
    baseline_path = tmp_path / "baseline.json"
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "questions": [
                    {
                        "id": "stat_rbi_1962",
                        "question": "who had the most RBIs in 1962",
                        "intent": "stat_query",
                        "expected_answer_contains": ["Davis"],
                        "required_sources": ["duckdb"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    baseline_path.write_text(
        json.dumps(
            {
                "summary": {"pass_rate": 1.0},
                "versions": {
                    "dataset": {"hash": "same"},
                    "model": {"name": "same"},
                    "prompt": {"version": "same"},
                },
                "cases": [{"case_id": "stat_rbi_1962", "status": "passed", "failures": []}],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "evals.questions.run_cases",
        lambda cases, **_kwargs: run_cases(
            cases,
            answer_fn=lambda _question: _answer(answer="wrong answer", rows=[]),
        ),
    )
    monkeypatch.setattr(
        "evals.questions._artifact_versions",
        lambda: {
            "dataset": {"hash": "same"},
            "model": {"name": "same"},
            "prompt": {"version": "same"},
        },
    )

    exit_code = main(
        [
            "--questions",
            str(questions_path),
            "--json-report",
            str(json_path),
            "--baseline",
            str(baseline_path),
        ]
    )

    assert exit_code == 1
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["baseline_comparison"]["recommendation"] == "BLOCK"


def test_main_writes_guardrail_report(tmp_path: Path, monkeypatch):
    report_path = tmp_path / "eval-report.md"
    guardrail_path = tmp_path / "guardrail-coverage.md"
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "questions": [
                    {
                        "id": "unsupported_betting",
                        "question": "which team should I bet on tonight",
                        "expected_unsupported": True,
                        "notes": "No betting advice.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("evals.questions.run_cases", lambda cases, **_kwargs: run_cases([]))

    main(
        [
            "--questions",
            str(questions_path),
            "--report",
            str(report_path),
            "--guardrail-report",
            str(guardrail_path),
        ]
    )

    assert "# Baseball RAG Guardrail Coverage" in guardrail_path.read_text(encoding="utf-8")


def test_main_blocks_release_when_no_deterministic_cases_attempted(tmp_path: Path):
    report_path = tmp_path / "eval-report.md"
    questions_path = tmp_path / "questions.yaml"
    questions_path.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "minimum_pass_rate": 0.85,
                "questions": [
                    {
                        "id": "bio",
                        "question": "who was Babe Ruth",
                        "intent": "player_biography",
                        "required_sources": ["duckdb"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(["--questions", str(questions_path), "--report", str(report_path)])

    assert exit_code == 1
    assert (
        "- Release recommendation: **BLOCK - investigate deterministic eval "
        "failures before release**" in report_path.read_text(encoding="utf-8")
    )
