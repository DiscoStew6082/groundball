"""Public immutable contracts for catalog-driven Ground Ball queries."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, TypeAlias, cast

Scalar: TypeAlias = str | int | float | bool | None


@dataclass(frozen=True)
class Compare:
    """A catalog-capped comparison in a Query Recipe or Query Plan."""

    value: str
    operator: str
    literal: Scalar

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": "compare",
            "literal": self.literal,
            "operator": self.operator,
            "value": self.value,
        }


@dataclass(frozen=True)
class QueryRecipe:
    """The editable user expression shared by every query Adapter."""

    source: str
    selections: tuple[str, ...]
    predicate: Compare | None = None
    catalog_revision: str | None = None
    grain: str = "raw_rows"


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
class QueryPlanV1:
    """Closed, executable, canonically serializable query meaning."""

    version: str
    catalog_revision: str
    source: str
    grain: str
    selections: tuple[str, ...]
    predicate: Compare | None
    relationships: tuple[str, ...] = ()
    ranking: RankSpec | None = None
    ordering: tuple[SortSpec, ...] = ()
    output: str = "interactive_page"

    def as_dict(self) -> dict[str, object]:
        return {
            "catalog_revision": self.catalog_revision,
            "grain": self.grain,
            "ordering": [item.as_dict() for item in self.ordering],
            "output": self.output,
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
        predicate_payload = cast(dict[str, object] | None, payload["predicate"])
        predicate = None
        if predicate_payload is not None:
            if predicate_payload.get("kind") != "compare":
                raise ValueError("Unsupported Query Plan predicate kind.")
            predicate = Compare(
                value=str(predicate_payload["value"]),
                operator=str(predicate_payload["operator"]),
                literal=_typed_scalar(predicate_payload.get("literal")),
            )
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
            predicate=predicate,
            relationships=tuple(cast(list[str], payload["relationships"])),
            ranking=ranking,
            ordering=ordering,
            output=str(payload["output"]),
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


@dataclass(frozen=True)
class QueryEvidence:
    parameterized_sql: str
    bound_values: tuple[Scalar, ...]
    sources: tuple[SourceEvidence, ...]
    catalog_revision: str
    data_release: str
    row_count: int
    result_fingerprint: str


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
class NoData(QueryRun):
    pass


@dataclass(frozen=True)
class ExecutionUnavailable:
    reason: str


@dataclass(frozen=True)
class ExecutionFailed:
    reason: str


ExecutionOutcome: TypeAlias = Rows | NoData | ExecutionUnavailable | ExecutionFailed


def _typed_scalar(value: object) -> Scalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return cast(Scalar, value)
    raise ValueError("Query Plan literals must be typed scalar values.")
