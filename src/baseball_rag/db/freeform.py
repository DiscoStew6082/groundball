"""Compatibility facade for natural language -> SQL freeform queries."""

import duckdb

from baseball_rag.db.freeform_intent import (
    _generate_query_spec as _generate_query_spec_impl,
)
from baseball_rag.db.freeform_intent import (
    _generate_sql as _generate_sql_impl,
)
from baseball_rag.db.freeform_runtime import (
    _execute_safe,
    _validate_sql,
    can_plan_deterministically,
    execute_plan,
    format_result,
    should_route_deterministic_freeform,
)
from baseball_rag.db.freeform_runtime import (
    plan_query as _plan_query_impl,
)
from baseball_rag.db.freeform_runtime import (
    query as _query_impl,
)
from baseball_rag.db.freeform_schema import _get_schema_cached
from baseball_rag.db.freeform_templates import (
    _career_era_sql,
    _career_home_run_sql,
    _career_pitching_wins_sql,
    _detect_template,
    _extract_explicit_wins_threshold,
    _extract_min_ipouts,
    _extract_threshold,
    _extract_year,
    _has_era_qualification_guard,
    _looks_like_single_season,
    _normalize_question,
    _qualified_season_era_sql,
    _template_source_detail,
    _thirty_thirty_sql,
    _triple_crown_sql,
    _unsupported_sql,
)
from baseball_rag.db.freeform_types import (
    MAX_ROWS,
    SCHEMA_TIMEOUT_MS,
    AssembledSQL,
    FreeformResult,
    PlannedFreeformQuery,
    QueryIntent,
    QuerySpec,
    TeamIdentity,
)
from baseball_rag.generation.llm import make_request

__all__ = [
    "MAX_ROWS",
    "SCHEMA_TIMEOUT_MS",
    "AssembledSQL",
    "FreeformResult",
    "PlannedFreeformQuery",
    "QueryIntent",
    "QuerySpec",
    "TeamIdentity",
    "can_plan_deterministically",
    "should_route_deterministic_freeform",
    "execute_plan",
    "format_result",
    "make_request",
    "plan_query",
    "query",
    "_career_era_sql",
    "_career_home_run_sql",
    "_career_pitching_wins_sql",
    "_detect_template",
    "_execute_safe",
    "_extract_explicit_wins_threshold",
    "_extract_min_ipouts",
    "_extract_threshold",
    "_extract_year",
    "_generate_query_spec",
    "_generate_sql",
    "_get_schema_cached",
    "_has_era_qualification_guard",
    "_looks_like_single_season",
    "_normalize_question",
    "_qualified_season_era_sql",
    "_template_source_detail",
    "_thirty_thirty_sql",
    "_triple_crown_sql",
    "_unsupported_sql",
    "_validate_sql",
]


def query(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    year: int | None = None,
) -> FreeformResult:
    """Convert a natural language question to SQL and execute it."""
    return _query_impl(question, conn, year=year, request_fn=make_request)


def plan_query(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    year: int | None = None,
) -> PlannedFreeformQuery:
    """Compatibility wrapper that honors patches to freeform.make_request."""
    return _plan_query_impl(question, conn, year=year, request_fn=make_request)


def _generate_sql(question: str, schema: str) -> str:
    """Compatibility wrapper that honors patches to freeform.make_request."""
    return _generate_sql_impl(question, schema, request_fn=make_request)


def _generate_query_spec(question: str, schema: str) -> QuerySpec:
    """Compatibility wrapper that honors patches to freeform.make_request."""
    return _generate_query_spec_impl(question, schema, request_fn=make_request)
