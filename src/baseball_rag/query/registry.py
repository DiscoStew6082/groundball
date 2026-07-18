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
    null_policy: str | None


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
    source_bindings: Mapping[str, str]
    source_fields: tuple[str, ...]
    match_fields: tuple[str, ...]
    match_composition: str | None
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
    null_policy: str | None


@dataclass(frozen=True)
class _RelationshipBinding:
    identity: str
    left_source: str
    right_source: str
    keys: tuple[tuple[str, str], ...]
    cardinality: str


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
    sources: tuple[str, ...]
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class _CombinationBinding:
    identity: str
    sources: tuple[str, ...]
    grains: tuple[str, ...]


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
    combined: dict[str, list[Any]] = {
        "grains": [],
        "values": [],
        "relationships": [],
        "recipes": [],
        "groupings": [],
        "combinations": [],
    }
    for filename in promoted_files:
        payload = _read_json(str(filename))
        for key in combined:
            declarations = payload.get(key, [])
            if key == "values":
                default_rollups = payload.get("default_rollups", {})
                default_allowed_grains = payload.get("default_allowed_grains", {})
                default_null_policies = payload.get("default_null_policies", {})
                declarations = [
                    {
                        **item,
                        **(
                            {"rollup": default_rollups[item["kind"]]}
                            if "rollup" not in item and item["kind"] in default_rollups
                            else {}
                        ),
                        **(
                            {"null_policy": default_null_policies[item["kind"]]}
                            if "null_policy" not in item and item["kind"] in default_null_policies
                            else {}
                        ),
                        **(
                            {
                                "allowed_grains": list(
                                    dict.fromkeys(
                                        [
                                            *default_allowed_grains[item["kind"]],
                                            *item.get("allowed_grains", []),
                                        ]
                                    )
                                )
                            }
                            if item["kind"] in default_allowed_grains
                            else {}
                        ),
                    }
                    for item in declarations
                ]
            combined[key].extend(declarations)
    _validate_promoted_declarations(combined)
    return combined


def _validate_promoted_declarations(payload: dict[str, list[Any]]) -> None:
    values = payload["values"]
    identities = [str(item.get("identity")) for item in values]
    if len(identities) != len(set(identities)):
        raise ValueError("Promoted catalog contains duplicate value identities.")
    value_ids = set(identities)
    groupings = {str(identity) for identity in payload["groupings"]}
    if len(groupings) != len(payload["groupings"]) or not groupings <= value_ids:
        raise ValueError("Promoted catalog contains stale or duplicate groupings.")
    raw_ids = {field.identity for field in discover_fields()}
    grain_ids: set[str] = set()
    for grain in payload["grains"]:
        identity = str(grain["identity"])
        if identity in grain_ids:
            raise ValueError("Promoted catalog contains duplicate grain identities.")
        grain_ids.add(identity)
        sources = grain.get("sources", [])
        if not sources or any(source_by_identity(str(source)) is None for source in sources):
            raise ValueError(f"Grain {identity!r} references a stale source.")
        if not set(grain["dimensions"]) <= value_ids:
            raise ValueError(f"Grain {identity!r} references stale dimensions.")
    for item in values:
        identity = str(item["identity"])
        if not set(item.get("allowed_grains", [])) <= grain_ids:
            raise ValueError(f"Promoted value {identity!r} references a stale grain.")
        kind = item.get("kind")
        rollup = item.get("rollup")
        valid_rollup = {
            "dimension": None,
            "fact": "not_aggregatable",
            "count": "additive",
            "component": "additive",
            "calculation": "recompute",
            "window": None,
        }.get(str(kind), "invalid")
        if rollup != valid_rollup:
            raise ValueError(f"Promoted value {identity!r} has an invalid kind and rollup pairing.")
        null_policy = item.get("null_policy")
        expected_null_policy = (
            "preserve_unknown" if kind in {"count", "component", "calculation"} else None
        )
        if null_policy != expected_null_policy:
            raise ValueError(f"Promoted value {identity!r} has an invalid null policy.")
        for field_identity in (
            *item.get("source_fields", []),
            *item.get("match_fields", []),
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
        source_bindings = item.get("source_bindings", {})
        if not isinstance(source_bindings, dict) or any(
            source_by_identity(str(source)) is None
            or field not in raw_ids
            or (binding := field_by_identity(str(field))) is None
            or binding.source != source
            for source, field in source_bindings.items()
        ):
            raise ValueError(f"Promoted value {identity!r} has stale source bindings.")
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

    values_by_identity = {str(item["identity"]): item for item in values}
    for grain in payload["grains"]:
        for source in grain["sources"]:
            for dimension_identity in grain["dimensions"]:
                dimension = values_by_identity[dimension_identity]
                direct_field = dimension.get("source_bindings", {}).get(source)
                if direct_field is None:
                    direct_field = dimension.get("source_field")
                field = field_by_identity(str(direct_field)) if direct_field is not None else None
                if field is None or field.source != source:
                    raise ValueError(
                        f"Grain {grain['identity']!r} has no direct {source} binding for "
                        f"dimension {dimension_identity!r}."
                    )

    relationship_ids: set[str] = set()
    for relationship in payload["relationships"]:
        identity = str(relationship["identity"])
        if identity in relationship_ids:
            raise ValueError("Promoted catalog contains duplicate relationship identities.")
        relationship_ids.add(identity)
        cardinality = relationship.get("cardinality")
        if cardinality not in {"left_one_to_right_many", "right_one_to_left_many"}:
            raise ValueError(f"Relationship {identity!r} has no safe cardinality.")
        for left, right in relationship["keys"]:
            left_field = field_by_identity(left)
            right_field = field_by_identity(right)
            if (
                left not in raw_ids
                or right not in raw_ids
                or left_field is None
                or right_field is None
                or left_field.source != relationship["left_source"]
                or right_field.source != relationship["right_source"]
            ):
                raise ValueError(f"Relationship {identity!r} references stale join keys.")

    combination_ids: set[str] = set()
    for combination in payload["combinations"]:
        identity = str(combination["identity"])
        if identity in combination_ids:
            raise ValueError("Promoted catalog contains duplicate combinations.")
        combination_ids.add(identity)
        if (
            len(combination["sources"]) < 2
            or any(source_by_identity(source) is None for source in combination["sources"])
            or not set(combination["grains"]) <= grain_ids
        ):
            raise ValueError(f"Combination {identity!r} has stale declarations.")

    recipe_ids: set[str] = set()
    for recipe in payload["recipes"]:
        identity = str(recipe["identity"])
        if identity in recipe_ids:
            raise ValueError("Promoted catalog contains duplicate recipe identities.")
        recipe_ids.add(identity)
        if recipe.get("grain") not in grain_ids:
            raise ValueError(f"Named recipe {identity!r} references a stale grain.")
        grain = next(item for item in payload["grains"] if item["identity"] == recipe["grain"])
        if recipe.get("source") not in grain["sources"]:
            raise ValueError(f"Named recipe {identity!r} uses an incompatible source.")
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
            source_bindings=MappingProxyType(dict(item.get("source_bindings", {}))),
            source_fields=tuple(item.get("source_fields", [])),
            match_fields=tuple(item.get("match_fields", [])),
            match_composition=item.get("match_composition"),
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
            null_policy=item.get("null_policy"),
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
            cardinality=item["cardinality"],
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
            sources=tuple(item["sources"]),
            dimensions=tuple(item["dimensions"]),
        )
        for item in _promoted_payload()["grains"]
    )


@lru_cache(maxsize=1)
def _combination_bindings() -> tuple[_CombinationBinding, ...]:
    return tuple(
        _CombinationBinding(
            identity=item["identity"],
            sources=tuple(item["sources"]),
            grains=tuple(item["grains"]),
        )
        for item in _promoted_payload()["combinations"]
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
            null_policy=value.null_policy,
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


def canonical_promoted_identity(reference: str, *, source: str | None = None) -> str | None:
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
    if len(matches) == 1:
        return next(iter(matches))
    if source is None:
        return None
    direct_matches = {
        identity
        for identity in matches
        if (value := promoted_value_by_identity(identity)) is not None
        and _value_is_directly_owned_by(value, source)
    }
    return next(iter(direct_matches)) if len(direct_matches) == 1 else None


def _value_is_directly_owned_by(value: _PromotedValueBinding, source: str) -> bool:
    if source in value.source_bindings:
        return True
    references = (
        *((value.source_field,) if value.source_field is not None else ()),
        *value.source_fields,
        *value.components,
    )
    return any(
        (field := field_by_identity(identity)) is not None and field.source == source
        for identity in references
    )


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


def is_promoted_grouping(identity: str) -> bool:
    return identity in {str(item) for item in _promoted_payload()["groupings"]}


def combination_by_identity(identity: str) -> _CombinationBinding | None:
    return next((item for item in _combination_bindings() if item.identity == identity), None)


def combination_for(sources: set[str], grain: str) -> _CombinationBinding | None:
    return next(
        (
            item
            for item in _combination_bindings()
            if sources <= set(item.sources) and grain in item.grains
        ),
        None,
    )


def direct_value_sources(identity: str) -> set[str]:
    value = promoted_value_by_identity(identity)
    if value is None:
        return set()
    sources = set(value.source_bindings)
    for field_identity in (
        *((value.source_field,) if value.source_field is not None else ()),
        *value.source_fields,
        *value.components,
    ):
        field = field_by_identity(field_identity)
        if field is not None:
            sources.add(field.source)
    return sources


@lru_cache(maxsize=1)
def catalog_revision() -> str:
    return str(_read_json("published_catalog.json")["catalog_revision"])


def source_by_identity(identity: str) -> _SourceBinding | None:
    return next((source for source in _source_bindings() if source.identity == identity), None)


def field_by_identity(identity: str) -> RawField | None:
    return next((field for field in discover_fields() if field.identity == identity), None)


def _read_json(filename: str) -> dict[str, Any]:
    return json.loads((CATALOG_DIR / filename).read_text(encoding="utf-8"))
