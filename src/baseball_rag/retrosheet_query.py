"""Dedicated deterministic Adapter for separately governed Retrosheet queries."""

from __future__ import annotations

import os
import threading
from datetime import date, datetime
from typing import Any

from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.retrosheet_query_templates import (
    match_published_retrosheet_template,
    match_retrosheet_template,
)
from baseball_rag.query.runtime import published_data_runtime

_QUERY_LOCK = threading.Lock()


def execute_retrosheet_query(question: str) -> dict[str, Any]:
    """Match and execute only a reviewed Retrosheet template, without primary routing."""
    bundle_configured = bool(os.environ.get("GROUNDBALL_RELEASE_BUNDLE"))
    public_demo = os.environ.get("GROUNDBALL_PUBLIC_DEMO", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if public_demo != bundle_configured:
        raise ValueError("Ground Ball public release configuration is incomplete.")
    release_bound = public_demo
    matcher = match_published_retrosheet_template if release_bound else match_retrosheet_template
    matched = matcher(question)
    if matched is None:
        raise ValueError("That question is not a published Retrosheet capability.")
    if matched.unsupported_reason is not None:
        raise ValueError(matched.unsupported_reason)

    sql = matched.sql.strip().rstrip(";")
    if not sql or sql.split(None, 1)[0].upper() not in {"SELECT", "WITH"}:
        raise ValueError("Retrosheet capability SQL must be one read-only query.")
    limited_sql = sql if "LIMIT" in sql.upper() else f"{sql} LIMIT 1000"
    if release_bound:
        runtime = published_data_runtime()
        with runtime.connection_lock:
            cursor = runtime.connection.execute(limited_sql, matched.params)
            columns = [str(item[0]) for item in cursor.description]
            materialized = cursor.fetchall()
    else:
        with _QUERY_LOCK:
            cursor = get_duckdb().execute(limited_sql, matched.params)
            columns = [str(item[0]) for item in cursor.description]
            materialized = cursor.fetchall()
    rows = [
        {column: _json_scalar(value) for column, value in zip(columns, values, strict=True)}
        for values in materialized
    ]
    return {
        "kind": "rows" if rows else "no_data",
        "capability": "retrosheet",
        "template": matched.template_id,
        "rows": rows,
        "evidence": {
            "parameterized_sql": limited_sql,
            "bound_values": list(matched.params),
            "sources": [{"identity": "Retrosheet", "detail": matched.source_detail}],
            "row_count": len(rows),
        },
    }


def _json_scalar(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
