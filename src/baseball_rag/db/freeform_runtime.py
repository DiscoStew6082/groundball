"""Runtime validation, execution, and formatting for freeform queries."""

import re
from collections.abc import Callable
from dataclasses import replace
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
    PlannedFreeformQuery,
)
from baseball_rag.db.team_history import get_contextual_hint, resolve_team_identity
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
    planned = plan_query(question, conn, year=year, request_fn=request_fn)
    return execute_plan(planned, conn)


def plan_query(
    question: str,
    conn: duckdb.DuckDBPyConnection,
    *,
    year: int | None = None,
    request_fn: RequestFn = default_make_request,
) -> PlannedFreeformQuery:
    """Plan a natural language question as constrained SQL without executing it."""
    hint = get_contextual_hint(question, year)
    enriched_question = f"{question} {hint}".strip() if hint else question

    assembled = _detect_template(enriched_question)
    if assembled is not None:
        return PlannedFreeformQuery(
            assembled=assembled,
            planning_path="deterministic_template",
            source_label="Deterministic template query",
            source_detail=_template_source_detail(enriched_question),
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
    return PlannedFreeformQuery(
        assembled=assembled,
        planning_path="llm_intent",
        source_label="LLM-backed typed freeform query",
        source_detail=(
            "LLM extracted a typed intent; Python assembled constrained SQL deterministically."
        ),
        query_spec=spec,
    )


def execute_plan(
    planned: PlannedFreeformQuery,
    conn: duckdb.DuckDBPyConnection,
) -> FreeformResult:
    """Validate and execute a planned freeform query."""
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
    source_label: str = "LLM-backed typed freeform query",
    source_detail: str = (
        "LLM extracted a typed intent; Python assembled constrained SQL deterministically."
    ),
    unsupported_reason: str | None = None,
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
            unsupported_reason=unsupported_reason,
        )
    except Exception as e:
        raise RuntimeError(f"Query failed: {e}\nSQL: {sql}") from e


def format_result(result: FreeformResult, question: str) -> str:
    """Convert result to readable string for terminal output."""
    if result.row_count == 0:
        return f"No results found for '{question}'."

    if _is_player_name_result(result):
        return _format_player_name_result(result)
    return _format_labeled_result(result)


def _is_player_name_result(result: FreeformResult) -> bool:
    return result.columns == ["nameFirst", "nameLast"]


def _result_count_line(result: FreeformResult, noun: str) -> str:
    plural = noun if result.row_count == 1 else f"{noun}s"
    line = f"{result.row_count} {plural} matched"
    if result.truncated or result.row_count > 100:
        line += ", showing first 100"
    return f"{line}:"


def _format_player_name_result(result: FreeformResult) -> str:
    lines = [_result_count_line(result, "player")]
    for first_name, last_name in result.rows[:100]:
        full_name = " ".join(str(part) for part in (first_name, last_name) if part)
        lines.append(f"- {full_name}")
    return "\n".join(lines)


def _format_labeled_result(result: FreeformResult) -> str:
    lines = [_result_count_line(result, "result")]
    for row in result.rows[:100]:
        values = [f"{column}: {value}" for column, value in zip(result.columns, row, strict=False)]
        lines.append(f"- {'; '.join(values)}")
    return "\n".join(lines)
