"""Public-only result and export policy over the local Query Adapter."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from baseball_rag.query.adapters import run_query_input
from baseball_rag.query.contracts import InteractivePage, QueryRecipe
from baseball_rag.query.recipe_adapter import interpret_recipe

PUBLIC_DEFAULT_PAGE_SIZE = 25
PUBLIC_PAGE_SIZES = frozenset({25, 50, 100})
EXPORT_ROW_MAX = 3_000
EXPORT_CONTENT_MAX_BYTES = 1_500_000
EXPORT_RESPONSE_MAX_BYTES = 3_500_000


def first_exceeded_export_ceiling(
    *,
    total_matched_count: int,
    content_bytes: int,
    response_bytes: int,
) -> dict[str, int | str] | None:
    """Return the first public export ceiling exceeded; exact boundaries are allowed."""
    if total_matched_count > EXPORT_ROW_MAX:
        return {
            "name": "matched_rows",
            "maximum": EXPORT_ROW_MAX,
            "observed": total_matched_count,
        }
    if content_bytes > EXPORT_CONTENT_MAX_BYTES:
        return {
            "name": "downloadable_bytes",
            "maximum": EXPORT_CONTENT_MAX_BYTES,
            "observed": content_bytes,
        }
    if response_bytes > EXPORT_RESPONSE_MAX_BYTES:
        return {
            "name": "complete_response_bytes",
            "maximum": EXPORT_RESPONSE_MAX_BYTES,
            "observed": response_bytes,
        }
    return None


def compact_json_bytes(payload: Mapping[str, Any]) -> bytes:
    """Encode the exact deterministic compact JSON used by public HTTP successes."""
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def export_measurements(payload: Mapping[str, Any]) -> dict[str, int]:
    """Measure an exported public envelope from its actual UTF-8 wire representation."""
    return {
        "total_matched_count": int(payload["evidence"]["matched_row_count"]),
        "content_bytes": len(payload["export"]["content"].encode("utf-8")),
        "response_bytes": len(compact_json_bytes(payload)),
    }


def run_public_query_input(
    *,
    question: str | None = None,
    recipe: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one query through public-only result policy without changing local behavior."""
    if (question is None) == (recipe is None):
        raise ValueError("Provide exactly one natural-language question or structured recipe.")
    if question is not None:
        adapted = interpret_recipe(question)
        if not isinstance(adapted, QueryRecipe):
            return _apply_public_planning_defaults(run_query_input(question=question))
        public_recipe = replace(
            adapted,
            output=InteractivePage(size=PUBLIC_DEFAULT_PAGE_SIZE, offset=0),
        )
        return _apply_public_result_policy(run_query_input(recipe=_recipe_mapping(public_recipe)))
    assert recipe is not None
    structured_recipe = _with_public_output_defaults(recipe)
    _validate_public_output(structured_recipe)
    return _apply_public_result_policy(run_query_input(recipe=structured_recipe))


def _apply_public_planning_defaults(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("kind") != "needs_clarification":
        return payload
    choices = [
        {**choice, "recipe": _with_public_default_page(choice["recipe"])}
        for choice in payload.get("choices", [])
    ]
    suggested = payload.get("suggested_recipe")
    return {
        **payload,
        "choices": choices,
        "suggested_recipe": _with_public_default_page(suggested) if suggested else None,
    }


def _with_public_default_page(recipe: Mapping[str, Any]) -> dict[str, Any]:
    return {
        **recipe,
        "output": {
            "kind": "interactive_page",
            "size": PUBLIC_DEFAULT_PAGE_SIZE,
            "offset": 0,
        },
    }


def _apply_public_result_policy(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("kind") == "exported":
        total = int(payload["evidence"]["matched_row_count"])
        exceeded = first_exceeded_export_ceiling(
            total_matched_count=total,
            content_bytes=0,
            response_bytes=0,
        )
        content_bytes = 0
        if exceeded is None:
            content_bytes = len(payload["export"]["content"].encode("utf-8"))
            exceeded = first_exceeded_export_ceiling(
                total_matched_count=total,
                content_bytes=content_bytes,
                response_bytes=0,
            )
        if exceeded is None:
            exceeded = first_exceeded_export_ceiling(
                total_matched_count=total,
                content_bytes=content_bytes,
                response_bytes=len(compact_json_bytes(payload)),
            )
        if exceeded is None:
            return payload
        labels = {
            "matched_rows": "matched rows",
            "downloadable_bytes": "downloadable bytes",
            "complete_response_bytes": "complete response bytes",
        }
        return {
            "kind": "export_too_large",
            "error": "export_too_large",
            "total_matched_count": total,
            "ceiling": exceeded,
            "detail": (
                f"The complete export exceeds the public {labels[str(exceeded['name'])]} ceiling."
            ),
            "guidance": "Add filters to narrow the result, then export again.",
        }
    if payload.get("kind") not in {"rows", "no_data"}:
        return payload
    output = payload["recipe"]["output"]
    if output.get("kind") != "interactive_page":
        return payload
    rows = payload["rows"]
    returned = len(rows)
    total = payload["evidence"]["matched_row_count"]
    size = output["size"]
    offset = output["offset"]
    return {
        **payload,
        "returned_row_count": returned,
        "total_matched_count": total,
        "pagination": {
            "size": size,
            "offset": offset,
            "has_more": offset + returned < total,
        },
    }


def _with_public_output_defaults(recipe: Mapping[str, Any]) -> dict[str, Any]:
    output = recipe.get("output")
    if output is None:
        return _with_public_default_page(recipe)
    if isinstance(output, Mapping) and output.get("kind") == "interactive_page":
        return {
            **recipe,
            "output": {
                **output,
                "size": output.get("size", PUBLIC_DEFAULT_PAGE_SIZE),
                "offset": output.get("offset", 0),
            },
        }
    return dict(recipe)


def _validate_public_output(recipe: Mapping[str, Any]) -> None:
    output = recipe.get("output")
    if not isinstance(output, Mapping) or output.get("kind") != "interactive_page":
        return
    size = output.get("size", PUBLIC_DEFAULT_PAGE_SIZE)
    offset = output.get("offset", 0)
    if (
        not isinstance(size, int)
        or isinstance(size, bool)
        or size not in PUBLIC_PAGE_SIZES
        or not isinstance(offset, int)
        or isinstance(offset, bool)
        or offset < 0
    ):
        raise ValueError(
            "Public interactive page size must be 25, 50, or 100 and offset must be "
            "a nonnegative integer."
        )


def _recipe_mapping(recipe: QueryRecipe) -> dict[str, Any]:
    from baseball_rag.query.adapters import recipe_to_dict

    return recipe_to_dict(recipe)
