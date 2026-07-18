"""Dedicated deterministic Adapter for separately governed Retrosheet queries."""

from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any

from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.grounded_database_templates import match_template

_RETROSHEET_TEMPLATE_IDS = {
    "batting_stat_streak",
    "player_batting_game_log",
    "pitcher_daily_strikeout_game_log",
    "pitcher_strikeout_side_game_log",
    "pitcher_strikeout_side_count",
    "pitcher_strikeout_side_leaders",
}
_QUERY_LOCK = threading.Lock()


def execute_retrosheet_query(question: str) -> dict[str, Any]:
    """Match and execute only a reviewed Retrosheet template, without primary routing."""
    matched = match_template(question)
    if matched is None or matched.template_id not in _RETROSHEET_TEMPLATE_IDS:
        raise ValueError("That question is not a published Retrosheet capability.")
    if matched.unsupported_reason is not None:
        raise ValueError(matched.unsupported_reason)

    sql = matched.assembled.sql.strip().rstrip(";")
    if not sql or sql.split(None, 1)[0].upper() not in {"SELECT", "WITH"}:
        raise ValueError("Retrosheet capability SQL must be one read-only query.")
    limited_sql = sql if "LIMIT" in sql.upper() else f"{sql} LIMIT 1000"
    with _QUERY_LOCK:
        cursor = get_duckdb().execute(limited_sql, matched.assembled.params)
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
            "bound_values": list(matched.assembled.params),
            "sources": [{"identity": "Retrosheet", "detail": matched.source_detail}],
            "row_count": len(rows),
        },
    }


def _json_scalar(value: object) -> object:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
