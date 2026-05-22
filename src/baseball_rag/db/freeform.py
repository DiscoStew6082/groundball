"""Compatibility facade for natural language -> SQL freeform queries."""

import duckdb

from baseball_rag.db.freeform_runtime import (
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
