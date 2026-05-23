"""Runtime validation, execution, and formatting for grounded database questions."""

import re
from collections.abc import Callable
from typing import Any

import duckdb

from baseball_rag.db.grounded_database_planner import (
    can_plan_deterministically as _planner_can_plan_deterministically,
)
from baseball_rag.db.grounded_database_planner import plan_grounded_database_query
from baseball_rag.db.grounded_database_planner import (
    should_route_deterministic_grounded_database as _planner_should_route,
)
from baseball_rag.db.grounded_database_types import (
    MAX_ROWS,
    SCHEMA_TIMEOUT_MS,
    GroundedDatabaseQueryPlan,
    GroundedDatabaseResult,
)
from baseball_rag.generation.llm import make_request as default_make_request

RequestFn = Callable[..., Any]


def can_plan_deterministically(question: str) -> bool:
    """Return whether planning can bypass LLM-backed extraction for this question."""
    return _planner_can_plan_deterministically(question)


def should_route_deterministic_grounded_database(
    question: str,
    *,
    competing_stat: str | None = None,
) -> bool:
    """Return whether deterministic grounded database planning should win over a competing route."""
    return _planner_should_route(
        question,
        competing_stat=competing_stat,
    )


def query(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    year: int | None = None,
    request_fn: RequestFn = default_make_request,
) -> GroundedDatabaseResult:
    """Convert a natural language question to SQL and execute it."""
    planned = plan_query(question, conn, year=year, request_fn=request_fn)
    return execute_plan(planned, conn)


def plan_query(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    year: int | None = None,
    request_fn: RequestFn = default_make_request,
) -> GroundedDatabaseQueryPlan:
    """Plan a natural language question as constrained SQL without executing it."""
    return plan_grounded_database_query(
        question,
        conn,
        year=year,
        request_fn=request_fn,
    )


def execute_plan(
    planned: GroundedDatabaseQueryPlan,
    conn: duckdb.DuckDBPyConnection,
) -> GroundedDatabaseResult:
    """Validate and execute a planned grounded database question."""
    assembled = planned.assembled
    sql = assembled.sql.strip().rstrip(";")

    _validate_sql(sql, conn)
    return _execute_safe(
        sql,
        conn,
        assembled.params,
        source_label=planned.source_label,
        source_detail=planned.source_detail,
        unsupported_reason=assembled.unsupported_reason,
    )


def _validate_sql(sql: str, conn: duckdb.DuckDBPyConnection) -> None:
    """Check all table/column references in sql exist in the schema."""
    tables = {row[2]: row[3] for row in conn.execute("SHOW ALL TABLES").fetchall()}
    cte_names = {
        match.group(1).lower()
        for match in re.finditer(
            r"(?:WITH|,)\s+(\w+)\s+AS\s*\(",
            sql,
            re.IGNORECASE,
        )
    }

    referenced_tables: set[str] = set()
    for keyword in sorted(
        ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN", "CROSS JOIN"),
        key=len,
        reverse=True,
    ):
        referenced_tables |= set(re.findall(rf"\b{keyword}\s+(\w+)\b", sql, re.IGNORECASE))

    for tbl in referenced_tables:
        if tbl.lower() in cte_names:
            continue
        if tbl.lower() not in {t.lower() for t in tables}:
            raise ValueError(f"Unknown table '{tbl}' in generated SQL")

    all_valid_cols: set[str] = set()
    for _tbl_name, cols in tables.items():
        all_valid_cols.update(c.lower() for c in cols)
    all_valid_cols.add("avg")

    col_refs = re.findall(r"\b(\w+)\.(\w+)\b", sql, re.IGNORECASE)
    for tbl_alias, col in col_refs:
        if tbl_alias.isdigit():
            continue
        if col.lower() not in all_valid_cols:
            raise ValueError(
                f"Unknown column '{col}'. Valid columns: {', '.join(sorted(all_valid_cols))}"
            )


def _execute_safe(
    sql: str,
    conn: duckdb.DuckDBPyConnection,
    params: list[object] | None = None,
    *,
    source_label: str = "LLM-backed typed grounded database query",
    source_detail: str = (
        "LLM extracted a typed intent; Python assembled constrained SQL deterministically."
    ),
    unsupported_reason: str | None = None,
) -> GroundedDatabaseResult:
    """Execute with timeout and row limit guardrails."""
    try:
        conn.execute(f"SET statement_timeout = '{SCHEMA_TIMEOUT_MS}ms'")
    except Exception:
        pass

    safe_sql = sql
    if "LIMIT" not in sql.upper():
        safe_sql = f"{sql} LIMIT {MAX_ROWS}"

    try:
        safe_params = params or []
        rows = conn.execute(safe_sql, safe_params).fetchall()
        columns = [d[0] for d in conn.description]
        columns, rows = _normalize_player_name_columns(columns, rows)
        truncated = len(rows) == MAX_ROWS
        return GroundedDatabaseResult(
            sql=safe_sql,
            rows=rows,
            columns=columns,
            row_count=len(rows),
            truncated=truncated,
            params=safe_params,
            source_label=source_label,
            source_detail=source_detail,
            unsupported_reason=unsupported_reason,
        )
    except Exception as e:
        raise RuntimeError(f"Query failed: {e}\nSQL: {sql}") from e


def _normalize_player_name_columns(
    columns: list[str],
    rows: list[tuple],
) -> tuple[list[str], list[tuple]]:
    if "nameFirst" not in columns or "nameLast" not in columns:
        return columns, rows

    first_index = columns.index("nameFirst")
    last_index = columns.index("nameLast")
    normalized_columns = [
        "name" if index == first_index else column
        for index, column in enumerate(columns)
        if index != last_index
    ]
    normalized_rows = []
    for row in rows:
        full_name = " ".join(
            str(part).strip() for part in (row[first_index], row[last_index]) if part
        )
        normalized_rows.append(
            tuple(
                full_name if index == first_index else value
                for index, value in enumerate(row)
                if index != last_index
            )
        )
    return normalized_columns, normalized_rows


def format_result(result: GroundedDatabaseResult, question: str) -> str:
    """Convert result to readable string for terminal output."""
    if result.row_count == 0:
        return f"No results found for '{question}'."

    if _is_player_name_result(result):
        return _format_player_name_result(result)
    return _format_labeled_result(result)


def _is_player_name_result(result: GroundedDatabaseResult) -> bool:
    return result.columns == ["name"]


def _result_count_line(result: GroundedDatabaseResult, noun: str) -> str:
    plural = noun if result.row_count == 1 else f"{noun}s"
    line = f"{result.row_count} {plural} matched"
    if result.truncated or result.row_count > 100:
        line += ", showing first 100"
    return f"{line}:"


def _format_player_name_result(result: GroundedDatabaseResult) -> str:
    lines = [_result_count_line(result, "player")]
    for (full_name,) in result.rows[:100]:
        lines.append(f"- {full_name}")
    return "\n".join(lines)


def _format_labeled_result(result: GroundedDatabaseResult) -> str:
    lines = [_result_count_line(result, "result")]
    for row in result.rows[:100]:
        values = [f"{column}: {value}" for column, value in zip(result.columns, row, strict=False)]
        lines.append(f"- {'; '.join(values)}")
    return "\n".join(lines)
