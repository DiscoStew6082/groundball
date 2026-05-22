"""SQL query helpers for baseball statistics."""

from dataclasses import dataclass
from typing import Literal

import duckdb

from baseball_rag.arch.tracing import traced
from baseball_rag.db.duckdb_schema import TEAM_MAP, get_duckdb
from baseball_rag.db.stat_registry import StatTable, get_stat

StatQueryKind = Literal["player", "leaderboard", "career"]


@dataclass(frozen=True)
class StatQueryPlan:
    """Execution plan for a deterministic stat request."""

    stat: str
    table: StatTable
    kind: StatQueryKind
    intent: str
    position: str | None = None
    player_name: str | None = None
    year: int | None = None
    start_year: int | None = None
    end_year: int | None = None
    limit: int = 10


@dataclass(frozen=True)
class StatQueryResult:
    """Executed deterministic stat query data ready for answer/provenance use."""

    stat: str
    label: str
    tables: list[str]
    rows: list[dict]
    sql: str
    executed_sql: str
    params: list[object]


def _team_name(team_id: str) -> str:
    """Map a team ID to its full name via TEAM_MAP."""
    return TEAM_MAP.get(team_id, "Unknown")


@traced(component_id="duckdb", label="DB Query")
def execute_stat_query(
    stat: str,
    *,
    table: StatTable,
    start_year: int | None = None,
    end_year: int | None = None,
    player_name: str | None = None,
    year: int | None = None,
    position: str | None = None,
    limit: int = 10,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> StatQueryResult:
    """Compatibility adapter for deterministic stat queries.

    New deterministic callers should pass a StatQueryPlan to execute_stat_query_plan.
    """
    stat_def = get_stat(stat, table=table)
    if player_name:
        kind: StatQueryKind = "player"
    elif start_year is not None and end_year is not None:
        kind = "leaderboard"
    else:
        kind = "career"
    return _execute_stat_query_plan(
        StatQueryPlan(
            stat=stat_def.canonical,
            table=stat_def.table,
            kind=kind,
            intent="stat_query",
            position=position,
            player_name=player_name,
            year=year,
            start_year=start_year,
            end_year=end_year,
            limit=limit,
        ),
        conn=conn,
    )


@traced(component_id="duckdb", label="DB Query")
def execute_stat_query_plan(
    plan: StatQueryPlan,
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> StatQueryResult:
    """Execute a deterministic stat plan and return provenance-ready details."""
    return _execute_stat_query_plan(plan, conn=conn)


def _execute_stat_query_plan(
    plan: StatQueryPlan,
    *,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    stat_def = get_stat(plan.stat, table=plan.table)
    stat = stat_def.canonical
    table = stat_def.table
    limit = plan.limit

    if plan.kind == "player":
        if plan.player_name is None:
            return StatQueryResult(
                stat=stat,
                label="Player stat lookup",
                tables=[table, "people"],
                rows=[],
                sql="Player stat lookup skipped because no player name was supplied",
                executed_sql="Player stat lookup skipped because no player name was supplied",
                params=[],
            )
        return _execute_player_stat(
            stat,
            table=table,
            player_name=plan.player_name,
            year=plan.year,
            position=plan.position,
            conn=conn,
        )

    start_year = plan.start_year
    end_year = plan.end_year
    if table == "fielding":
        if start_year is None or end_year is None:
            return _execute_fielding_career(
                stat,
                position=plan.position,
                limit=limit,
                conn=conn,
            )
        return _execute_fielding_leaders(
            stat,
            start_year=start_year,
            end_year=end_year,
            position=plan.position,
            conn=conn,
        )
    if table == "pitching":
        if start_year is not None and end_year is not None:
            return _execute_pitching_range(
                stat,
                start_year=start_year,
                end_year=end_year,
                conn=conn,
            )
        return _execute_pitching_career(stat, limit=limit, conn=conn)
    if start_year is not None and end_year is not None:
        return _execute_batting_range(
            stat,
            start_year=start_year,
            end_year=end_year,
            conn=conn,
        )
    return _execute_batting_career(stat, limit=limit, conn=conn)


@traced(component_id="duckdb", label="DB Query")
def get_stat_leaders(stat: str, year: int) -> list[dict]:
    """Compatibility adapter for top 10 batting stat leaders for a given year.

    Args:
        stat: The statistic to rank by (HR, RBI, H, AB, R, 2B, 3B)
        year: The season year

    Returns:
        List of dicts with keys: name, team, stat_value
    """
    result = execute_stat_query(stat, table="batting", start_year=year, end_year=year)
    return result.rows


@traced(component_id="duckdb", label="DB Query")
def get_stat_leaders_range(stat: str, start_year: int, end_year: int) -> list[dict]:
    """Compatibility adapter for top 10 batting stat leaders over a year range.

    Aggregates the named stat across all seasons in [start_year, end_year]
    (inclusive), then ranks by total. This handles decade queries
    ("seventies") and explicit ranges ("1960-1980").

    Parameters
    ----------
    stat : str
        The statistic to rank by (HR, RBI, H, AB, R, 2B, 3B)
    start_year : int
        First season in the range (inclusive).
    end_year : int
        Last season in the range (inclusive). Must be >= start_year.

    Returns
    -------
    list[dict]
        List of dicts with keys: name, team ("Range"), stat_value
    """
    result = execute_stat_query(stat, table="batting", start_year=start_year, end_year=end_year)
    return result.rows


@traced(component_id="duckdb", label="DB Query")
def get_career_stat_leaders(stat: str, limit: int = 10) -> list[dict]:
    """Compatibility adapter for career batting stat leaders.

    Args:
        stat: The statistic to rank by (HR, RBI, H, etc.)
        limit: Number of results to return

    Returns:
        List of dicts with keys: name, team, stat_value
    """
    result = execute_stat_query(stat, table="batting", limit=limit)
    return result.rows


def get_fielding_leaders(year: int, position: str) -> list[dict]:
    """Compatibility adapter for fielding putouts leaders for a given year and position.

    Args:
        year: The season year
        position: 'OF' for all outfield, or specific 'LF'/'CF'/'RF'

    Returns:
        List of dicts with keys: player (name), stat_value (putouts)
    """
    result = execute_stat_query(
        "PO",
        table="fielding",
        start_year=year,
        end_year=year,
        position=position,
        limit=20,
    )
    return [{"player": row["name"], "stat_value": row["stat_value"]} for row in result.rows]


def _execute_batting_range(
    stat: str,
    *,
    start_year: int,
    end_year: int,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    stat_def = get_stat(stat, table="batting")
    expr = stat_def.aggregate_expression("b")
    sample_clause = stat_def.aggregate_sample_clause("b")
    having_parts = [f"{expr} IS NOT NULL", f"{expr} > 0"]
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)
    sql = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM batting b
    JOIN people p ON b.playerID = p.playerID
    WHERE b.yearID >= ?
      AND b.yearID <= ?
    GROUP BY b.playerID, p.nameLast, p.nameFirst
    HAVING {having_clause}
    ORDER BY stat_value DESC
    LIMIT 10
    """
    active_conn = conn or get_duckdb()
    result = active_conn.execute(sql, [start_year, end_year]).fetchall()
    rows = [{"name": r[0], "team": "Range", "stat_value": r[1]} for r in result]
    return StatQueryResult(
        stat=stat_def.canonical,
        label=f"{stat_def.canonical} leaderboard for {start_year}-{end_year}",
        tables=["batting", "people"],
        rows=rows,
        sql=sql,
        executed_sql=sql,
        params=[start_year, end_year],
    )


def _execute_batting_career(
    stat: str,
    *,
    limit: int,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    stat_def = get_stat(stat, table="batting")
    expr = stat_def.aggregate_expression("b")
    sample_clause = stat_def.aggregate_sample_clause("b")
    having_parts = [f"{expr} IS NOT NULL", f"{expr} > 0"]
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)
    sql = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM batting b
    JOIN people p ON b.playerID = p.playerID
    GROUP BY b.playerID, p.nameLast, p.nameFirst
    HAVING {having_clause}
    ORDER BY stat_value DESC
    LIMIT ?
    """
    active_conn = conn or get_duckdb()
    result = active_conn.execute(sql, [limit]).fetchall()
    rows = [{"name": r[0], "team": "Career", "stat_value": r[1]} for r in result]
    return StatQueryResult(
        stat=stat_def.canonical,
        label=f"Career {stat_def.canonical} leaderboard",
        tables=["batting", "people"],
        rows=rows,
        sql=sql,
        executed_sql=sql,
        params=[limit],
    )


def _execute_pitching_range(
    stat: str,
    *,
    start_year: int,
    end_year: int,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    stat_def = get_stat(stat, table="pitching")
    expr = stat_def.aggregate_expression("pi")
    sample_clause = stat_def.aggregate_sample_clause("pi")
    having_parts = [f"{expr} IS NOT NULL", f"{expr} > 0"]
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)
    order_direction = "DESC" if stat_def.higher_is_better else "ASC"
    sql = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM pitching pi
    JOIN people p ON pi.playerID = p.playerID
    WHERE pi.yearID >= ?
      AND pi.yearID <= ?
    GROUP BY pi.playerID, p.nameLast, p.nameFirst
    HAVING {having_clause}
    ORDER BY stat_value {order_direction}
    LIMIT 10
    """
    active_conn = conn or get_duckdb()
    result = active_conn.execute(sql, [start_year, end_year]).fetchall()
    rows = [{"name": r[0], "team": "Range", "stat_value": r[1]} for r in result]
    return StatQueryResult(
        stat=stat_def.canonical,
        label=f"{stat_def.canonical} leaderboard for {start_year}-{end_year}",
        tables=["pitching", "people"],
        rows=rows,
        sql=sql,
        executed_sql=sql,
        params=[start_year, end_year],
    )


def _execute_pitching_career(
    stat: str,
    *,
    limit: int,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    stat_def = get_stat(stat, table="pitching")
    expr = stat_def.aggregate_expression("pi")
    sample_clause = stat_def.aggregate_sample_clause("pi")
    having_parts = [f"{expr} IS NOT NULL", f"{expr} > 0"]
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)
    order_direction = "DESC" if stat_def.higher_is_better else "ASC"
    sql = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM pitching pi
    JOIN people p ON pi.playerID = p.playerID
    GROUP BY pi.playerID, p.nameLast, p.nameFirst
    HAVING {having_clause}
    ORDER BY stat_value {order_direction}
    LIMIT ?
    """
    active_conn = conn or get_duckdb()
    result = active_conn.execute(sql, [limit]).fetchall()
    rows = [{"name": r[0], "team": "Career", "stat_value": r[1]} for r in result]
    return StatQueryResult(
        stat=stat_def.canonical,
        label=f"Career {stat_def.canonical} leaderboard",
        tables=["pitching", "people"],
        rows=rows,
        sql=sql,
        executed_sql=sql,
        params=[limit],
    )


def _execute_fielding_leaders(
    stat: str,
    *,
    start_year: int,
    end_year: int,
    position: str | None,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    stat_def = get_stat(stat, table="fielding")
    params: list[object] = [start_year, end_year]
    position_label = "All fielding"
    if position is None:
        pos_clause = ""
    elif position.upper() == "OF":
        pos_clause = "AND f.POS = ?"
        params.append("OF")
        position_label = "OF"
    else:
        pos_clause = "AND f.POS = ?"
        params.append(position.upper())
        position_label = position.upper()
    expr = stat_def.aggregate_expression("f")
    sql = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM fielding f
    JOIN people p ON f.playerID = p.playerID
    WHERE f.yearID >= ?
      AND f.yearID <= ?
      {pos_clause}
    GROUP BY f.playerID, p.nameLast, p.nameFirst
    HAVING {expr} IS NOT NULL AND {expr} > 0
    ORDER BY stat_value DESC
    LIMIT 10
    """
    active_conn = conn or get_duckdb()
    result = active_conn.execute(sql, params).fetchall()
    rows = [{"name": r[0], "team": position_label, "stat_value": r[1]} for r in result]
    return StatQueryResult(
        stat=stat_def.canonical,
        label=f"{stat_def.canonical} leaderboard for {start_year}-{end_year}",
        tables=["fielding", "people"],
        rows=rows,
        sql=sql,
        executed_sql=sql,
        params=params,
    )


def _execute_fielding_career(
    stat: str,
    *,
    position: str | None,
    limit: int,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    stat_def = get_stat(stat, table="fielding")
    params: list[object] = [limit]
    position_label = "Career"
    if position is None:
        pos_clause = ""
    else:
        pos_clause = "WHERE f.POS = ?"
        params = [position.upper(), limit]
        position_label = position.upper()
    expr = stat_def.aggregate_expression("f")
    sql = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM fielding f
    JOIN people p ON f.playerID = p.playerID
    {pos_clause}
    GROUP BY f.playerID, p.nameLast, p.nameFirst
    HAVING {expr} IS NOT NULL AND {expr} > 0
    ORDER BY stat_value DESC
    LIMIT ?
    """
    active_conn = conn or get_duckdb()
    result = active_conn.execute(sql, params).fetchall()
    rows = [{"name": r[0], "team": position_label, "stat_value": r[1]} for r in result]
    return StatQueryResult(
        stat=stat_def.canonical,
        label=f"Career {stat_def.canonical} leaderboard",
        tables=["fielding", "people"],
        rows=rows,
        sql=sql,
        executed_sql=sql,
        params=params,
    )


def _execute_player_stat(
    stat: str,
    *,
    table: StatTable,
    player_name: str,
    year: int | None,
    position: str | None,
    conn: duckdb.DuckDBPyConnection | None,
) -> StatQueryResult:
    alias = {"batting": "b", "pitching": "pi", "fielding": "f"}[table]
    stat_def = get_stat(stat, table=table)
    expr = stat_def.expression(alias)
    sample_clause = (
        stat_def.min_sample_clause.format(alias=alias) if stat_def.min_sample_clause else None
    )

    parts = [p for p in player_name.strip().split() if not _is_suffix(p)]
    if len(parts) >= 2:
        first, last = parts[0], " ".join(parts[1:])
    elif len(parts) == 1:
        first = None
        last = parts[0]
    else:
        return StatQueryResult(
            stat=stat_def.canonical,
            label="Player stat lookup",
            tables=[table, "people"],
            rows=[],
            sql="Player stat lookup skipped because no player name was supplied",
            executed_sql="Player stat lookup skipped because no player name was supplied",
            params=[],
        )

    if first:
        where_parts = [
            "strip_accents(LOWER(p.nameFirst)) = ?",
            "strip_accents(LOWER(p.nameLast)) = ?",
        ]
        params: list[object] = [_normalize(first), _normalize(last)]
    else:
        where_parts = ["strip_accents(LOWER(p.nameLast)) = ?"]
        params = [_normalize(last)]

    if year is not None:
        where_parts.append(f"{alias}.yearID = ?")
        params.append(year)
    if table == "fielding" and position is not None:
        where_parts.append(f"{alias}.POS = ?")
        params.append(position.upper())
    if sample_clause:
        where_parts.append(sample_clause)
    where_clause = " AND ".join(where_parts)

    sql = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {alias}.yearID,
        {alias}.teamID,
        {expr} AS stat_value
    FROM {table} {alias}
    JOIN people p ON {alias}.playerID = p.playerID
    WHERE {where_clause}
      AND {expr} IS NOT NULL
    ORDER BY {alias}.yearID DESC
    LIMIT 1
    """
    active_conn = conn or get_duckdb()
    result = active_conn.execute(sql, params).fetchone()
    row = None
    if result:
        row = {
            "name": result[0],
            "year": result[1],
            "team": _team_name(result[2]),
            "stat_value": result[3],
        }
    return StatQueryResult(
        stat=stat_def.canonical,
        label="Player stat lookup",
        tables=[table, "people"],
        rows=[row] if row else [],
        sql=sql,
        executed_sql=sql,
        params=params,
    )


def _normalize(s: str) -> str:
    """ASCII-fold a string for fuzzy matching.

    Uses NFD normalization so that composed accented characters like "ñ" (U+00F1)
    decompose into base letter + combining mark, then unidecode strips the combining
    mark — yielding the same result as DuckDB's strip_accents(LOWER(...)).

    Example: "Acuña" → NFD → "Acun~a" (combining tilde) → unidecode → "acuna"
             matching DB: strip_accents(LOWER('Acuña')) = 'acuna'
    """
    import re
    import unicodedata

    from unidecode import unidecode

    return re.sub(r"[^a-z]", "", unidecode(unicodedata.normalize("NFD", s)).lower())


def _is_suffix(s: str) -> bool:
    """Return True if s is a common baseball name suffix (case-insensitive, strips trailing .)."""
    return s.lower().rstrip(".") in {"jr", "sr", "ii", "iii", "iv"}
