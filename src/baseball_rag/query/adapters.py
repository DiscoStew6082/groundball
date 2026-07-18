"""Rendering-neutral HTTP, CLI, browser, and export Adapter contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from baseball_rag.query.contracts import (
    All,
    Compare,
    ExecutionFailed,
    ExecutionUnavailable,
    Export,
    Exported,
    InteractivePage,
    NeedsClarification,
    NoData,
    Not,
    Predicate,
    QueryRecipe,
    RankSpec,
    Ready,
    Rejected,
    Rows,
    Scalar,
    SortSpec,
    ValueRef,
)
from baseball_rag.query.contracts import (
    Any as AnyPredicate,
)
from baseball_rag.query.coverage import verification_payload
from baseball_rag.query.recipe_adapter import interpret_recipe
from baseball_rag.query.registry import (
    catalog_revision,
    discover_fields,
    published_relationships,
    published_sources,
    published_values,
)
from baseball_rag.query.service import execute, prepare


def run_query_input(
    *,
    question: str | None = None,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve exactly one Adapter input into one discriminated query outcome."""
    if (question is None) == (recipe is None):
        raise ValueError("Provide exactly one natural-language question or structured recipe.")
    if question is not None:
        adapted = interpret_recipe(question)
        if isinstance(adapted, (NeedsClarification, Rejected)):
            return _planning_payload(adapted, recipe=None)
        resolved_recipe = adapted
    else:
        resolved_recipe = recipe_from_dict(cast(Mapping[str, Any], recipe))

    planned = prepare(resolved_recipe)
    if not isinstance(planned, Ready):
        return _planning_payload(planned, recipe=resolved_recipe)
    return _execution_payload(resolved_recipe, planned, execute(planned.plan))


def recipe_to_dict(recipe: QueryRecipe) -> dict[str, Any]:
    """Serialize the editable recipe using typed, non-executable JSON values."""
    return {
        "catalog_revision": recipe.catalog_revision,
        "grain": recipe.grain,
        "groupings": list(recipe.groupings),
        "ordering": [item.as_dict() for item in recipe.ordering],
        "output": recipe.output.as_dict(),
        "predicate": recipe.predicate.as_dict() if recipe.predicate else None,
        "ranking": recipe.ranking.as_dict() if recipe.ranking else None,
        "selections": list(recipe.selections),
        "source": recipe.source,
    }


def recipe_from_dict(payload: Mapping[str, Any]) -> QueryRecipe:
    """Parse a structured recipe without accepting SQL or expression fragments."""
    allowed = {
        "catalog_revision",
        "grain",
        "groupings",
        "ordering",
        "output",
        "predicate",
        "ranking",
        "selections",
        "source",
    }
    extras = set(payload) - allowed
    if extras:
        raise ValueError(f"Unknown Query Recipe fields: {', '.join(sorted(extras))}.")
    source = payload.get("source")
    selections = payload.get("selections")
    if (
        not isinstance(source, str)
        or not isinstance(selections, list)
        or not all(isinstance(item, str) for item in selections)
    ):
        raise ValueError("Query Recipe requires a source and string selections.")
    groupings = _string_list(payload.get("groupings", []), "groupings")
    ordering_payload = payload.get("ordering", [])
    if not isinstance(ordering_payload, list):
        raise ValueError("Query Recipe ordering must be a list.")
    ordering = tuple(_sort_from(item) for item in ordering_payload)
    ranking_payload = payload.get("ranking")
    ranking = None if ranking_payload is None else _rank_from(ranking_payload)
    predicate_payload = payload.get("predicate")
    predicate = None if predicate_payload is None else _predicate_from(predicate_payload)
    output_payload = payload.get("output", {"kind": "interactive_page", "size": 100, "offset": 0})
    return QueryRecipe(
        source=source,
        selections=tuple(selections),
        predicate=predicate,
        catalog_revision=_optional_string(payload.get("catalog_revision"), "catalog_revision"),
        grain=_string(payload.get("grain", "raw_rows"), "grain"),
        groupings=groupings,
        ranking=ranking,
        ordering=ordering,
        output=_output_from(output_payload),
    )


def catalog_payload(
    *,
    source: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return the catalog discovery read model used by every application Adapter."""
    needle = search.casefold().strip() if search else ""
    fields = [
        field
        for field in discover_fields(source=source)
        if _matches(needle, field.identity, field.column)
    ]
    if offset < 0 or limit is not None and limit <= 0:
        raise ValueError("Catalog offset must be nonnegative and limit must be positive.")
    field_total = len(fields)
    fields = fields[offset:] if limit is None else fields[offset : offset + limit]
    values = [
        value
        for value in published_values()
        if _matches(needle, value.identity, value.friendly_name, *value.aliases)
    ]
    return {
        "catalog_revision": catalog_revision(),
        "field_total": field_total,
        "field_offset": offset,
        "field_limit": limit,
        "sources": [
            {
                "identity": item.identity,
                "kind": item.kind,
                "reference_version": item.reference_version,
            }
            for item in published_sources()
        ],
        "fields": [
            {
                "identity": item.identity,
                "source": item.source,
                "column": item.column,
                "ordinal": item.ordinal,
                "duckdb_type": item.duckdb_type,
                "data_type": item.data_type,
                "operations": list(item.operations),
            }
            for item in fields
        ],
        "values": [
            {
                "identity": item.identity,
                "friendly_name": item.friendly_name,
                "aliases": list(item.aliases),
                "kind": item.kind,
                "data_type": item.data_type,
                "formula": item.formula,
                "rollup": item.rollup,
                "allowed_grains": list(item.allowed_grains),
                "null_policy": item.null_policy,
                "operations": list(item.operations),
                "explanation": item.explanation,
            }
            for item in values
        ],
        "relationships": [
            {
                "identity": item.identity,
                "left_source": item.left_source,
                "right_source": item.right_source,
            }
            for item in published_relationships()
        ],
    }


def _planning_payload(
    outcome: NeedsClarification | Rejected,
    *,
    recipe: QueryRecipe | None,
) -> dict[str, Any]:
    base = {"recipe": recipe_to_dict(recipe) if recipe else None, "plan": None}
    if isinstance(outcome, NeedsClarification):
        return {
            "kind": "needs_clarification",
            "question": outcome.question,
            "suggested_recipe": (
                recipe_to_dict(outcome.suggested_recipe_change)
                if outcome.suggested_recipe_change
                else None
            ),
            "choices": [
                {"label": choice.label, "recipe": recipe_to_dict(choice.recipe)}
                for choice in outcome.choices
            ],
            **base,
        }
    return {"kind": "rejected", "reason": outcome.reason, **base}


def _execution_payload(recipe: QueryRecipe, planned: Ready, outcome: object) -> dict[str, Any]:
    base = {"recipe": recipe_to_dict(recipe), "plan": planned.plan.as_dict()}
    if isinstance(outcome, ExecutionUnavailable):
        return {"kind": "unavailable", "reason": outcome.reason, **base}
    if isinstance(outcome, ExecutionFailed):
        return {"kind": "failed", "reason": outcome.reason, **base}
    if not isinstance(outcome, (Rows, NoData, Exported)):
        raise TypeError("Unknown Query Run outcome.")
    verification = verification_payload(outcome.evidence)
    if verification["status"] != "verified":
        return {
            **base,
            "kind": "unavailable",
            "reason": verification["reason"],
        }
    payload = {
        **base,
        "kind": (
            "exported"
            if isinstance(outcome, Exported)
            else "no_data"
            if isinstance(outcome, NoData)
            else "rows"
        ),
        "rows": [dict(row) for row in outcome.rows],
        "evidence": _evidence_payload(outcome.evidence),
        "verification": verification,
    }
    if isinstance(outcome, Exported):
        payload["export"] = {"format": outcome.format, "content": outcome.content}
    return payload


def _evidence_payload(evidence: Any) -> dict[str, Any]:
    return {
        "parameterized_sql": evidence.parameterized_sql,
        "bound_values": list(evidence.bound_values),
        "sources": [
            {
                "identity": item.identity,
                "kind": item.kind,
                "release": item.release,
                "expected_rows": item.expected_rows,
                "sha256": item.sha256,
                "row_fingerprint": item.row_fingerprint,
            }
            for item in evidence.sources
        ],
        "catalog_revision": evidence.catalog_revision,
        "data_release": evidence.data_release,
        "row_count": evidence.row_count,
        "matched_row_count": evidence.matched_row_count,
        "result_fingerprint": evidence.result_fingerprint,
        "calculations": [
            {"identity": item.identity, "formula": item.formula, "inputs": list(item.inputs)}
            for item in evidence.calculations
        ],
    }


def _predicate_from(payload: object) -> Predicate:
    if not isinstance(payload, Mapping):
        raise ValueError("Query Recipe predicate must be an object.")
    kind = payload.get("kind")
    if kind == "compare":
        _require_exact(payload, {"kind", "value", "operator", "literal"}, "predicate")
        return Compare(
            _string(payload.get("value"), "predicate value"),
            _string(payload.get("operator"), "predicate operator"),
            _literal_from(payload.get("literal")),
        )
    if kind in {"all", "any"}:
        _require_exact(payload, {"kind", "predicates"}, "predicate")
        children = payload.get("predicates")
        if not isinstance(children, list):
            raise ValueError("Compound predicates require a predicate list.")
        resolved = tuple(_predicate_from(item) for item in children)
        return All(resolved) if kind == "all" else AnyPredicate(resolved)
    if kind == "not":
        _require_exact(payload, {"kind", "predicate"}, "predicate")
        return Not(_predicate_from(payload.get("predicate")))
    raise ValueError("Query Recipe predicate kind is not published.")


def _literal_from(value: object) -> Scalar | tuple[Scalar, ...] | ValueRef:
    if isinstance(value, Mapping) and value.get("kind") == "value_ref":
        _require_exact(value, {"kind", "identity"}, "value reference")
        return ValueRef(_string(value.get("identity"), "value reference"))
    if isinstance(value, list):
        return tuple(_scalar(item) for item in value)
    return _scalar(value)


def _scalar(value: object) -> Scalar:
    if value is None or isinstance(value, (str, int, float, bool)):
        return cast(Scalar, value)
    raise ValueError("Query Recipe literals must be typed scalar values.")


def _rank_from(payload: object) -> RankSpec:
    if not isinstance(payload, Mapping):
        raise ValueError("Query Recipe ranking must be an object.")
    _require_exact(
        payload,
        {"value", "direction", "count", "tie_policy", "within"},
        "ranking",
    )
    count = payload.get("count")
    if not isinstance(count, int) or isinstance(count, bool):
        raise ValueError("Query Recipe rank count must be an integer.")
    return RankSpec(
        value=_string(payload.get("value"), "rank value"),
        direction=_string(payload.get("direction"), "rank direction"),
        count=count,
        tie_policy=_string(payload.get("tie_policy"), "rank tie policy"),
        within=_string_list(payload.get("within", []), "rank partitions"),
    )


def _sort_from(payload: object) -> SortSpec:
    if not isinstance(payload, Mapping):
        raise ValueError("Query Recipe sort must be an object.")
    _require_exact(payload, {"value", "direction", "nulls"}, "sort")
    return SortSpec(
        value=_string(payload.get("value"), "sort value"),
        direction=_string(payload.get("direction"), "sort direction"),
        nulls=_string(payload.get("nulls", "last"), "sort null placement"),
    )


def _output_from(payload: object) -> InteractivePage | Export:
    if not isinstance(payload, Mapping):
        raise ValueError("Query Recipe output must be an object.")
    kind = payload.get("kind")
    if kind == "interactive_page":
        _require_exact(payload, {"kind", "size", "offset"}, "output")
        size = payload.get("size", 100)
        offset = payload.get("offset", 0)
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or not isinstance(offset, int)
            or isinstance(offset, bool)
        ):
            raise ValueError("Interactive page size and offset must be integers.")
        return InteractivePage(size=size, offset=offset)
    if kind == "export":
        _require_exact(payload, {"kind", "format"}, "output")
        return Export(format=_string(payload.get("format", "json"), "export format"))
    raise ValueError("Query Recipe output kind is not published.")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Query Recipe {label} must be a string.")
    return value


def _optional_string(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _string(value, label)


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"Query Recipe {label} must be a string list.")
    return tuple(value)


def _matches(needle: str, *haystacks: str) -> bool:
    return not needle or any(needle in item.casefold() for item in haystacks)


def _require_exact(payload: Mapping[object, object], allowed: set[str], label: str) -> None:
    extras = {str(key) for key in payload if key not in allowed}
    if extras:
        raise ValueError(f"Unknown Query Recipe {label} fields: {', '.join(sorted(extras))}.")
