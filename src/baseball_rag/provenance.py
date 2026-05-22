"""Structured answer and provenance models for grounded responses."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SourceType = Literal["duckdb", "system", "corpus"]
UnsupportedReason = Literal[
    "unsupported",
    "ambiguous",
    "no_data",
    "missing_corpus",
    "retrieval_failed",
    "llm_unavailable",
]
ReviewReason = Literal["unsupported", "ambiguous", "low_confidence"]


@dataclass
class SourceRecord:
    """A single source used to ground an answer."""

    type: SourceType
    label: str
    detail: str | None = None
    sql: str | None = None
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    score: float | None = None
    data_manifest: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable source record."""
        return {
            "type": self.type,
            "label": self.label,
            "detail": self.detail,
            "sql": self.sql,
            "rows": self.rows,
            "columns": self.columns,
            "score": self.score,
            "data_manifest": self.data_manifest,
        }


@dataclass
class StructuredAnswer:
    """Grounded answer returned by the shared answer service."""

    answer: str
    intent: str
    sources: list[SourceRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unsupported: bool = False
    unsupported_reason: UnsupportedReason | None = None
    review_reason: ReviewReason | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable answer payload."""
        return {
            "answer": self.answer,
            "intent": self.intent,
            "sources": [source.to_dict() for source in self.sources],
            "warnings": self.warnings,
            "unsupported": self.unsupported,
            "unsupported_reason": self.unsupported_reason,
            "review_reason": self.review_reason,
            "metadata": self.metadata,
            "review": self.review,
        }


def manifest_path() -> Path:
    """Return the project data manifest path."""
    return Path(__file__).resolve().parents[2] / "data" / "manifest.json"


def load_data_manifest() -> dict[str, Any]:
    """Load the local dataset provenance manifest."""
    with manifest_path().open(encoding="utf-8") as f:
        return json.load(f)


def compact_data_manifest() -> dict[str, Any]:
    """Return the manifest fields most useful inside an answer source."""
    manifest = load_data_manifest()
    return {
        "dataset": manifest.get("dataset", {}),
        "download": manifest.get("download", {}),
        "coverage": manifest.get("coverage", {}),
        "files": [
            {
                "path": item.get("path"),
                "table": item.get("table"),
                "rows": item.get("rows"),
                "year_coverage": item.get("year_coverage"),
                "sha256": item.get("sha256"),
            }
            for item in manifest.get("files", [])
        ],
    }
