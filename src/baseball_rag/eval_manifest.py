"""Package-safe eval manifest helpers for runtime metadata and coverage."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

import yaml

LIVE_INTENTS = {"player_biography", "general_explanation"}


class ManifestCase(Protocol):
    """Eval case shape needed by manifest metadata and guardrail coverage."""

    @property
    def id(self) -> str: ...

    @property
    def question(self) -> str: ...

    @property
    def spec(self) -> dict[str, Any]: ...

    @property
    def required_sources(self) -> set[str]: ...

    @property
    def intent(self) -> str | None: ...

    def requires_live_services(self) -> bool: ...

    def should_run(self, *, include_live: bool = False) -> bool: ...


@dataclass(frozen=True)
class EvalManifestCase:
    """Package-local representation of one eval manifest case."""

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

    def requires_live_services(self) -> bool:
        """Return True when the case is expected to need the local LLM."""
        if self.intent == "general_explanation" and "stat_definition" in self.required_sources:
            return False
        return self.intent in LIVE_INTENTS

    def should_run(self, *, include_live: bool = False) -> bool:
        """Select deterministic cases by default, plus explicit opt-ins."""
        if include_live:
            return True
        if self.ci_safe:
            return not self.requires_live_services()
        if (
            self.intent == "general_explanation"
            and self.required_sources
            and not self.requires_live_services()
        ):
            return True
        return (
            self.intent == "stat_query"
            and self.required_sources == {"duckdb"}
            and not self.spec.get("expected_unsupported", False)
            and not self.requires_live_services()
        )


def default_questions_path() -> Path:
    """Return the repo-root eval manifest path when available."""
    return Path(__file__).resolve().parents[2] / "evals" / "questions.yaml"


def load_manifest_cases(path: str | Path | None = None) -> list[EvalManifestCase]:
    """Load eval manifest cases without importing the repo-only ``evals`` package."""
    questions_path = default_questions_path() if path is None else Path(path)
    with questions_path.open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    questions = raw.get("questions")
    if not isinstance(questions, list):
        raise ValueError(f"{questions_path} must contain a top-level questions list")

    cases: list[EvalManifestCase] = []
    for index, item in enumerate(questions, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"Question #{index} must be a mapping")
        case_id = item.get("id")
        question = item.get("question")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"Question #{index} must have a non-empty string id")
        if not isinstance(question, str) or not question:
            raise ValueError(f"Question {case_id!r} must have a non-empty question")
        cases.append(EvalManifestCase(id=case_id, question=question, spec=item))
    return cases


def eval_category_for_question(question: str) -> dict[str, Any]:
    """Return exact eval-manifest match metadata for a question."""
    questions_path = default_questions_path()
    try:
        cases = load_manifest_cases(questions_path)
    except FileNotFoundError:
        return unavailable_eval_match(questions_path)

    normalized = _normalized_text(question)
    for case in cases:
        if _normalized_text(case.question) != normalized:
            continue
        category = case.intent
        if category is None and case.spec.get("expected_unsupported"):
            category = "unsupported"
        return {"matched": True, "case_id": case.id, "category": category}
    return {"matched": False, "case_id": None, "category": None}


def unavailable_eval_match(path: str | Path) -> dict[str, Any]:
    """Return explicit eval metadata for package-only runtimes."""
    return {
        "matched": False,
        "case_id": None,
        "category": None,
        "status": "unavailable",
        "reason": f"Eval manifest is unavailable at {Path(path)}.",
    }


def default_guardrail_coverage_payload() -> dict[str, Any]:
    """Return guardrail coverage when the manifest exists, otherwise unavailable."""
    questions_path = default_questions_path()
    try:
        return guardrail_coverage_payload(load_manifest_cases(questions_path))
    except FileNotFoundError:
        return unavailable_guardrail_coverage_payload(questions_path)


def unavailable_guardrail_coverage_payload(path: str | Path) -> dict[str, Any]:
    """Return explicit guardrail coverage metadata for package-only runtimes."""
    reason = f"Guardrail manifest is unavailable at {Path(path)}."
    return {
        "status": "unavailable",
        "reason": reason,
        "summary": {
            "ci_safe_deterministic_guardrails": 0,
            "unsupported_guardrails": 0,
            "sql_safety": 0,
            "provenance_source_visibility": 0,
            "live_manual_guardrail_cases": 0,
        },
        "categories": {
            "unsupported": [],
            "sql_safety": [],
            "provenance_source_visibility": [],
            "live_manual": [],
        },
        "markdown": _unavailable_guardrail_report(reason),
    }


def format_guardrail_report(cases: Sequence[ManifestCase]) -> str:
    """Render deterministic guardrail coverage from the eval manifest."""
    groups = _guardrail_groups(cases)
    lines = [
        "# Baseball RAG Guardrail Coverage",
        "",
        "## Summary",
        "",
        f"- CI-safe deterministic guardrails: {len(_dedupe_cases(groups.ci_safe))}",
        f"- Unsupported guardrails: {len(groups.unsupported)}",
        f"- SQL safety: {len(groups.sql_safety)}",
        f"- Provenance/source visibility: {len(groups.provenance)}",
        f"- Live/manual guardrail cases: {len(_dedupe_cases(groups.live_manual))}",
        "",
        "## Unsupported Guardrails",
        "",
    ]
    lines.extend(_case_lines(groups.unsupported) or ["- None"])
    lines.extend(["", "## SQL Safety", ""])
    lines.extend(_case_lines(groups.sql_safety) or ["- None"])
    lines.extend(["", "## Provenance And Source Visibility", ""])
    lines.extend(_case_lines(groups.provenance) or ["- None"])
    lines.extend(["", "## Live/Manual Guardrail Cases", ""])
    lines.extend(_case_lines(_dedupe_cases(groups.live_manual)) or ["- None"])
    return "\n".join(lines) + "\n"


def guardrail_coverage_payload(cases: Sequence[ManifestCase]) -> dict[str, Any]:
    """Return structured guardrail coverage from the eval manifest."""
    groups = _guardrail_groups(cases)
    categories = {
        "unsupported": _case_payloads(groups.unsupported),
        "sql_safety": _case_payloads(groups.sql_safety),
        "provenance_source_visibility": _case_payloads(groups.provenance),
        "live_manual": _case_payloads(_dedupe_cases(groups.live_manual)),
    }
    return {
        "summary": {
            "ci_safe_deterministic_guardrails": len(_dedupe_cases(groups.ci_safe)),
            "unsupported_guardrails": len(groups.unsupported),
            "sql_safety": len(groups.sql_safety),
            "provenance_source_visibility": len(groups.provenance),
            "live_manual_guardrail_cases": len(_dedupe_cases(groups.live_manual)),
        },
        "categories": categories,
        "markdown": format_guardrail_report(cases),
    }


@dataclass(frozen=True)
class _GuardrailGroups:
    unsupported: list[ManifestCase]
    sql_safety: list[ManifestCase]
    provenance: list[ManifestCase]
    ci_safe: list[ManifestCase]
    live_manual: list[ManifestCase]


def _guardrail_groups(cases: Sequence[ManifestCase]) -> _GuardrailGroups:
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
    return _GuardrailGroups(
        unsupported=unsupported_cases,
        sql_safety=sql_safety_cases,
        provenance=provenance_cases,
        ci_safe=ci_safe_guardrails,
        live_manual=live_guardrails,
    )


def _dedupe_cases(cases: Sequence[ManifestCase]) -> list[ManifestCase]:
    result: list[ManifestCase] = []
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            continue
        seen.add(case.id)
        result.append(case)
    return result


def _case_lines(cases: Sequence[ManifestCase]) -> list[str]:
    lines: list[str] = []
    for case in _dedupe_cases(cases):
        note = case.spec.get("notes")
        suffix = f" - {note}" if note else ""
        lines.append(f"- `{case.id}`: {case.question}{suffix}")
    return lines


def _case_payloads(cases: Sequence[ManifestCase]) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case.id,
            "question": case.question,
            "notes": case.spec.get("notes"),
        }
        for case in _dedupe_cases(cases)
    ]


def _unavailable_guardrail_report(reason: str) -> str:
    return "\n".join(
        [
            "# Baseball RAG Guardrail Coverage",
            "",
            "## Summary",
            "",
            f"- Status: unavailable ({reason})",
            "- CI-safe deterministic guardrails: 0",
            "- Unsupported guardrails: 0",
            "- SQL safety: 0",
            "- Provenance/source visibility: 0",
            "- Live/manual guardrail cases: 0",
            "",
        ]
    )


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.casefold().strip()
