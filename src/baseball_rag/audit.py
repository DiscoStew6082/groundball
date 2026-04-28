"""Audit-ready metadata helpers for query responses."""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import UTC, datetime
from typing import Any

from baseball_rag.provenance import StructuredAnswer, compact_data_manifest


def build_query_metadata(
    question: str,
    answer: StructuredAnswer,
    *,
    trace: Any,
) -> dict[str, Any]:
    """Build additive audit metadata for a query response."""
    sources = [source.to_dict() for source in answer.sources]
    source_types = [source["type"] for source in sources if source.get("type")]
    source_labels = [source["label"] for source in sources if source.get("label")]
    sql = _sql_metadata(sources)
    dataset = dataset_version()
    eval_match = eval_category_for_question(question)
    trace_payload = trace_to_dict(trace)
    stable_id_payload = {
        "question": question,
        "route": answer.intent,
        "sql_hash": sql.get("template_hash"),
        "dataset_hash": dataset.get("hash"),
        "eval_case_id": eval_match.get("case_id"),
    }
    query_id = (
        "q_"
        + hashlib.sha256(
            json.dumps(stable_id_payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()[:16]
    )
    return {
        "query_id": query_id,
        "timestamp": datetime.now(UTC).astimezone().isoformat(),
        "route": answer.intent,
        "unsupported": answer.unsupported,
        "unsupported_reason": unsupported_reason(answer),
        "warning_count": len(answer.warnings),
        "source_count": len(sources),
        "source_types": source_types,
        "source_labels": source_labels,
        "sql_visible": bool(sql.get("template")),
        "sql": sql,
        "model": model_version(),
        "dataset": dataset,
        "eval": eval_match,
        "latency_ms": trace_payload["total_ms"],
        "trace": trace_payload,
    }


def trace_to_dict(trace: Any) -> dict[str, Any]:
    """Serialize a pipeline trace for audit metadata."""
    if trace is None:
        return {"route_type": "", "total_ms": 0.0, "stages": []}
    return {
        "route_type": trace.route_type,
        "total_ms": trace.total_ms,
        "stages": [
            {
                "component_id": stage.component_id,
                "label": stage.label,
                "elapsed_ms": stage.elapsed_ms,
                "output_summary": stage.output_summary,
                "error": stage.error,
            }
            for stage in trace.stages
        ],
    }


def sql_template_hash(sql: str) -> str:
    """Hash normalized parameterized SQL."""
    normalized = re.sub(r"\s+", " ", sql.strip().rstrip(";"))
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def dataset_version() -> dict[str, Any]:
    """Return dataset audit version fields."""
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


def model_version() -> dict[str, Any]:
    """Return model and prompt audit versions."""
    from baseball_rag.generation.llm import DEFAULT_MODEL
    from baseball_rag.generation.prompt import PROMPT_VERSION

    return {
        "name": os.environ.get("LMSTUDIO_MODEL", DEFAULT_MODEL),
        "prompt_version": PROMPT_VERSION,
    }


def eval_category_for_question(question: str) -> dict[str, Any]:
    """Return exact eval-manifest match metadata for a question."""
    from evals.questions import load_cases

    normalized = _normalized_text(question)
    for case in load_cases():
        if _normalized_text(case.question) != normalized:
            continue
        category = case.retrieval_category
        if category is None and case.spec.get("expected_unsupported"):
            category = "unsupported"
        return {"matched": True, "case_id": case.id, "category": category}
    return {"matched": False, "case_id": None, "category": None}


def unsupported_reason(answer: StructuredAnswer) -> str | None:
    """Return a structured unsupported reason when available."""
    if not answer.unsupported:
        return None
    for source in answer.sources:
        for row in source.rows:
            reason = row.get("unsupported_reason")
            if reason:
                return str(reason)
    if answer.warnings:
        return answer.warnings[0]
    return "unsupported"


def _sql_metadata(sources: list[dict[str, Any]]) -> dict[str, Any]:
    for source in sources:
        template = source.get("sql")
        if not template:
            continue
        rows = source.get("rows") or []
        return {
            "template": template,
            "template_hash": sql_template_hash(str(template)),
            "parameterized": "?" in str(template),
            "params_count": str(template).count("?"),
            "row_count": len(rows),
            "truncated": len(rows) >= 100,
            "source_label": source.get("label"),
        }
    return {
        "template": None,
        "template_hash": None,
        "parameterized": False,
        "params_count": 0,
        "row_count": 0,
        "truncated": False,
        "source_label": None,
    }


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents.casefold().strip()
