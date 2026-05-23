"""Planning policy for grounded database questions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import duckdb

from baseball_rag.db.grounded_database_assembler import _assemble_sql
from baseball_rag.db.grounded_database_intent import _generate_query_spec
from baseball_rag.db.grounded_database_schema import _get_schema_cached
from baseball_rag.db.grounded_database_templates import (
    can_plan_deterministically as _templates_can_plan_deterministically,
)
from baseball_rag.db.grounded_database_templates import match_template
from baseball_rag.db.grounded_database_templates import (
    should_route_deterministic_grounded_database as _templates_should_route,
)
from baseball_rag.db.grounded_database_types import GroundedDatabaseQueryPlan
from baseball_rag.db.team_history import get_contextual_hint, resolve_team_identity
from baseball_rag.generation.llm import make_request as default_make_request

RequestFn = Callable[..., Any]


def can_plan_deterministically(question: str) -> bool:
    """Return whether planning can bypass LLM-backed extraction for this question."""
    return _templates_can_plan_deterministically(question)


def should_route_deterministic_grounded_database(
    question: str,
    *,
    competing_stat: str | None = None,
) -> bool:
    """Return whether deterministic grounded database planning should win route ownership."""
    return _templates_should_route(
        question,
        competing_stat=competing_stat,
    )


def plan_grounded_database_query(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    year: int | None = None,
    request_fn: RequestFn = default_make_request,
) -> GroundedDatabaseQueryPlan:
    """Plan a natural-language database question as constrained SQL."""
    hint = get_contextual_hint(question, year)
    enriched_question = f"{question} {hint}".strip() if hint else question

    matched_template = match_template(enriched_question)
    if matched_template is not None:
        return GroundedDatabaseQueryPlan(
            assembled=matched_template.assembled,
            planning_path="deterministic_template",
            source_label="Deterministic template query",
            source_detail=matched_template.source_detail,
            query_spec=matched_template.query_spec,
        )

    schema = _get_schema_cached(conn)
    spec = _generate_query_spec(enriched_question, schema, request_fn=request_fn)
    if spec.year_value is None and year is not None:
        spec = replace(spec, year_value=year)
    team_identity = resolve_team_identity(
        question,
        team_name_pattern=spec.team_name_pattern,
        year=spec.year_value,
    )
    if team_identity is not None:
        spec = replace(spec, team_identity=team_identity)
    assembled = _assemble_sql(spec)
    return GroundedDatabaseQueryPlan(
        assembled=assembled,
        planning_path="llm_intent",
        source_label="LLM-backed typed grounded database query",
        source_detail=(
            "LLM extracted a typed intent; Python assembled constrained SQL deterministically."
        ),
        query_spec=spec,
    )
