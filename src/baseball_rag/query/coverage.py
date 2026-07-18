"""Canonical completeness proof for one query catalog and packaged data release."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from baseball_rag.query.contracts import QueryEvidence
from baseball_rag.query.data_identity import semantic_manifest_sha256
from baseball_rag.query.registry import CATALOG_DIR, catalog_revision
from baseball_rag.query.runtime import published_data_runtime

REPORT_SCHEMA_VERSION = "query-coverage-report-v1"
MODULE_DIR = Path(__file__).resolve().parent
COVERAGE_DIR = MODULE_DIR / "coverage"
COVERAGE_REPORT_PATH = COVERAGE_DIR / "coverage-report.json"
COVERAGE_MARKDOWN_PATH = COVERAGE_DIR / "coverage-report.md"

_COMPILER_CONTRACT_FILES = (
    *tuple(sorted(MODULE_DIR.glob("*.py"))),
    MODULE_DIR / "eval_matrix.json",
)
_CATALOG_FILES = tuple(sorted(CATALOG_DIR.glob("*.json"))) + tuple(
    sorted((CATALOG_DIR / "assets").glob("*"))
)
REQUIRED_GATE_IDS = (
    "catalog_schema_identity",
    "raw_reachability",
    "promoted_exactness",
    "plan_compiler_safety",
    "outcome_evidence_integrity",
    "no_llm_no_mac",
)


class CoverageProofUnavailableError(RuntimeError):
    """The checked-in coverage proof is absent, failing, or stale."""


def current_proof_identity() -> dict[str, Any]:
    """Return the exact identity that invalidates stale generated proof."""
    runtime = published_data_runtime()
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "catalog_revision": catalog_revision(),
        "catalog_sha256": _files_digest(_CATALOG_FILES),
        "data_release": runtime.data_release,
        "data_manifest_semantic_sha256": semantic_manifest_sha256(runtime.manifest),
        "compiler_contract": "query-plan-v1",
        "compiler_sha256": _files_digest(_COMPILER_CONTRACT_FILES),
        "source_fingerprints": dict(sorted(runtime.source_fingerprints.items())),
    }


def load_coverage_report() -> dict[str, Any]:
    """Load the canonical machine-readable report without asserting readiness."""
    try:
        value = json.loads(COVERAGE_REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CoverageProofUnavailableError("Coverage Report is unavailable.") from exc
    if not isinstance(value, dict):
        raise CoverageProofUnavailableError("Coverage Report is malformed.")
    return value


def load_passing_coverage_report() -> dict[str, Any]:
    """Return proof only when it passes and matches the current runtime exactly."""
    report = load_coverage_report()
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise CoverageProofUnavailableError("Coverage Report schema is stale.")
    if report.get("proof_id") != canonical_proof_id(report):
        raise CoverageProofUnavailableError("Coverage Report proof hash is invalid.")
    if report.get("proof_identity") != current_proof_identity():
        raise CoverageProofUnavailableError(
            "Coverage Report is stale for this catalog or data release."
        )
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise CoverageProofUnavailableError("Coverage Report summary is malformed.")
    if (
        report.get("status") != "passing"
        or report.get("failures")
        or summary.get("uncovered") != 0
        or summary.get("covered") != summary.get("total")
    ):
        raise CoverageProofUnavailableError("Coverage Report is not passing.")
    gates = report.get("gates")
    if (
        not isinstance(gates, list)
        or not all(isinstance(gate, dict) for gate in gates)
        or tuple(gate.get("identity") for gate in gates) != REQUIRED_GATE_IDS
    ):
        raise CoverageProofUnavailableError("Coverage Report gate set is incomplete.")
    for gate in gates:
        obligations = gate.get("obligations")
        if (
            not isinstance(gate, dict)
            or gate.get("status") != "passing"
            or not isinstance(gate.get("covered"), int)
            or gate.get("covered") != gate.get("total")
            or gate.get("failures")
            or not isinstance(obligations, list)
            or len(obligations) != gate.get("total")
            or any(
                not isinstance(item, dict)
                or not isinstance(item.get("identity"), str)
                or item.get("status") != "passing"
                for item in obligations
            )
        ):
            raise CoverageProofUnavailableError("Coverage Report contains a failing gate.")
    return report


def verification_payload(evidence: QueryEvidence) -> dict[str, str | None]:
    """Return the shared adapter verification state for factual outcomes."""
    try:
        report = load_passing_coverage_report()
    except CoverageProofUnavailableError as exc:
        return {"status": "unavailable", "reason": str(exc), "coverage_report": None}
    identity = report["proof_identity"]
    source_fingerprints = identity["source_fingerprints"]
    evidence_matches = (
        evidence.catalog_revision == identity["catalog_revision"]
        and evidence.data_release == identity["data_release"]
        and all(
            source_fingerprints.get(source.identity) == source.row_fingerprint
            for source in evidence.sources
        )
    )
    if not evidence_matches:
        return {
            "status": "unavailable",
            "reason": "Query Run evidence does not match the passing Coverage Report.",
            "coverage_report": None,
        }
    return {
        "status": "verified",
        "reason": "Verified for this data release.",
        "coverage_report": "/coverage-report",
    }


def canonical_proof_id(report: Mapping[str, Any]) -> str:
    """Hash canonical report content while excluding the self-referential proof ID."""
    payload = {key: value for key, value in report.items() if key != "proof_id"}
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def render_coverage_markdown(report: Mapping[str, Any]) -> str:
    """Render the human representation exclusively from canonical gate results."""
    identity = report.get("proof_identity", {})
    summary = report.get("summary", {})
    passing = report.get("status") == "passing" and summary.get("uncovered") == 0
    lines = [
        "# Ground Ball Query Coverage Report",
        "",
        (
            "**Verified for this data release**"
            if passing
            else "**Not verified for this data release**"
        ),
        "",
        f"- Catalog: `{identity.get('catalog_revision', 'unavailable')}`",
        f"- Data release: `{identity.get('data_release', 'unavailable')}`",
        f"- Report schema: `{report.get('schema_version', 'unavailable')}`",
        f"- Proof ID: `{report.get('proof_id', 'unavailable')}`",
        f"- Covered obligations: {summary.get('covered', 'unavailable')} / "
        f"{summary.get('total', 'unavailable')}",
        f"- Uncovered obligations: {summary.get('uncovered', 'unavailable')}",
        "",
        "## Release-blocking gates",
        "",
        "| Gate | Status | Coverage |",
        "| --- | --- | ---: |",
    ]
    gates = report.get("gates", [])
    if isinstance(gates, list):
        for gate in gates:
            if not isinstance(gate, Mapping):
                continue
            lines.append(
                f"| `{gate.get('identity', 'unknown')}` | {gate.get('status', 'unknown')} | "
                f"{gate.get('covered', 0)} / {gate.get('total', 0)} |"
            )
    failures = report.get("failures", [])
    if isinstance(failures, list) and failures:
        lines.extend(["", "## Failures", "", *(f"- {item}" for item in failures)])
    return "\n".join(lines) + "\n"


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files_digest(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
