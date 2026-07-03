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
    compact = _compact_manifest(manifest)
    compact["source_authorities"] = source_authority_catalog()
    return compact


def compact_secondary_data_manifest(
    source: str,
    *,
    required_tables: list[str] | None = None,
    any_required_table: bool = False,
) -> dict[str, Any]:
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
    if available and required_tables is not None:
        present_tables = {item.get("table") for item in compact["files"]}
        required = set(required_tables)
        if any_required_table:
            available = bool(required & present_tables)
        else:
            available = required <= present_tables
    compact["available"] = available
    if not available:
        if required_tables:
            compact["unavailable_reason"] = (
                f"{source} manifest does not include required tables: {', '.join(required_tables)}"
            )
        else:
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
        "retrosheet": compact_secondary_data_manifest(
            "retrosheet",
            required_tables=[
                "retrosheet_batting",
                "retrosheet_pitching",
                "retrosheet_fielding",
                "retrosheet_biofile",
            ],
            any_required_table=True,
        ),
    }
    manifest["source_authorities"] = source_authority_catalog(include_retrosheet=True)
    return manifest


def source_authority_catalog(*, include_retrosheet: bool = False) -> list[dict[str, Any]]:
    """Return source authority roles and scopes for public provenance payloads."""
    primary = compact_data_manifest_without_authorities()
    dataset = primary.get("dataset", {})
    authorities: list[dict[str, Any]] = [
        {
            "name": "Lahman",
            "role": "primary",
            "authority": "factual_stat_authority",
            "dataset": dataset.get("name"),
            "upstream": dataset.get("upstream"),
            "optional": False,
            "scopes": [
                "structured_stat_answers",
                "grounded_database_answers",
                "player_identity",
                "biography_stat_claim_primary_verification",
            ],
        }
    ]
    if include_retrosheet:
        authorities.append(
            {
                "name": "Retrosheet",
                "role": "secondary",
                "authority": "optional_consensus_evidence",
                "dataset": "Retrosheet event/stat consensus",
                "upstream": "Retrosheet",
                "optional": True,
                "scopes": ["biography_stat_claim_consensus"],
            }
        )
    return authorities


def compact_data_manifest_without_authorities() -> dict[str, Any]:
    """Return the compact primary manifest without authority catalog metadata."""
    return _compact_manifest(load_data_manifest())


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
