"""Public immutable contracts for catalog-driven Ground Ball queries."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias

Scalar: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class ValueRef:
    """A compatible catalog value used as the right side of a comparison."""

    identity: str

    def as_dict(self) -> dict[str, str]:
        return {"identity": self.identity, "kind": "value_ref"}


Literal: TypeAlias = Scalar | tuple[Scalar, ...] | ValueRef


@dataclass(frozen=True)
class Compare:
    """A catalog-capped comparison in a Query Recipe or Query Plan."""

    value: str
    operator: str
    literal: Literal

    def __post_init__(self) -> None:
        literals = self.literal if isinstance(self.literal, tuple) else (self.literal,)
        if any(isinstance(value, float) and not math.isfinite(value) for value in literals):
            raise ValueError("Query comparison numeric literals must be finite.")

    def as_dict(self) -> dict[str, object]:
        if isinstance(self.literal, tuple):
            literal: object = list(self.literal)
        elif isinstance(self.literal, ValueRef):
            literal = self.literal.as_dict()
        else:
            literal = self.literal
        return {
            "kind": "compare",
            "literal": literal,
            "operator": self.operator,
            "value": self.value,
        }


@dataclass(frozen=True)
class All:
    predicates: tuple[Predicate, ...]

    def as_dict(self) -> dict[str, object]:
        return {"kind": "all", "predicates": [item.as_dict() for item in self.predicates]}


@dataclass(frozen=True)
class Any:
    predicates: tuple[Predicate, ...]

    def as_dict(self) -> dict[str, object]:
        return {"kind": "any", "predicates": [item.as_dict() for item in self.predicates]}


@dataclass(frozen=True)
class Not:
    predicate: Predicate

    def as_dict(self) -> dict[str, object]:
        return {"kind": "not", "predicate": self.predicate.as_dict()}


Predicate: TypeAlias = Compare | All | Any | Not


@dataclass(frozen=True)
class RankSpec:
    value: str
    direction: str
    count: int
    tie_policy: str
    within: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "direction": self.direction,
            "tie_policy": self.tie_policy,
            "value": self.value,
            "within": list(self.within),
        }


@dataclass(frozen=True)
class SortSpec:
    value: str
    direction: str
    nulls: str = "last"

    def as_dict(self) -> dict[str, object]:
        return {
            "direction": self.direction,
            "nulls": self.nulls,
            "value": self.value,
        }


@dataclass(frozen=True)
class InteractivePage:
    size: int = 100
    offset: int = 0

    def as_dict(self) -> dict[str, object]:
        return {"kind": "interactive_page", "offset": self.offset, "size": self.size}


@dataclass(frozen=True)
class Export:
    format: str = "json"

    def as_dict(self) -> dict[str, object]:
        return {"format": self.format, "kind": "export"}


OutputSpec: TypeAlias = InteractivePage | Export


@dataclass(frozen=True)
class QueryRecipe:
    """The editable user expression shared by every query Adapter."""

    source: str
    selections: tuple[str, ...]
    predicate: Predicate | None = None
    catalog_revision: str | None = None
    grain: str = "raw_rows"
    groupings: tuple[str, ...] = ()
    ranking: RankSpec | None = None
    ordering: tuple[SortSpec, ...] = ()
    output: OutputSpec = field(default_factory=InteractivePage)


@dataclass(frozen=True)
class QueryPlanV1:
    """Closed, executable, canonically serializable query meaning."""

    version: str
    catalog_revision: str
    source: str
    grain: str
    selections: tuple[str, ...]
    predicate: Predicate | None
    groupings: tuple[str, ...] = ()
    relationships: tuple[str, ...] = ()
    ranking: RankSpec | None = None
    ordering: tuple[SortSpec, ...] = ()
    output: OutputSpec = field(default_factory=InteractivePage)

    def as_dict(self) -> dict[str, object]:
        return {
            "catalog_revision": self.catalog_revision,
            "grain": self.grain,
            "groupings": list(self.groupings),
            "ordering": [item.as_dict() for item in self.ordering],
            "output": self.output.as_dict(),
            "predicate": self.predicate.as_dict() if self.predicate else None,
            "ranking": self.ranking.as_dict() if self.ranking else None,
            "relationships": list(self.relationships),
            "selections": list(self.selections),
            "source": self.source,
            "version": self.version,
        }

    def to_json(self) -> str:
        return json.dumps(
            self.as_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, serialized: str) -> QueryPlanV1:
        """Restore a canonical plan without accepting executable expressions."""
        try:
            decoded = json.loads(
                serialized,
                parse_constant=lambda value: (_ for _ in ()).throw(
                    ValueError(f"Non-finite JSON number {value!r} is not allowed.")
                ),
            )
        except json.JSONDecodeError as exc:
            raise ValueError("Query Plan JSON is malformed.") from exc
        payload = _object(decoded, "Query Plan")
        _exact_keys(
            payload,
            {
                "version",
                "catalog_revision",
                "source",
                "grain",
                "selections",
                "predicate",
                "groupings",
                "relationships",
                "ranking",
                "ordering",
                "output",
            },
            "Query Plan",
        )
        ranking_payload = payload["ranking"]
        ranking = None
        if ranking_payload is not None:
            ranking_object = _object(ranking_payload, "ranking")
            _exact_keys(
                ranking_object,
                {"value", "direction", "count", "tie_policy", "within"},
                "ranking",
            )
            ranking = RankSpec(
                value=_string(ranking_object["value"], "ranking value"),
                direction=_string(ranking_object["direction"], "ranking direction"),
                count=_integer(ranking_object["count"], "ranking count"),
                tie_policy=_string(ranking_object["tie_policy"], "ranking tie policy"),
                within=_string_tuple(ranking_object["within"], "ranking partitions"),
            )
        ordering_payload = payload["ordering"]
        if not isinstance(ordering_payload, list):
            raise ValueError("Query Plan ordering must be a list.")
        ordering_items = []
        for item in ordering_payload:
            sort = _object(item, "sort")
            _exact_keys(sort, {"value", "direction", "nulls"}, "sort")
            ordering_items.append(
                SortSpec(
                    value=_string(sort["value"], "sort value"),
                    direction=_string(sort["direction"], "sort direction"),
                    nulls=_string(sort["nulls"], "sort null placement"),
                )
            )
        return cls(
            version=_string(payload["version"], "version"),
            catalog_revision=_string(payload["catalog_revision"], "catalog revision"),
            source=_string(payload["source"], "source"),
            grain=_string(payload["grain"], "grain"),
            selections=_string_tuple(payload["selections"], "selections"),
            predicate=_predicate_from(payload["predicate"]),
            groupings=_string_tuple(payload["groupings"], "groupings"),
            relationships=_string_tuple(payload["relationships"], "relationships"),
            ranking=ranking,
            ordering=tuple(ordering_items),
            output=_output_from(payload["output"]),
        )


@dataclass(frozen=True)
class Ready:
    plan: QueryPlanV1


@dataclass(frozen=True)
class ClarificationChoice:
    label: str
    recipe: QueryRecipe


@dataclass(frozen=True)
class NeedsClarification:
    question: str
    suggested_recipe_change: QueryRecipe | None = None
    choices: tuple[ClarificationChoice, ...] = ()


@dataclass(frozen=True)
class Rejected:
    reason: str


PlanningOutcome: TypeAlias = Ready | NeedsClarification | Rejected


@dataclass(frozen=True)
class SourceEvidence:
    identity: str
    kind: str
    release: str
    expected_rows: int | None
    sha256: str | None
    row_fingerprint: str


@dataclass(frozen=True)
class CalculationEvidence:
    identity: str
    formula: str
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class QueryEvidence:
    parameterized_sql: str
    bound_values: tuple[Scalar, ...]
    sources: tuple[SourceEvidence, ...]
    catalog_revision: str
    data_release: str
    row_count: int
    matched_row_count: int
    result_fingerprint: str
    calculations: tuple[CalculationEvidence, ...] = ()


@dataclass(frozen=True)
class QueryRun:
    plan: QueryPlanV1
    rows: tuple[Mapping[str, Scalar], ...]
    evidence: QueryEvidence

    def __post_init__(self) -> None:
        immutable_rows = tuple(MappingProxyType(dict(row)) for row in self.rows)
        object.__setattr__(self, "rows", immutable_rows)


@dataclass(frozen=True)
class Rows(QueryRun):
    pass


@dataclass(frozen=True)
class Exported(QueryRun):
    format: str
    content: str


@dataclass(frozen=True)
class NoData(QueryRun):
    pass


@dataclass(frozen=True)
class ExecutionUnavailable:
    reason: str


@dataclass(frozen=True)
class ExecutionFailed:
    reason: str


ExecutionOutcome: TypeAlias = Rows | Exported | NoData | ExecutionUnavailable | ExecutionFailed


def _predicate_from(value: object) -> Predicate | None:
    if value is None:
        return None
    payload = _object(value, "predicate")
    kind = payload.get("kind")
    if kind == "compare":
        _exact_keys(payload, {"kind", "value", "operator", "literal"}, "predicate")
        return Compare(
            value=_string(payload["value"], "predicate value"),
            operator=_string(payload["operator"], "predicate operator"),
            literal=_typed_literal(payload.get("literal")),
        )
    if kind in {"all", "any"}:
        _exact_keys(payload, {"kind", "predicates"}, "predicate")
        children_payload = payload["predicates"]
        if not isinstance(children_payload, list):
            raise ValueError("Compound Query Plan predicates require a list.")
        children = tuple(
            child for item in children_payload if (child := _predicate_from(item)) is not None
        )
        if len(children) != len(children_payload):
            raise ValueError("Compound Query Plan predicates cannot contain null children.")
        return All(children) if kind == "all" else Any(children)
    if kind == "not":
        _exact_keys(payload, {"kind", "predicate"}, "predicate")
        child = _predicate_from(payload["predicate"])
        if child is None:
            raise ValueError("Not predicate requires one child.")
        return Not(child)
    raise ValueError("Unsupported Query Plan predicate kind.")


def _output_from(value: object) -> OutputSpec:
    payload = _object(value, "output")
    kind = payload.get("kind")
    if kind == "interactive_page":
        _exact_keys(payload, {"kind", "size", "offset"}, "output")
        return InteractivePage(
            size=_integer(payload["size"], "interactive page size"),
            offset=_integer(payload["offset"], "interactive page offset"),
        )
    if kind == "export":
        _exact_keys(payload, {"kind", "format"}, "output")
        return Export(format=_string(payload["format"], "export format"))
    raise ValueError("Unsupported Query Plan output kind.")


def _typed_literal(value: object) -> Literal:
    if isinstance(value, list):
        return tuple(_typed_scalar(item) for item in value)
    if isinstance(value, dict) and value.get("kind") == "value_ref":
        _exact_keys(value, {"kind", "identity"}, "value reference")
        return ValueRef(identity=_string(value["identity"], "value reference identity"))
    return _typed_scalar(value)


def _typed_scalar(value: object) -> Scalar:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Query Plan numeric literals must be finite.")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError("Query Plan literals must be typed scalar values.")


def _object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object with string keys.")
    return value


def _exact_keys(payload: Mapping[str, object], expected: set[str], label: str) -> None:
    unknown = set(payload) - expected
    missing = expected - set(payload)
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(sorted(unknown))}.")
    if missing:
        raise ValueError(f"{label} is missing fields: {', '.join(sorted(missing))}.")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Query Plan {label} must be a string.")
    return value


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Query Plan {label} must be an integer.")
    return value


def _string_tuple(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Query Plan {label} must be a string list.")
    return tuple(value)
