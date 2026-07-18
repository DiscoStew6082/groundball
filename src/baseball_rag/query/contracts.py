"""Public immutable contracts for catalog-driven Ground Ball queries."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, TypeAlias, cast

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
        return {"format": self.format, "full_match": True, "kind": "export"}


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
        payload = cast(dict[str, object], json.loads(serialized))
        ranking_payload = cast(dict[str, object] | None, payload["ranking"])
        ranking = None
        if ranking_payload is not None:
            ranking = RankSpec(
                value=str(ranking_payload["value"]),
                direction=str(ranking_payload["direction"]),
                count=int(cast(int, ranking_payload["count"])),
                tie_policy=str(ranking_payload["tie_policy"]),
                within=tuple(cast(list[str], ranking_payload["within"])),
            )
        ordering_payload = cast(list[dict[str, object]], payload["ordering"])
        ordering = tuple(
            SortSpec(
                value=str(item["value"]),
                direction=str(item["direction"]),
                nulls=str(item["nulls"]),
            )
            for item in ordering_payload
        )
        return cls(
            version=str(payload["version"]),
            catalog_revision=str(payload["catalog_revision"]),
            source=str(payload["source"]),
            grain=str(payload["grain"]),
            selections=tuple(cast(list[str], payload["selections"])),
            predicate=_predicate_from(payload["predicate"]),
            groupings=tuple(cast(list[str], payload.get("groupings", []))),
            relationships=tuple(cast(list[str], payload["relationships"])),
            ranking=ranking,
            ordering=ordering,
            output=_output_from(payload["output"]),
        )


@dataclass(frozen=True)
class Ready:
    plan: QueryPlanV1


@dataclass(frozen=True)
class NeedsClarification:
    question: str
    suggested_recipe_change: QueryRecipe | None = None


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
    payload = cast(dict[str, object], value)
    kind = payload.get("kind")
    if kind == "compare":
        return Compare(
            value=str(payload["value"]),
            operator=str(payload["operator"]),
            literal=_typed_literal(payload.get("literal")),
        )
    if kind in {"all", "any"}:
        children = tuple(
            cast(Predicate, _predicate_from(item))
            for item in cast(list[dict[str, object]], payload["predicates"])
        )
        return All(children) if kind == "all" else Any(children)
    if kind == "not":
        child = _predicate_from(payload["predicate"])
        if child is None:
            raise ValueError("Not predicate requires one child.")
        return Not(child)
    raise ValueError("Unsupported Query Plan predicate kind.")


def _output_from(value: object) -> OutputSpec:
    payload = cast(dict[str, object], value)
    kind = payload.get("kind")
    if kind == "interactive_page":
        return InteractivePage(
            size=int(cast(int, payload["size"])),
            offset=int(cast(int, payload["offset"])),
        )
    if kind == "export":
        return Export(format=str(payload["format"]))
    raise ValueError("Unsupported Query Plan output kind.")


def _typed_literal(value: object) -> Literal:
    if isinstance(value, list):
        return tuple(_typed_scalar(item) for item in value)
    if isinstance(value, dict) and value.get("kind") == "value_ref":
        return ValueRef(identity=str(value["identity"]))
    return _typed_scalar(value)


def _typed_scalar(value: object) -> Scalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return cast(Scalar, value)
    raise ValueError("Query Plan literals must be typed scalar values.")
