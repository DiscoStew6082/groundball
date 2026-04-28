"""Schema introspection for LLM-backed freeform planning."""

import duckdb

_cached_schema: str | None = None


def _get_schema_cached(conn: duckdb.DuckDBPyConnection) -> str:
    global _cached_schema
    if _cached_schema is not None:
        return _cached_schema

    tables = conn.execute("SHOW ALL TABLES").fetchall()
    lines = []
    for row in tables:
        tbl = row[2]
        cols = conn.execute(f"DESCRIBE {tbl}").fetchall()
        col_list = ", ".join(f"{c[0]} ({c[1]})" for c in cols)
        sample = conn.execute(f"SELECT * FROM {tbl} LIMIT 2").fetchall()
        lines.append(f"- **{tbl}**: {col_list}")
        if sample:
            desc = conn.description
            lines.append(f"  Sample row: {dict(zip([d[0] for d in desc], sample[0]))}")

    lines.append(
        "\nComputed / derived stats (do NOT assume these exist as columns):\n"
        "  batting: AVG = CAST(H AS DOUBLE) / NULLIF(AB, 0)\n"
        "  pitching: ERA is pre-computed and exists as a column\n"
    )

    _cached_schema = "\n".join(lines)
    return _cached_schema
