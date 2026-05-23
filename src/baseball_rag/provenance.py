"""Structured answer and provenance models for grounded responses."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SourceType = Literal["duckdb", "system", "stat_definition"]
UnsupportedReason = Literal[
    "unsupported",
    "ambiguous",
    "no_data",
    "llm_unavailable",
]
ReviewReason = Literal["unsupported", "ambiguous"]


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


def secondary_manifest_path(source: str) -> Path:
    """Return the project data manifest path for an optional secondary source."""
    return (
        Path(__file__).resolve().parents[2]
        / "data"
        / "secondary_sources"
        / source
        / "manifest.json"
    )


def load_data_manifest() -> dict[str, Any]:
    """Load the local dataset provenance manifest."""
    with manifest_path().open(encoding="utf-8") as f:
        return json.load(f)


def load_secondary_data_manifest(source: str) -> dict[str, Any]:
    """Load a local secondary-source provenance manifest."""
    with secondary_manifest_path(source).open(encoding="utf-8") as f:
        return json.load(f)


def compact_data_manifest() -> dict[str, Any]:
    """Return the manifest fields most useful inside an answer source."""
    manifest = load_data_manifest()
    return _compact_manifest(manifest)


def compact_secondary_data_manifest(source: str) -> dict[str, Any]:
    """Return compact provenance for an optional secondary source."""
    try:
        manifest = load_secondary_data_manifest(source)
    except FileNotFoundError:
        return {
            "available": False,
            "unavailable_reason": f"{source} manifest is not available",
            "dataset": {},
            "download": {},
            "coverage": {},
            "files": [],
        }

    compact = _compact_manifest(manifest)
    available = bool(compact["files"]) and bool(compact["download"].get("downloaded_at"))
    compact["available"] = available
    if not available:
        compact["unavailable_reason"] = f"{source} manifest has no available local files"
    return compact


def compact_consensus_data_manifest() -> dict[str, Any]:
    """Return answer provenance for Lahman primary plus optional Retrosheet consensus."""
    manifest = compact_data_manifest()
    manifest["consensus_sources"] = [
        {
            "name": "Lahman",
            "role": "primary",
            "dataset": manifest.get("dataset", {}).get("name"),
            "upstream": manifest.get("dataset", {}).get("upstream"),
        },
        {
            "name": "Retrosheet",
            "role": "secondary",
            "dataset": "Retrosheet event/stat consensus",
            "upstream": "Retrosheet",
        },
    ]
    manifest["secondary_manifests"] = {
        "retrosheet": compact_secondary_data_manifest("retrosheet"),
    }
    return manifest


def _compact_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
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
