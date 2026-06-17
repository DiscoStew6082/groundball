"""Operational health checks for deterministic verification surfaces."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

HealthStatus = Literal["ok", "error"]


@dataclass(frozen=True)
class VerificationHealthCheck:
    """One operational verification readiness check."""

    name: str
    status: HealthStatus
    detail: str

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail}


def operational_verification_health() -> dict[str, Any]:
    """Return deterministic runtime verification readiness."""
    checks = [
        _data_manifest_check(),
        _duckdb_core_tables_check(),
        _guardrail_manifest_check(),
    ]
    status: HealthStatus = "ok" if all(check.status == "ok" for check in checks) else "error"
    return {
        "status": status,
        "checks": [check.to_dict() for check in checks],
        "commands": {
            "focused": "uv run pytest tests/test_api.py -q",
            "full": "uv run pytest -q",
            "eval_gate": (
                "uv run python -m evals.questions --report docs/eval-report.md "
                "--guardrail-report docs/guardrail-coverage.md "
                "--json-report docs/eval-report.json --baseline evals/baseline.json"
            ),
            "browser_smoke": "uv run groundball-ui",
        },
    }


def _data_manifest_check() -> VerificationHealthCheck:
    try:
        from baseball_rag.provenance import compact_data_manifest

        manifest = compact_data_manifest()
        dataset = manifest.get("dataset", {}).get("name")
        files = manifest.get("files", [])
        if not dataset:
            return VerificationHealthCheck(
                "data_manifest",
                "error",
                "Primary data manifest does not name a dataset.",
            )
        if not files:
            return VerificationHealthCheck(
                "data_manifest",
                "error",
                f"Primary data manifest for {dataset} has no files.",
            )
        return VerificationHealthCheck(
            "data_manifest",
            "ok",
            f"Primary manifest loaded for {dataset} with {len(files)} files.",
        )
    except Exception as exc:
        return VerificationHealthCheck("data_manifest", "error", str(exc))


def _duckdb_core_tables_check() -> VerificationHealthCheck:
    try:
        from baseball_rag.db.duckdb_schema import get_duckdb

        conn = get_duckdb()
        counts = {}
        for table in ("people", "batting"):
            row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            if row is None:
                return VerificationHealthCheck(
                    "duckdb_core_tables",
                    "error",
                    f"Core DuckDB table {table} returned no count row.",
                )
            counts[table] = row[0]
        missing = [table for table, count in counts.items() if not count]
        if missing:
            return VerificationHealthCheck(
                "duckdb_core_tables",
                "error",
                "Core DuckDB tables have no rows: " + ", ".join(missing),
            )
        return VerificationHealthCheck(
            "duckdb_core_tables",
            "ok",
            (
                "DuckDB core tables are queryable: "
                f"people={counts['people']}, batting={counts['batting']}."
            ),
        )
    except Exception as exc:
        return VerificationHealthCheck("duckdb_core_tables", "error", str(exc))


def _guardrail_manifest_check() -> VerificationHealthCheck:
    try:
        path = _guardrail_manifest_path()
        if not path.exists():
            return VerificationHealthCheck(
                "guardrail_manifest",
                "ok",
                "Repository guardrail manifest is not present in this package-only runtime.",
            )
        deterministic, unsupported = _guardrail_counts(path)
        if deterministic <= 0 or unsupported <= 0:
            return VerificationHealthCheck(
                "guardrail_manifest",
                "error",
                "Guardrail manifest has no CI-safe deterministic or unsupported cases.",
            )
        return VerificationHealthCheck(
            "guardrail_manifest",
            "ok",
            (
                "Guardrail manifest loaded with "
                f"{deterministic} CI-safe deterministic and {unsupported} unsupported cases."
            ),
        )
    except Exception as exc:
        return VerificationHealthCheck("guardrail_manifest", "error", str(exc))


def _guardrail_manifest_path() -> Path:
    return Path(__file__).resolve().parents[2] / "evals" / "questions.yaml"


def _guardrail_counts(path: Path) -> tuple[int, int]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = raw.get("questions")
    if not isinstance(questions, list):
        raise ValueError(f"{path} must contain a top-level questions list")
    unsupported = 0
    deterministic = 0
    for item in questions:
        if not isinstance(item, dict):
            continue
        is_unsupported = bool(item.get("expected_unsupported"))
        is_sql_safety = bool(item.get("expected_sql_parameterized")) or "sql_injection" in str(
            item.get("id", "")
        )
        if is_unsupported:
            unsupported += 1
        if bool(item.get("ci_safe")) and (is_unsupported or is_sql_safety):
            deterministic += 1
    return deterministic, unsupported
