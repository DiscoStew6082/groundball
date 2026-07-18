"""Published Lahman Source Registry and raw-field discovery read models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

CATALOG_DIR = Path(__file__).with_name("catalog")


@dataclass(frozen=True)
class PublishedSourceView:
    """Rendering-neutral published source metadata."""

    identity: str
    kind: str
    reference_version: str | None = None


@dataclass(frozen=True)
class _SourceBinding:
    identity: str
    kind: str
    relation: str
    asset: str | None
    manifest_table: str | None
    primary_key: tuple[str, ...]
    reference_manifest: str | None = None
    reference_version: str | None = None


@dataclass(frozen=True)
class RawField:
    identity: str
    source: str
    column: str
    data_type: str
    operations: tuple[str, ...]


@lru_cache(maxsize=1)
def _source_bindings() -> tuple[_SourceBinding, ...]:
    payload = _read_json("published_sources.json")
    return tuple(
        _SourceBinding(
            identity=item["identity"],
            kind=item["kind"],
            relation=item["relation"],
            asset=item.get("asset"),
            manifest_table=item.get("manifest_table"),
            primary_key=tuple(item["primary_key"]),
            reference_manifest=item.get("reference_manifest"),
            reference_version=item.get("reference_version"),
        )
        for item in payload["sources"]
    )


@lru_cache(maxsize=1)
def published_sources() -> tuple[PublishedSourceView, ...]:
    return tuple(
        PublishedSourceView(
            identity=source.identity,
            kind=source.kind,
            reference_version=source.reference_version,
        )
        for source in _source_bindings()
    )


@lru_cache(maxsize=1)
def discover_fields(*, source: str | None = None) -> tuple[RawField, ...]:
    payload = _read_json("raw_fields.json")
    fields = tuple(
        RawField(
            identity=item["identity"],
            source=item["source"],
            column=item["column"],
            data_type=item["data_type"],
            operations=tuple(item["operations"]),
        )
        for item in payload["fields"]
    )
    if source is None:
        return fields
    return tuple(field for field in fields if field.source == source)


@lru_cache(maxsize=1)
def catalog_revision() -> str:
    return str(_read_json("published_catalog.json")["catalog_revision"])


def source_by_identity(identity: str) -> _SourceBinding | None:
    return next((source for source in _source_bindings() if source.identity == identity), None)


def field_by_identity(identity: str) -> RawField | None:
    return next((field for field in discover_fields() if field.identity == identity), None)


def _read_json(filename: str) -> dict[str, Any]:
    return json.loads((CATALOG_DIR / filename).read_text(encoding="utf-8"))
