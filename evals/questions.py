"""CI-safe golden eval runner for ``evals/questions.yaml``."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

import yaml  # type: ignore[import-untyped]

from baseball_rag.provenance import StructuredAnswer
from baseball_rag.retrieval.chroma_store import RetrievedChunk, retrieve
from baseball_rag.retrieval.strategies import available_strategy_names, get_strategy

AnswerFn = Callable[[str], StructuredAnswer]
RouteFn = Callable[[str], Any]
PlayerResolverFn = Callable[[str], Any]


DEFAULT_QUESTIONS_PATH = Path(__file__).with_name("questions.yaml")
LIVE_SOURCE_TYPES = {"chroma"}
LIVE_INTENTS = {"player_biography", "general_explanation"}
RETRIEVAL_CATEGORIES = {"player_biography", "general_explanation"}


@dataclass(frozen=True)
class EvalCase:
    """A single golden question and its expected response properties."""

    id: str
    question: str
    spec: dict[str, Any]

    @property
    def required_sources(self) -> set[str]:
        return {str(source) for source in self.spec.get("required_sources", [])}

    @property
    def intent(self) -> str | None:
        intent = self.spec.get("intent")
        return str(intent) if intent is not None else None

    @property
    def ci_safe(self) -> bool:
        return bool(self.spec.get("ci_safe", False))

    @property
    def retrieval_category(self) -> str | None:
        category = self.spec.get("retrieval_category") or self.intent
        return str(category) if category is not None else None

    @property
    def player_name(self) -> str | None:
        player_name = self.spec.get("player_name")
        return str(player_name) if player_name is not None else None

    def requires_live_services(self) -> bool:
        """Return True when the case is expected to need LLM or live Chroma."""
        if self.required_sources & LIVE_SOURCE_TYPES:
            return True
        return self.intent in LIVE_INTENTS

    def should_run(self, *, include_live: bool = False) -> bool:
        """Select deterministic cases by default, plus explicit opt-ins."""
        if include_live:
            return True
        if self.ci_safe:
            return not self.requires_live_services()
        return (
            self.intent == "stat_query"
            and self.required_sources == {"duckdb"}
            and not self.spec.get("expected_unsupported", False)
            and not self.requires_live_services()
        )

    def is_retrieval_strategy_case(self) -> bool:
        """Return True when retrieval strategy choice can affect this case."""
        if bool(self.spec.get("expected_unsupported", False)):
            return False
        if self.retrieval_category in RETRIEVAL_CATEGORIES:
            return True
        if self.required_sources & LIVE_SOURCE_TYPES:
            return True
        return self.intent in {"player_biography", "general_explanation"}


@dataclass
class EvalCaseResult:
    """Outcome for one eval case."""

    case_id: str
    status: str
    failures: list[str] = field(default_factory=list)
    reason: str | None = None


@dataclass
class EvalRunResult:
    """Aggregate outcome for an eval run."""

    passed: list[EvalCaseResult] = field(default_factory=list)
    failed: list[EvalCaseResult] = field(default_factory=list)
    skipped: list[EvalCaseResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failed

    @property
    def attempted(self) -> int:
        return len(self.passed) + len(self.failed)


@dataclass
class StrategyRunResult:
    """Aggregate outcomes keyed by retrieval strategy name."""

    by_strategy: dict[str, EvalRunResult] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(result.ok for result in self.by_strategy.values())


@dataclass
class RetrievalCaseResult(EvalCaseResult):
    """Outcome for one retrieval-only strategy/case attempt."""

    strategy: str | None = None
    category: str | None = None
    route_intent: str | None = None
    player_name: str | None = None
    player_id: str | None = None
    retrieved_count: int = 0


@dataclass(frozen=True)
class EvalReport:
    """Markdown report content for a CLI eval run."""

    command: str
    cases: list[EvalCase]
    include_live: bool
    minimum_pass_rate: float = 0.85
    result: EvalRunResult | None = None
    strategy_results: dict[str, EvalRunResult] | None = None
    mode: str = "answer"
    baseline_comparison: "BaselineComparison | None" = None


@dataclass(frozen=True)
class BaselineComparison:
    """Result of comparing a current eval artifact to a baseline artifact."""

    recommendation: str
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def load_cases(path: Path = DEFAULT_QUESTIONS_PATH) -> list[EvalCase]:
    """Load eval cases from the YAML manifest."""
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    questions = raw.get("questions")
    if not isinstance(questions, list):
        raise ValueError(f"{path} must contain a top-level questions list")

    cases: list[EvalCase] = []
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Question #{index} must be a mapping")
        case_id = item.get("id")
        question = item.get("question")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"Question #{index} must have a non-empty string id")
        if not isinstance(question, str) or not question:
            raise ValueError(f"Question {case_id!r} must have a non-empty question")
        cases.append(EvalCase(id=case_id, question=question, spec=item))
    return cases


def selected_cases(cases: list[EvalCase], *, include_live: bool = False) -> list[EvalCase]:
    """Return cases runnable under the selected service constraints."""
    return [case for case in cases if case.should_run(include_live=include_live)]


def selected_strategy_cases(cases: list[EvalCase]) -> list[EvalCase]:
    """Return cases where retrieval strategy choice can affect the outcome."""
    return [case for case in cases if case.is_retrieval_strategy_case()]


def run_cases(
    cases: list[EvalCase],
    *,
    answer_fn: AnswerFn | None = None,
    include_live: bool = False,
) -> EvalRunResult:
    """Run selected cases through ``baseball_rag.service.answer`` and validate them."""
    runner: AnswerFn
    if answer_fn is None:
        from baseball_rag.service import answer as service_answer

        def service_runner(value: str) -> StructuredAnswer:
            return service_answer(value)

        runner = service_runner

    else:
        runner = answer_fn

    result = EvalRunResult()
    for case in cases:
        if not case.should_run(include_live=include_live):
            result.skipped.append(
                EvalCaseResult(case_id=case.id, status="skipped", reason="not CI-safe")
            )
            continue

        try:
            answer = runner(case.question)
            failures = validate_case(case, answer)
        except Exception as exc:  # noqa: BLE001 - evals should report all case failures
            failures = [f"{type(exc).__name__}: {exc}"]
        case_result = EvalCaseResult(
            case_id=case.id,
            status="failed" if failures else "passed",
            failures=failures,
        )
        if failures:
            result.failed.append(case_result)
        else:
            result.passed.append(case_result)
    return result


def run_strategy_cases(
    cases: list[EvalCase],
    *,
    strategies: list[str] | None = None,
    answer_factory: Callable[[str], AnswerFn] | None = None,
    include_live: bool = False,
) -> dict[str, EvalRunResult]:
    """Run the same cases once per retrieval strategy."""
    strategy_names = strategies or available_strategy_names()
    strategy_cases = selected_strategy_cases(cases)
    if answer_factory is None:

        def answer_factory(strategy: str) -> AnswerFn:
            from baseball_rag.service import answer as service_answer

            def answer_with_strategy(question: str) -> StructuredAnswer:
                return service_answer(question, retrieval_strategy=strategy)

            return answer_with_strategy

    result: dict[str, EvalRunResult] = {}
    for strategy in strategy_names:
        result[strategy] = run_cases(
            strategy_cases,
            answer_fn=answer_factory(strategy),
            include_live=include_live,
        )
    return result


def run_retrieval_strategy_cases(
    cases: list[EvalCase],
    *,
    strategies: list[str] | None = None,
    route_fn: RouteFn | None = None,
    player_resolver_fn: PlayerResolverFn | None = None,
    retrieve_fn: Callable[..., list[RetrievedChunk]] = retrieve,
    persist_dir: Path | None = None,
    top_k: int = 3,
) -> dict[str, EvalRunResult]:
    """Run retrieval-only evals once per strategy without service.answer or LLM answers."""
    if route_fn is None:
        from baseball_rag.routing import route as route_query

        route_fn = route_query

    result: dict[str, EvalRunResult] = {}
    for strategy_name in strategies or available_strategy_names():
        strategy = get_strategy(strategy_name, retrieve_fn=retrieve_fn)
        run_result = EvalRunResult()
        for case in selected_strategy_cases(cases):
            try:
                decision = _retrieval_decision_for_case(case, route_fn=route_fn)
                category = _retrieval_category_for_case(case, decision)
                player_name = getattr(decision, "player_name", None)
                player_id = _resolve_player_id_for_retrieval_eval(
                    decision,
                    player_resolver_fn=player_resolver_fn,
                )

                if not strategy.is_applicable(category=category, player_id=player_id):
                    run_result.skipped.append(
                        RetrievalCaseResult(
                            case_id=case.id,
                            status="skipped",
                            reason=_strategy_skip_reason(strategy.metadata, category, player_id),
                            strategy=strategy.name,
                            category=category,
                            route_intent=getattr(decision, "intent", None),
                            player_name=player_name,
                            player_id=player_id,
                        )
                    )
                    continue

                chunks = strategy.retrieve(
                    getattr(decision, "raw_question", None) or case.question,
                    top_k=top_k,
                    persist_dir=persist_dir,
                    player_name=player_name,
                    player_id=player_id,
                )
                failures = validate_retrieved_chunks(case, chunks)
                case_result = RetrievalCaseResult(
                    case_id=case.id,
                    status="failed" if failures else "passed",
                    failures=failures,
                    strategy=strategy.name,
                    category=category,
                    route_intent=getattr(decision, "intent", None),
                    player_name=player_name,
                    player_id=player_id,
                    retrieved_count=len(chunks),
                )
            except Exception as exc:  # noqa: BLE001 - evals should report all case failures
                case_result = RetrievalCaseResult(
                    case_id=case.id,
                    status="failed",
                    failures=[f"{type(exc).__name__}: {exc}"],
                    strategy=strategy.name,
                )

            if case_result.failures:
                run_result.failed.append(case_result)
            else:
                run_result.passed.append(case_result)
        result[strategy.name] = run_result
    return result


def format_strategy_summary(result: StrategyRunResult | dict[str, EvalRunResult]) -> str:
    """Render a fixed-width strategy comparison table."""
    by_strategy = result.by_strategy if isinstance(result, StrategyRunResult) else result
    rows = [
        (
            strategy,
            len(run_result.passed),
            len(run_result.failed),
            len(run_result.skipped),
            sum(
                getattr(case_result, "retrieved_count", 0)
                for case_result in run_result.passed + run_result.failed
            ),
        )
        for strategy, run_result in by_strategy.items()
    ]
    strategy_width = max([len("strategy"), *(len(row[0]) for row in rows)])
    lines = [
        f"{'strategy':<{strategy_width}}  {'passed':>6}  {'failed':>6}  "
        f"{'skipped':>7}  {'chunks':>6}"
    ]
    for strategy, passed, failed, skipped, chunks in rows:
        lines.append(
            f"{strategy:<{strategy_width}}  {passed:>6}  {failed:>6}  {skipped:>7}  {chunks:>6}"
        )
    return "\n".join(lines)


def format_eval_report(report: EvalReport) -> str:
    """Render a deterministic Markdown report for portfolio/demo use."""
    counts = _report_counts(report)
    release_recommendation = _release_recommendation(
        passed=counts["passed"],
        failed=counts["failed"],
        attempted=counts["attempted"],
        minimum_pass_rate=report.minimum_pass_rate,
        baseline_comparison=report.baseline_comparison,
    )

    lines = [
        "# Baseball RAG Eval Report",
        "",
        f"- Command: `{report.command}`",
        f"- Mode: {report.mode}",
        f"- Release recommendation: **{release_recommendation}**",
        f"- Cases loaded: {len(report.cases)}",
        f"- Attempted: {counts['attempted']}",
        f"- Passed: {counts['passed']}",
        f"- Failed: {counts['failed']}",
        f"- Skipped: {counts['skipped']}",
        f"- Pass rate: {counts['pass_rate']:.1%}",
        f"- Required pass rate: {report.minimum_pass_rate:.0%}",
        "",
        "## Service Requirements",
        "",
    ]
    if report.include_live:
        lines.append(
            "- Live evals were included; `--include-live` may require Chroma, corpus, "
            "and LLM services."
        )
    else:
        non_default_skipped = sum(
            1 for case in report.cases if not case.should_run(include_live=False)
        )
        live_service_cases = sum(
            1
            for case in report.cases
            if not case.should_run(include_live=False) and case.requires_live_services()
        )
        lines.append(
            "- Deterministic/CI-safe mode was used; non-default cases were skipped. "
            f"{non_default_skipped} case(s) are available behind `--include-live`; "
            f"{live_service_cases} skipped case(s) may require Chroma, corpus, "
            "and LLM services."
        )
        live_examples = [
            case for case in report.cases if case.requires_live_services() and not case.ci_safe
        ][:5]
        if live_examples:
            lines.extend(["", "## Skipped Live Cases", ""])
            for case in live_examples:
                lines.append(f"- `{case.id}`: {case.question}")

    risk_lines = _risk_category_lines(report.cases)
    if risk_lines:
        lines.extend(["", "## Risk Categories", ""])
        lines.extend(risk_lines)

    coverage_lines = _coverage_examples(report.cases)
    if coverage_lines:
        lines.extend(["", "## Suite Coverage", ""])
        lines.extend(coverage_lines)

    if report.baseline_comparison is not None:
        lines.extend(["", "## Baseline Comparison", ""])
        lines.append(f"- Recommendation: {report.baseline_comparison.recommendation}")
        if report.baseline_comparison.blockers:
            lines.extend(f"- Blocker: {blocker}" for blocker in report.baseline_comparison.blockers)
        if report.baseline_comparison.warnings:
            lines.extend(f"- Warning: {warning}" for warning in report.baseline_comparison.warnings)

    failed_results: list[tuple[str | None, EvalCaseResult]]
    if report.strategy_results is not None:
        lines.extend(["", "## Strategy Summary", "", "```text"])
        lines.append(format_strategy_summary(report.strategy_results))
        lines.append("```")
        failed_results = [
            (strategy, case_result)
            for strategy, result in report.strategy_results.items()
            for case_result in result.failed
        ]
    else:
        result = report.result
        if result is None:
            raise ValueError("EvalReport requires result or strategy_results")
        failed_results = [(None, case_result) for case_result in result.failed]

    lines.extend(["", "## Failed Cases", ""])
    if not failed_results:
        lines.append("- None")
    else:
        for strategy, case_result in failed_results:
            prefix = f"{strategy}/" if strategy is not None else ""
            lines.append(f"- `{prefix}{case_result.case_id}`: {'; '.join(case_result.failures)}")

    return "\n".join(lines) + "\n"


def write_eval_report(path: Path, report: EvalReport) -> None:
    """Write an eval report, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_eval_report(report), encoding="utf-8")


def build_eval_artifact(
    report: EvalReport,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a machine-readable eval artifact."""
    counts = _report_counts(report)
    baseline = report.baseline_comparison or BaselineComparison(recommendation="PASS")
    recommendation = _recommendation_label(
        passed=counts["passed"],
        failed=counts["failed"],
        attempted=counts["attempted"],
        minimum_pass_rate=report.minimum_pass_rate,
        baseline_comparison=baseline,
    )
    return {
        "schema_version": 1,
        "command": report.command,
        "mode": report.mode,
        "generated_at": generated_at or datetime.now(UTC).isoformat(),
        "include_live": report.include_live,
        "minimum_pass_rate": report.minimum_pass_rate,
        "summary": {
            "cases_loaded": len(report.cases),
            **counts,
            "recommendation": recommendation,
            "release_recommendation": _release_recommendation(
                passed=counts["passed"],
                failed=counts["failed"],
                attempted=counts["attempted"],
                minimum_pass_rate=report.minimum_pass_rate,
                baseline_comparison=baseline,
            ),
        },
        "versions": _artifact_versions(),
        "baseline_comparison": {
            "recommendation": baseline.recommendation,
            "blockers": baseline.blockers,
            "warnings": baseline.warnings,
        },
        "cases": _artifact_case_results(report),
    }


def write_json_report(path: Path, artifact: dict[str, Any]) -> None:
    """Write a JSON eval artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_json_report(path: Path) -> dict[str, Any]:
    """Load a JSON eval artifact."""
    return json.loads(path.read_text(encoding="utf-8"))


def compare_to_baseline(current: dict[str, Any], baseline: dict[str, Any]) -> BaselineComparison:
    """Compare a current eval artifact to a committed baseline."""
    blockers: list[str] = []
    warnings: list[str] = []

    baseline_cases = {
        str(case.get("case_id")): case for case in baseline.get("cases", []) if case.get("case_id")
    }
    current_cases = {
        str(case.get("case_id")): case for case in current.get("cases", []) if case.get("case_id")
    }
    for case_id, baseline_case in baseline_cases.items():
        current_case = current_cases.get(case_id)
        if current_case is None:
            blockers.append(f"case {case_id} missing from current artifact")
            continue
        if baseline_case.get("status") == "passed" and current_case.get("status") == "failed":
            blockers.append(f"case {case_id} regressed from passed to failed")

    current_pass_rate = float(current.get("summary", {}).get("pass_rate", 0.0))
    baseline_pass_rate = float(baseline.get("summary", {}).get("pass_rate", 0.0))
    if current_pass_rate < baseline_pass_rate:
        blockers.append(
            f"pass rate decreased from {baseline_pass_rate:.3f} to {current_pass_rate:.3f}"
        )

    current_versions = current.get("versions", {})
    baseline_versions = baseline.get("versions", {})
    if current_versions.get("dataset") != baseline_versions.get("dataset"):
        warnings.append("dataset version changed")
    if current_versions.get("model") != baseline_versions.get("model"):
        warnings.append("model version changed")
    if current_versions.get("prompt") != baseline_versions.get("prompt"):
        warnings.append("prompt version changed")

    current_skipped = int(current.get("summary", {}).get("skipped", 0))
    baseline_skipped = int(baseline.get("summary", {}).get("skipped", current_skipped))
    if current_skipped != baseline_skipped:
        warnings.append(f"skipped case count changed from {baseline_skipped} to {current_skipped}")

    if blockers:
        return BaselineComparison(recommendation="BLOCK", blockers=blockers, warnings=warnings)
    if warnings:
        return BaselineComparison(recommendation="WARN", warnings=warnings)
    return BaselineComparison(recommendation="PASS")


def format_guardrail_report(cases: list[EvalCase]) -> str:
    """Render deterministic guardrail coverage from the eval manifest."""
    unsupported_cases = [case for case in cases if case.spec.get("expected_unsupported")]
    sql_safety_cases = [
        case
        for case in cases
        if case.spec.get("expected_sql_parameterized") or "sql_injection" in case.id
    ]
    provenance_cases = [
        case
        for case in cases
        if case.required_sources
        or case.spec.get("required_source_manifest_fields")
        or case.spec.get("expected_sql_visible")
    ]
    ci_safe_guardrails = [
        case for case in unsupported_cases + sql_safety_cases if case.should_run()
    ]
    live_guardrails = [
        case
        for case in unsupported_cases + sql_safety_cases
        if not case.should_run() and case.requires_live_services()
    ]

    lines = [
        "# Baseball RAG Guardrail Coverage",
        "",
        "## Summary",
        "",
        f"- CI-safe deterministic guardrails: {len(_dedupe_cases(ci_safe_guardrails))}",
        f"- Unsupported guardrails: {len(unsupported_cases)}",
        f"- SQL safety: {len(sql_safety_cases)}",
        f"- Provenance/source visibility: {len(provenance_cases)}",
        f"- Live/manual guardrail cases: {len(_dedupe_cases(live_guardrails))}",
        "",
        "## Unsupported Guardrails",
        "",
    ]
    lines.extend(_case_lines(unsupported_cases) or ["- None"])
    lines.extend(["", "## SQL Safety", ""])
    lines.extend(_case_lines(sql_safety_cases) or ["- None"])
    lines.extend(["", "## Provenance And Source Visibility", ""])
    lines.extend(_case_lines(provenance_cases) or ["- None"])
    lines.extend(["", "## Live/Manual Guardrail Cases", ""])
    lines.extend(_case_lines(_dedupe_cases(live_guardrails)) or ["- None"])
    return "\n".join(lines) + "\n"


def write_guardrail_report(path: Path, cases: list[EvalCase]) -> None:
    """Write a deterministic guardrail coverage report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(format_guardrail_report(cases), encoding="utf-8")


def validate_case(case: EvalCase, answer: StructuredAnswer) -> list[str]:
    """Validate supported golden expectations against a structured answer."""
    failures: list[str] = []
    spec = case.spec

    expected_intent = spec.get("intent")
    if expected_intent is not None and answer.intent != expected_intent:
        failures.append(f"intent: expected {expected_intent!r}, got {answer.intent!r}")

    if "expected_unsupported" in spec and answer.unsupported is not bool(
        spec["expected_unsupported"]
    ):
        failures.append(
            f"unsupported: expected {bool(spec['expected_unsupported'])!r}, "
            f"got {answer.unsupported!r}"
        )

    expected_unsupported_reason = spec.get("expected_unsupported_reason")
    if (
        expected_unsupported_reason is not None
        and answer.unsupported_reason != expected_unsupported_reason
    ):
        failures.append(
            "unsupported_reason: expected "
            f"{expected_unsupported_reason!r}, got {answer.unsupported_reason!r}"
        )

    expected_review_reason = spec.get("expected_review_reason")
    if expected_review_reason is not None and answer.review_reason != expected_review_reason:
        failures.append(
            f"review_reason: expected {expected_review_reason!r}, got {answer.review_reason!r}"
        )

    answer_text = _normalized_text(answer.answer)
    for needle in spec.get("expected_answer_contains", []) or []:
        if _normalized_text(str(needle)) not in answer_text:
            failures.append(f"answer missing substring {needle!r}")

    source_types = [source.type for source in answer.sources]
    for source_type in spec.get("required_sources", []) or []:
        if source_type not in source_types:
            failures.append(f"sources missing required type {source_type!r}")

    row_count = _row_count(answer)
    min_rows = spec.get("expected_min_rows")
    if min_rows is not None and row_count < int(min_rows):
        failures.append(f"row count: expected >= {min_rows}, got {row_count}")

    max_rows = spec.get("expected_max_rows")
    if max_rows is not None and row_count > int(max_rows):
        failures.append(f"row count: expected <= {max_rows}, got {row_count}")

    for field_name in spec.get("required_source_manifest_fields", []) or []:
        if not any(
            source.data_manifest and field_name in source.data_manifest for source in answer.sources
        ):
            failures.append(f"source manifest missing field {field_name!r}")

    if spec.get("expected_sql_visible") and not any(source.sql for source in answer.sources):
        failures.append("expected visible SQL on at least one source")

    for needle in spec.get("expected_sql_contains", []) or []:
        if not any(source.sql and str(needle) in source.sql for source in answer.sources):
            failures.append(f"SQL missing substring {needle!r}")

    if spec.get("expected_sql_parameterized") and not any(
        source.sql and "?" in source.sql for source in answer.sources
    ):
        failures.append("expected parameterized SQL with bound placeholders")

    for expected_row in spec.get("expected_rows", []) or []:
        if not isinstance(expected_row, dict):
            failures.append(f"expected row must be a mapping, got {expected_row!r}")
            continue
        if not _source_rows_contain(answer, expected_row):
            failures.append(f"source rows missing expected row {expected_row!r}")

    return failures


def _source_rows_contain(answer: StructuredAnswer, expected: dict[str, Any]) -> bool:
    """Return True when any source row contains all expected key/value pairs."""
    for source in answer.sources:
        for row in source.rows:
            if all(_row_value_matches(row.get(key), value) for key, value in expected.items()):
                return True
    return False


def _row_value_matches(actual: Any, expected: Any) -> bool:
    if isinstance(expected, float):
        try:
            return abs(float(actual) - expected) < 0.000001
        except (TypeError, ValueError):
            return False
    if isinstance(expected, int) and not isinstance(expected, bool):
        try:
            return int(actual) == expected
        except (TypeError, ValueError):
            return False
    return _normalized_text(str(actual)) == _normalized_text(str(expected))


def validate_retrieved_chunks(case: EvalCase, chunks: list[RetrievedChunk]) -> list[str]:
    """Validate YAML retrieval expectations against raw retrieved chunks."""
    failures: list[str] = []
    spec = case.spec

    if "chroma" in case.required_sources and not chunks:
        failures.append("retrieval returned no chunks")

    combined_text = _normalized_text(
        "\n".join(
            " ".join(
                str(value)
                for value in (
                    chunk.title,
                    chunk.text,
                    chunk.source,
                    chunk.category,
                    chunk.player_id,
                    chunk.doc_kind,
                )
                if value
            )
            for chunk in chunks
        )
    )
    needles = []
    seen_needles = set()
    for needle in list(spec.get("expected_retrieved_contains", []) or []) + list(
        spec.get("expected_answer_contains", []) or []
    ):
        normalized_needle = _normalized_text(str(needle))
        if normalized_needle in seen_needles:
            continue
        seen_needles.add(normalized_needle)
        needles.append(needle)

    for needle in needles:
        if _normalized_text(str(needle)) not in combined_text:
            failures.append(f"retrieved chunks missing substring {needle!r}")

    for needle in spec.get("expected_retrieved_title_contains", []) or []:
        if not any(
            _normalized_text(str(needle)) in _normalized_text(chunk.title) for chunk in chunks
        ):
            failures.append(f"retrieved chunk titles missing substring {needle!r}")

    expected_player_id = spec.get("expected_player_id")
    if expected_player_id is not None and not any(
        chunk.player_id == str(expected_player_id) for chunk in chunks
    ):
        failures.append(f"retrieved chunks missing player_id {expected_player_id!r}")

    expected_doc_kind = spec.get("expected_doc_kind")
    if expected_doc_kind is not None and not any(
        chunk.doc_kind == str(expected_doc_kind) for chunk in chunks
    ):
        failures.append(f"retrieved chunks missing doc_kind {expected_doc_kind!r}")

    return failures


def _retrieval_category_for_case(case: EvalCase, decision: Any) -> str:
    category = case.retrieval_category or getattr(decision, "intent", None)
    if category is None:
        return "general_explanation"
    return str(category)


def _retrieval_decision_for_case(case: EvalCase, *, route_fn: RouteFn) -> Any:
    if case.intent is not None and case.retrieval_category is not None:
        from types import SimpleNamespace

        return SimpleNamespace(
            intent=case.intent,
            player_name=case.player_name,
            raw_question=case.question,
        )
    return route_fn(case.question)


def _resolve_player_id_for_retrieval_eval(
    decision: Any,
    *,
    player_resolver_fn: PlayerResolverFn | None,
) -> str | None:
    if getattr(decision, "intent", None) != "player_biography":
        return None
    player_name = getattr(decision, "player_name", None)
    if not player_name:
        return None
    if player_resolver_fn is None:
        from baseball_rag.corpus.player_bios import resolve_player_by_name
        from baseball_rag.db.duckdb_schema import get_duckdb

        resolution = resolve_player_by_name(player_name, get_duckdb())
    else:
        resolution = player_resolver_fn(player_name)
    return getattr(resolution, "player_id", None)


def _strategy_skip_reason(metadata: Any, category: str, player_id: str | None) -> str:
    if category not in metadata.categories:
        return f"strategy does not apply to {category!r}"
    if metadata.requires_player_id and not player_id:
        return "strategy requires a resolved player_id"
    return "strategy not applicable"


def _row_count(answer: StructuredAnswer) -> int:
    return sum(len(source.rows) for source in answer.sources)


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.casefold()


def _coverage_examples(cases: list[EvalCase]) -> list[str]:
    examples: list[str] = []
    seen: set[str] = set()
    labels = {
        "stat_query": "stat query",
        "freeform_query": "freeform SQL query",
        "player_biography": "player biography retrieval",
        "general_explanation": "baseball explanation retrieval",
    }
    for case in cases:
        key = case.retrieval_category or case.intent
        if key is None and case.spec.get("expected_unsupported", False):
            key = "unsupported"
        if key is None or key in seen:
            continue
        label = labels.get(key, "unsupported/guardrail")
        examples.append(f"- {label}: `{case.id}` - {case.question}")
        seen.add(key)
    return examples


def _risk_category_lines(cases: list[EvalCase]) -> list[str]:
    categories = {
        "Grounded stats": sum(1 for case in cases if case.intent == "stat_query"),
        "SQL safety": sum(
            1
            for case in cases
            if case.spec.get("expected_sql_parameterized")
            or "sql_injection" in case.id
            or case.spec.get("expected_sql_visible")
        ),
        "Unsupported guardrails": sum(
            1 for case in cases if bool(case.spec.get("expected_unsupported", False))
        ),
        "Provenance and source visibility": sum(
            1
            for case in cases
            if case.required_sources
            or case.spec.get("required_source_manifest_fields")
            or case.spec.get("expected_sql_visible")
        ),
        "Live retrieval/LLM optional": sum(1 for case in cases if case.requires_live_services()),
    }
    return [f"- {name}: {count} case(s)" for name, count in categories.items()]


def guardrail_coverage_payload(cases: list[EvalCase]) -> dict[str, Any]:
    """Return structured guardrail coverage from the eval manifest."""
    unsupported_cases = [case for case in cases if case.spec.get("expected_unsupported")]
    sql_safety_cases = [
        case
        for case in cases
        if case.spec.get("expected_sql_parameterized") or "sql_injection" in case.id
    ]
    provenance_cases = [
        case
        for case in cases
        if case.required_sources
        or case.spec.get("required_source_manifest_fields")
        or case.spec.get("expected_sql_visible")
    ]
    ci_safe_guardrails = [
        case for case in unsupported_cases + sql_safety_cases if case.should_run()
    ]
    live_guardrails = [
        case
        for case in unsupported_cases + sql_safety_cases
        if not case.should_run() and case.requires_live_services()
    ]
    categories = {
        "unsupported": _case_payloads(unsupported_cases),
        "sql_safety": _case_payloads(sql_safety_cases),
        "provenance_source_visibility": _case_payloads(provenance_cases),
        "live_manual": _case_payloads(_dedupe_cases(live_guardrails)),
    }
    return {
        "summary": {
            "ci_safe_deterministic_guardrails": len(_dedupe_cases(ci_safe_guardrails)),
            "unsupported_guardrails": len(unsupported_cases),
            "sql_safety": len(sql_safety_cases),
            "provenance_source_visibility": len(provenance_cases),
            "live_manual_guardrail_cases": len(_dedupe_cases(live_guardrails)),
        },
        "categories": categories,
        "markdown": format_guardrail_report(cases),
    }


def _dedupe_cases(cases: list[EvalCase]) -> list[EvalCase]:
    result: list[EvalCase] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            continue
        seen.add(case.id)
        result.append(case)
    return result


def _case_lines(cases: list[EvalCase]) -> list[str]:
    lines: list[str] = []
    for case in _dedupe_cases(cases):
        note = case.spec.get("notes")
        suffix = f" - {note}" if note else ""
        lines.append(f"- `{case.id}`: {case.question}{suffix}")
    return lines


def _case_payloads(cases: list[EvalCase]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case.id,
            "question": case.question,
            "notes": case.spec.get("notes"),
        }
        for case in _dedupe_cases(cases)
    ]


def _report_counts(report: EvalReport) -> dict[str, Any]:
    if report.strategy_results is None:
        if report.result is None:
            raise ValueError("EvalReport requires result or strategy_results")
        passed = len(report.result.passed)
        failed = len(report.result.failed)
        skipped = len(report.result.skipped)
        attempted = report.result.attempted
    else:
        passed = sum(len(result.passed) for result in report.strategy_results.values())
        failed = sum(len(result.failed) for result in report.strategy_results.values())
        skipped = sum(len(result.skipped) for result in report.strategy_results.values())
        attempted = passed + failed
    pass_rate = passed / attempted if attempted else 0.0
    return {
        "attempted": attempted,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": pass_rate,
    }


def _artifact_case_results(report: EvalReport) -> list[dict[str, Any]]:
    if report.strategy_results is None:
        if report.result is None:
            raise ValueError("EvalReport requires result or strategy_results")
        return [
            _case_result_payload(case_result)
            for case_result in report.result.passed + report.result.failed + report.result.skipped
        ]
    payloads: list[dict[str, Any]] = []
    for strategy, result in report.strategy_results.items():
        for case_result in result.passed + result.failed + result.skipped:
            payload = _case_result_payload(case_result)
            payload["strategy"] = strategy
            payloads.append(payload)
    return payloads


def _case_result_payload(case_result: EvalCaseResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_id,
        "status": case_result.status,
        "failures": case_result.failures,
        "reason": case_result.reason,
    }


def _artifact_versions() -> dict[str, Any]:
    return {
        "dataset": _dataset_version(),
        "model": _model_version(),
        "prompt": _prompt_version(),
    }


def _dataset_version() -> dict[str, Any]:
    from baseball_rag.provenance import compact_data_manifest

    try:
        manifest = compact_data_manifest()
    except FileNotFoundError:
        return {"name": None, "version": None, "downloaded_at": None, "hash": None}
    digest = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    dataset = manifest.get("dataset", {})
    download = manifest.get("download", {})
    return {
        "name": dataset.get("name"),
        "version": dataset.get("upstream_release"),
        "downloaded_at": download.get("downloaded_at"),
        "hash": f"sha256:{digest}",
    }


def _model_version() -> dict[str, Any]:
    from baseball_rag.generation.llm import DEFAULT_MODEL

    return {"name": os.environ.get("LMSTUDIO_MODEL", DEFAULT_MODEL)}


def _prompt_version() -> dict[str, Any]:
    from baseball_rag.generation.prompt import PROMPT_VERSION

    return {"version": PROMPT_VERSION}


def _release_gate_ok(
    *,
    passed: int,
    failed: int,
    attempted: int,
    minimum_pass_rate: float,
) -> bool:
    pass_rate = passed / attempted if attempted else 0.0
    return failed == 0 and attempted > 0 and pass_rate >= minimum_pass_rate


def _release_recommendation(
    *,
    passed: int,
    failed: int,
    attempted: int,
    minimum_pass_rate: float,
    baseline_comparison: BaselineComparison | None = None,
) -> str:
    label = _recommendation_label(
        passed=passed,
        failed=failed,
        attempted=attempted,
        minimum_pass_rate=minimum_pass_rate,
        baseline_comparison=baseline_comparison,
    )
    if label == "PASS":
        return "PASS - deterministic release gate is green"
    if label == "WARN":
        return "WARN - deterministic gate is green with baseline drift"
    return "BLOCK - investigate deterministic eval failures before release"


def _recommendation_label(
    *,
    passed: int,
    failed: int,
    attempted: int,
    minimum_pass_rate: float,
    baseline_comparison: BaselineComparison | None = None,
) -> str:
    if baseline_comparison is not None and baseline_comparison.recommendation == "BLOCK":
        return "BLOCK"
    if _release_gate_ok(
        passed=passed,
        failed=failed,
        attempted=attempted,
        minimum_pass_rate=minimum_pass_rate,
    ):
        if baseline_comparison is not None and baseline_comparison.recommendation == "WARN":
            return "WARN"
        return "PASS"
    return "BLOCK"


def _minimum_pass_rate(path: Path) -> float:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return float(raw.get("minimum_pass_rate", 0.85))


def _result_release_gate_ok(result: EvalRunResult, *, minimum_pass_rate: float) -> bool:
    return _release_gate_ok(
        passed=len(result.passed),
        failed=len(result.failed),
        attempted=result.attempted,
        minimum_pass_rate=minimum_pass_rate,
    )


def _strategy_release_gate_ok(
    results: dict[str, EvalRunResult],
    *,
    minimum_pass_rate: float,
) -> bool:
    passed = sum(len(result.passed) for result in results.values())
    failed = sum(len(result.failed) for result in results.values())
    attempted = passed + failed
    return _release_gate_ok(
        passed=passed,
        failed=failed,
        attempted=attempted,
        minimum_pass_rate=minimum_pass_rate,
    )


def _command_for_report(argv: list[str] | None) -> str:
    args = sys.argv[1:] if argv is None else argv
    return " ".join(["python", "-m", "evals.questions", *args])


def _apply_baseline_and_write_reports(
    report: EvalReport,
    *,
    markdown_path: Path | None,
    json_path: Path | None,
    baseline_path: Path | None,
) -> tuple[EvalReport, dict[str, Any] | None]:
    artifact = build_eval_artifact(report)
    comparison: BaselineComparison | None = None
    if baseline_path is not None:
        try:
            baseline = load_json_report(baseline_path)
            comparison = compare_to_baseline(artifact, baseline)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            comparison = BaselineComparison(
                recommendation="BLOCK",
                blockers=[f"baseline could not be loaded: {type(exc).__name__}: {exc}"],
            )
        report = EvalReport(
            command=report.command,
            cases=report.cases,
            include_live=report.include_live,
            minimum_pass_rate=report.minimum_pass_rate,
            result=report.result,
            strategy_results=report.strategy_results,
            mode=report.mode,
            baseline_comparison=comparison,
        )
        artifact = build_eval_artifact(report)
    if markdown_path:
        write_eval_report(markdown_path, report)
    if json_path:
        write_json_report(json_path, artifact)
    return report, artifact


def _report_exit_code(report: EvalReport) -> int:
    counts = _report_counts(report)
    label = _recommendation_label(
        passed=counts["passed"],
        failed=counts["failed"],
        attempted=counts["attempted"],
        minimum_pass_rate=report.minimum_pass_rate,
        baseline_comparison=report.baseline_comparison,
    )
    return 0 if label in {"PASS", "WARN"} else 1


def main(argv: list[str] | None = None) -> int:
    """Run evals from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", type=Path, default=DEFAULT_QUESTIONS_PATH)
    parser.add_argument(
        "--include-live",
        action="store_true",
        help="also run cases that may require LLM or Chroma services",
    )
    parser.add_argument(
        "--strategy",
        choices=available_strategy_names(),
        default=None,
        help="run Chroma-backed evals with one retrieval strategy",
    )
    parser.add_argument(
        "--all-strategies",
        action="store_true",
        help="run evals once for each retrieval strategy and print a comparison table",
    )
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="benchmark retrieval strategies using retrieved chunks only; no answer generation",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="write a Markdown eval report to PATH",
    )
    parser.add_argument(
        "--guardrail-report",
        type=Path,
        default=None,
        help="write a deterministic Markdown guardrail coverage report to PATH",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=None,
        help="write a machine-readable JSON eval report to PATH",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="compare current eval results to a JSON baseline artifact",
    )
    args = parser.parse_args(argv)

    cases = load_cases(args.questions)
    minimum_pass_rate = _minimum_pass_rate(args.questions)
    command = _command_for_report(argv)
    if args.guardrail_report:
        write_guardrail_report(args.guardrail_report, cases)
    if args.all_strategies:
        if args.retrieval_only:
            strategy_result = StrategyRunResult(run_retrieval_strategy_cases(cases))
            print(format_strategy_summary(strategy_result))
            for strategy, result in strategy_result.by_strategy.items():
                for failed in result.failed:
                    print(f"- {strategy}/{failed.case_id}: " + "; ".join(failed.failures))
            report, _artifact = _apply_baseline_and_write_reports(
                EvalReport(
                    command=command,
                    cases=cases,
                    include_live=args.include_live,
                    minimum_pass_rate=minimum_pass_rate,
                    strategy_results=strategy_result.by_strategy,
                    mode="retrieval-only all-strategies",
                ),
                markdown_path=args.report,
                json_path=args.json_report,
                baseline_path=args.baseline,
            )
            return _report_exit_code(report)

        strategy_result = StrategyRunResult(
            run_strategy_cases(cases, include_live=args.include_live)
        )
        print(format_strategy_summary(strategy_result))
        for strategy, result in strategy_result.by_strategy.items():
            for failed in result.failed:
                print(f"- {strategy}/{failed.case_id}: " + "; ".join(failed.failures))
        report, _artifact = _apply_baseline_and_write_reports(
            EvalReport(
                command=command,
                cases=cases,
                include_live=args.include_live,
                minimum_pass_rate=minimum_pass_rate,
                strategy_results=strategy_result.by_strategy,
                mode="answer all-strategies",
            ),
            markdown_path=args.report,
            json_path=args.json_report,
            baseline_path=args.baseline,
        )
        return _report_exit_code(report)

    answer_fn: AnswerFn | None = None
    if args.strategy:
        if args.retrieval_only:
            strategy_result = StrategyRunResult(
                run_retrieval_strategy_cases(cases, strategies=[args.strategy])
            )
            print(format_strategy_summary(strategy_result))
            for failed in strategy_result.by_strategy[args.strategy].failed:
                print(f"- {args.strategy}/{failed.case_id}: " + "; ".join(failed.failures))
            report, _artifact = _apply_baseline_and_write_reports(
                EvalReport(
                    command=command,
                    cases=cases,
                    include_live=args.include_live,
                    minimum_pass_rate=minimum_pass_rate,
                    strategy_results=strategy_result.by_strategy,
                    mode=f"retrieval-only strategy {args.strategy}",
                ),
                markdown_path=args.report,
                json_path=args.json_report,
                baseline_path=args.baseline,
            )
            return _report_exit_code(report)

        from baseball_rag.service import answer as service_answer

        def answer_with_strategy(question: str) -> StructuredAnswer:
            return service_answer(question, retrieval_strategy=args.strategy)

        answer_fn = answer_with_strategy

    result = run_cases(cases, answer_fn=answer_fn, include_live=args.include_live)
    print(
        f"evals: {len(result.passed)} passed, {len(result.failed)} failed, "
        f"{len(result.skipped)} skipped"
    )
    for failed in result.failed:
        print(f"- {failed.case_id}: " + "; ".join(failed.failures))
    report, _artifact = _apply_baseline_and_write_reports(
        EvalReport(
            command=command,
            cases=cases,
            include_live=args.include_live,
            minimum_pass_rate=minimum_pass_rate,
            result=result,
            mode="answer",
        ),
        markdown_path=args.report,
        json_path=args.json_report,
        baseline_path=args.baseline,
    )
    return _report_exit_code(report)


if __name__ == "__main__":
    raise SystemExit(main())
