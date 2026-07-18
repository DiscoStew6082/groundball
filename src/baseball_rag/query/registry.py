"""Published Lahman Source Registry and raw-field discovery read models."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

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
    ordinal: int
    duckdb_type: str
    data_type: str
    operations: tuple[str, ...]


@dataclass(frozen=True)
class PromotedValueView:
    """Rendering-neutral promoted value metadata."""

    identity: str
    friendly_name: str
    aliases: tuple[str, ...]
    kind: str
    data_type: str
    formula: str | None
    rollup: str | None
    allowed_grains: tuple[str, ...]


@dataclass(frozen=True)
class PublishedRelationshipView:
    """Friendly relationship metadata without physical join keys."""

    identity: str
    left_source: str
    right_source: str


@dataclass(frozen=True)
class _PromotedValueBinding:
    identity: str
    friendly_name: str
    aliases: tuple[str, ...]
    kind: str
    data_type: str
    source_field: str | None
    source_fields: tuple[str, ...]
    composition: str | None
    formula: str | None
    expression: Mapping[str, Any] | None
    components: tuple[str, ...]
    eligibility_component: str | None
    rollup: str | None
    allowed_grains: tuple[str, ...]
    window_base: str | None
    window_partition: tuple[str, ...]
    window_eligibility: str | None
    public: bool


@dataclass(frozen=True)
class _RelationshipBinding:
    identity: str
    left_source: str
    right_source: str
    keys: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class _NamedRecipeBinding:
    identity: str
    source: str
    grain: str
    selections: tuple[str, ...]
    predicates: tuple[Mapping[str, Any], ...]
    ordering: tuple[Mapping[str, str], ...]
    eligibility: tuple[Mapping[str, Any], ...]


@dataclass(frozen=True)
class _GrainBinding:
    identity: str
    source: str
    dimensions: tuple[str, ...]


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
            ordinal=int(item["ordinal"]),
            duckdb_type=item["duckdb_type"],
            data_type=item["data_type"],
            operations=tuple(item["operations"]),
        )
        for item in payload["fields"]
    )
    if source is None:
        return fields
    return tuple(field for field in fields if field.source == source)


@lru_cache(maxsize=1)
def _promoted_payload() -> dict[str, Any]:
    catalog = _read_json("published_catalog.json")
    promoted_files = catalog.get("promoted", [])
    if not isinstance(promoted_files, list):
        raise ValueError("Published catalog promoted entries must be a list.")
    combined: dict[str, list[dict[str, Any]]] = {
        "grains": [],
        "values": [],
        "relationships": [],
        "recipes": [],
    }
    for filename in promoted_files:
        payload = _read_json(str(filename))
        for key in combined:
            combined[key].extend(payload.get(key, []))
    _validate_promoted_declarations(combined)
    return combined


def _validate_promoted_declarations(payload: dict[str, list[dict[str, Any]]]) -> None:
    values = payload["values"]
    identities = [str(item.get("identity")) for item in values]
    if len(identities) != len(set(identities)):
        raise ValueError("Promoted catalog contains duplicate value identities.")
    value_ids = set(identities)
    raw_ids = {field.identity for field in discover_fields()}
    grain_ids: set[str] = set()
    for grain in payload["grains"]:
        identity = str(grain["identity"])
        if identity in grain_ids:
            raise ValueError("Promoted catalog contains duplicate grain identities.")
        grain_ids.add(identity)
        if source_by_identity(str(grain["source"])) is None:
            raise ValueError(f"Grain {identity!r} references a stale source.")
        if not set(grain["dimensions"]) <= value_ids:
            raise ValueError(f"Grain {identity!r} references stale dimensions.")
    for item in values:
        identity = str(item["identity"])
        for field_identity in (
            *item.get("source_fields", []),
            *item.get("components", []),
        ):
            if field_identity not in raw_ids:
                raise ValueError(
                    f"Promoted value {identity!r} references stale field {field_identity!r}."
                )
        source_field = item.get("source_field")
        if source_field is not None and source_field not in raw_ids:
            raise ValueError(
                f"Promoted value {identity!r} references stale field {source_field!r}."
            )
        expression = item.get("expression")
        if expression is not None:
            field_refs, value_refs = _expression_references(expression)
            if not field_refs <= raw_ids or not value_refs <= value_ids:
                raise ValueError(f"Promoted calculation {identity!r} has stale references.")
        for reference in (
            item.get("window_base"),
            item.get("window_eligibility"),
            *item.get("window_partition", []),
        ):
            if reference is not None and reference not in value_ids:
                raise ValueError(
                    f"Promoted window value {identity!r} references stale value {reference!r}."
                )

    relationship_ids: set[str] = set()
    for relationship in payload["relationships"]:
        identity = str(relationship["identity"])
        if identity in relationship_ids:
            raise ValueError("Promoted catalog contains duplicate relationship identities.")
        relationship_ids.add(identity)
        for left, right in relationship["keys"]:
            if left not in raw_ids or right not in raw_ids:
                raise ValueError(f"Relationship {identity!r} references stale join keys.")

    recipe_ids: set[str] = set()
    for recipe in payload["recipes"]:
        identity = str(recipe["identity"])
        if identity in recipe_ids:
            raise ValueError("Promoted catalog contains duplicate recipe identities.")
        recipe_ids.add(identity)
        if recipe.get("grain") not in grain_ids:
            raise ValueError(f"Named recipe {identity!r} references a stale grain.")
        references = set(recipe.get("selections", []))
        references.update(
            str(predicate.get("value"))
            for predicate in recipe.get("predicates", [])
            if predicate.get("value") is not None
        )
        references.update(
            str(predicate.get("value_ref"))
            for predicate in recipe.get("predicates", [])
            if predicate.get("value_ref") is not None
        )
        references.update(str(spec.get("value")) for spec in recipe.get("ordering", []))
        references.update(str(rule.get("value")) for rule in recipe.get("eligibility", []))
        if not references <= value_ids:
            raise ValueError(f"Named recipe {identity!r} references stale values.")


def _expression_references(expression: object) -> tuple[set[str], set[str]]:
    if not isinstance(expression, dict):
        raise ValueError("Catalog calculation expressions must be objects.")
    fields = {str(expression["field"])} if "field" in expression else set()
    values = {str(expression["value"])} if "value" in expression else set()
    arguments = expression.get("args", [])
    if not isinstance(arguments, list):
        raise ValueError("Catalog calculation arguments must be a list.")
    for argument in arguments:
        child_fields, child_values = _expression_references(argument)
        fields.update(child_fields)
        values.update(child_values)
    return fields, values


@lru_cache(maxsize=1)
def _promoted_value_bindings() -> tuple[_PromotedValueBinding, ...]:
    return tuple(
        _PromotedValueBinding(
            identity=item["identity"],
            friendly_name=item["friendly_name"],
            aliases=tuple(item.get("aliases", [])),
            kind=item["kind"],
            data_type=item["data_type"],
            source_field=item.get("source_field"),
            source_fields=tuple(item.get("source_fields", [])),
            composition=item.get("composition"),
            formula=item.get("formula"),
            expression=(
                MappingProxyType(item["expression"]) if item.get("expression") is not None else None
            ),
            components=tuple(item.get("components", [])),
            eligibility_component=item.get("eligibility_component"),
            rollup=item.get("rollup"),
            allowed_grains=tuple(item.get("allowed_grains", [])),
            window_base=item.get("window_base"),
            window_partition=tuple(item.get("window_partition", [])),
            window_eligibility=item.get("window_eligibility"),
            public=bool(item.get("public", True)),
        )
        for item in _promoted_payload()["values"]
    )


@lru_cache(maxsize=1)
def _relationship_bindings() -> tuple[_RelationshipBinding, ...]:
    return tuple(
        _RelationshipBinding(
            identity=item["identity"],
            left_source=item["left_source"],
            right_source=item["right_source"],
            keys=tuple(tuple(pair) for pair in item["keys"]),
        )
        for item in _promoted_payload()["relationships"]
    )


@lru_cache(maxsize=1)
def _named_recipe_bindings() -> tuple[_NamedRecipeBinding, ...]:
    return tuple(
        _NamedRecipeBinding(
            identity=item["identity"],
            source=item["source"],
            grain=item["grain"],
            selections=tuple(item["selections"]),
            predicates=tuple(MappingProxyType(dict(predicate)) for predicate in item["predicates"]),
            ordering=tuple(MappingProxyType(dict(spec)) for spec in item.get("ordering", [])),
            eligibility=tuple(MappingProxyType(dict(rule)) for rule in item.get("eligibility", [])),
        )
        for item in _promoted_payload()["recipes"]
    )


@lru_cache(maxsize=1)
def _grain_bindings() -> tuple[_GrainBinding, ...]:
    return tuple(
        _GrainBinding(
            identity=item["identity"],
            source=item["source"],
            dimensions=tuple(item["dimensions"]),
        )
        for item in _promoted_payload()["grains"]
    )


@lru_cache(maxsize=1)
def published_values() -> tuple[PromotedValueView, ...]:
    return tuple(
        PromotedValueView(
            identity=value.identity,
            friendly_name=value.friendly_name,
            aliases=value.aliases,
            kind=value.kind,
            data_type=value.data_type,
            formula=value.formula,
            rollup=value.rollup,
            allowed_grains=value.allowed_grains,
        )
        for value in _promoted_value_bindings()
        if value.public
    )


@lru_cache(maxsize=1)
def published_relationships() -> tuple[PublishedRelationshipView, ...]:
    return tuple(
        PublishedRelationshipView(
            identity=relationship.identity,
            left_source=relationship.left_source,
            right_source=relationship.right_source,
        )
        for relationship in _relationship_bindings()
    )


def promoted_value_by_identity(identity: str) -> _PromotedValueBinding | None:
    return next(
        (value for value in _promoted_value_bindings() if value.identity == identity),
        None,
    )


def canonical_promoted_identity(reference: str) -> str | None:
    normalized = reference.strip().casefold()
    matches = {
        value.identity
        for value in _promoted_value_bindings()
        if normalized
        in {
            value.identity.casefold(),
            value.friendly_name.casefold(),
            *(alias.casefold() for alias in value.aliases),
        }
    }
    return next(iter(matches)) if len(matches) == 1 else None


def relationship_by_identity(identity: str) -> _RelationshipBinding | None:
    return next(
        (item for item in _relationship_bindings() if item.identity == identity),
        None,
    )


def named_recipe_by_identity(identity: str) -> _NamedRecipeBinding | None:
    return next(
        (item for item in _named_recipe_bindings() if item.identity == identity),
        None,
    )


def grain_by_identity(identity: str) -> _GrainBinding | None:
    return next((grain for grain in _grain_bindings() if grain.identity == identity), None)


@lru_cache(maxsize=1)
def catalog_revision() -> str:
    return str(_read_json("published_catalog.json")["catalog_revision"])


def source_by_identity(identity: str) -> _SourceBinding | None:
    return next((source for source in _source_bindings() if source.identity == identity), None)


def field_by_identity(identity: str) -> RawField | None:
    return next((field for field in discover_fields() if field.identity == identity), None)


def _read_json(filename: str) -> dict[str, Any]:
    return json.loads((CATALOG_DIR / filename).read_text(encoding="utf-8"))
