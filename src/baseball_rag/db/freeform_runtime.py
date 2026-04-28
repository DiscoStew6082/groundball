"""Runtime validation, execution, and formatting for freeform queries."""

import re
from collections.abc import Callable
from typing import Any

import duckdb

from baseball_rag.db.freeform_assembler import _assemble_sql
from baseball_rag.db.freeform_intent import _generate_query_spec
from baseball_rag.db.freeform_schema import _get_schema_cached
from baseball_rag.db.freeform_templates import _detect_template, _template_source_detail
from baseball_rag.db.freeform_types import (
    MAX_ROWS,
    SCHEMA_TIMEOUT_MS,
    FreeformResult,
)
from baseball_rag.db.team_history import get_contextual_hint
from baseball_rag.generation.llm import make_request as default_make_request

RequestFn = Callable[..., Any]


def query(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    year: int | None = None,
    request_fn: RequestFn = default_make_request,
) -> FreeformResult:
    """Convert a natural language question to SQL and execute it."""
    hint = get_contextual_hint(question, year)
    enriched_question = f"{question} {hint}".strip() if hint else question

    assembled = _detect_template(enriched_question)
    if assembled is not None:
        source_label = "Deterministic template query"
        source_detail = _template_source_detail(enriched_question)
    else:
        schema = _get_schema_cached(conn)
        spec = _generate_query_spec(enriched_question, schema, request_fn=request_fn)
        assembled = _assemble_sql(spec)
        source_label = "LLM-backed typed freeform query"
        source_detail = (
            "LLM extracted a typed intent; Python assembled constrained SQL deterministically."
        )
    sql = assembled.sql.strip().rstrip(";")

    _validate_sql(sql, conn)
    return _execute_safe(
        sql,
        conn,
        assembled.params,
        source_label=source_label,
        source_detail=source_detail,
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
    source_label: str = "LLM-backed typed freeform query",
    source_detail: str = (
        "LLM extracted a typed intent; Python assembled constrained SQL deterministically."
    ),
) -> FreeformResult:
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
        truncated = len(rows) == MAX_ROWS
        return FreeformResult(
            sql=safe_sql,
            rows=rows,
            columns=columns,
            row_count=len(rows),
            truncated=truncated,
            params=safe_params,
            source_label=source_label,
            source_detail=source_detail,
        )
    except Exception as e:
        raise RuntimeError(f"Query failed: {e}\nSQL: {sql}") from e


def format_result(result: FreeformResult, question: str) -> str:
    """Convert result to readable string for terminal output."""
    if result.row_count == 0:
        return f"No results found for '{question}'."

    lines = []
    header = f"{result.columns}"
    lines.append(header)

    if result.truncated:
        lines.append(f"({result.row_count} rows total, showing first 100)")
    else:
        lines.append(f"({result.row_count} rows)")

    for row in result.rows[:100]:
        lines.append(str(row))

    return "\n".join(lines)
