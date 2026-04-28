"""SQL query helpers for baseball statistics."""

import duckdb

from baseball_rag.arch.tracing import traced
from baseball_rag.db.duckdb_schema import TEAM_MAP, get_duckdb
from baseball_rag.db.stat_registry import get_stat


def _team_name(team_id: str) -> str:
    """Map a team ID to its full name via TEAM_MAP."""
    return TEAM_MAP.get(team_id, "Unknown")


@traced(component_id="duckdb", label="DB Query")
def get_stat_leaders(stat: str, year: int) -> list[dict]:
    """Get top 10 batting stat leaders for a given year.

    Args:
        stat: The statistic to rank by (HR, RBI, H, AB, R, 2B, 3B)
        year: The season year

    Returns:
        List of dicts with keys: name, team, stat_value
    """
    stat_def = get_stat(stat, table="batting")
    expr = stat_def.expression("b")

    query = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        b.teamID,
        {expr} AS stat_value
    FROM batting b
    JOIN people p ON b.playerID = p.playerID
    WHERE b.yearID = ?
      AND {expr} IS NOT NULL
    ORDER BY {expr} DESC
    LIMIT 10
    """

    conn = get_duckdb()
    result = conn.execute(query, [year]).fetchall()

    return [{"name": r[0], "team": _team_name(r[1]), "stat_value": r[2]} for r in result]


@traced(component_id="duckdb", label="DB Query")
def get_stat_leaders_range(stat: str, start_year: int, end_year: int) -> list[dict]:
    """Get top 10 batting stat leaders aggregated over a year range.

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
    stat_def = get_stat(stat, table="batting")
    expr = stat_def.aggregate_expression("b")
    sample_clause = stat_def.aggregate_sample_clause("b")
    having_parts = [f"{expr} IS NOT NULL", f"{expr} > 0"]
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)

    query = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM batting b
    JOIN people p ON b.playerID = p.playerID
    WHERE b.yearID >= ?
      AND b.yearID <= ?
    GROUP BY p.nameLast, p.nameFirst
    HAVING {having_clause}
    ORDER BY stat_value DESC
    LIMIT 10
    """

    conn = get_duckdb()
    result = conn.execute(query, [start_year, end_year]).fetchall()

    return [{"name": r[0], "team": "Range", "stat_value": r[1]} for r in result]


@traced(component_id="duckdb", label="DB Query")
def get_career_stat_leaders(stat: str, limit: int = 10) -> list[dict]:
    """Get career batting stat leaders.

    Args:
        stat: The statistic to rank by (HR, RBI, H, etc.)
        limit: Number of results to return

    Returns:
        List of dicts with keys: name, team, stat_value
    """
    stat_def = get_stat(stat, table="batting")
    expr = stat_def.aggregate_expression("b")
    sample_clause = stat_def.aggregate_sample_clause("b")
    having_parts = [f"{expr} IS NOT NULL", f"{expr} > 0"]
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)

    query = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        {expr} AS stat_value
    FROM batting b
    JOIN people p ON b.playerID = p.playerID
    GROUP BY p.nameLast, p.nameFirst
    HAVING {having_clause}
    ORDER BY stat_value DESC
    LIMIT ?
    """

    conn = get_duckdb()
    result = conn.execute(query, [limit]).fetchall()

    return [{"name": r[0], "team": "Career", "stat_value": r[1]} for r in result]


def get_fielding_leaders(year: int, position: str) -> list[dict]:
    """Get fielding putouts leaders for a given year and position.

    Args:
        year: The season year
        position: 'OF' for all outfield, or specific 'LF'/'CF'/'RF'

    Returns:
        List of dicts with keys: player (name), stat_value (putouts)
    """
    if position.upper() == "OF":
        pos_clause = "AND f.POS IN (?, ?, ?)"
        params: list = [year, "LF", "CF", "RF"]
    else:
        pos_clause = "AND f.POS = ?"
        params = [year, position.upper()]

    query = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS player,
        SUM(f.PO) AS stat_value
    FROM fielding f
    JOIN people p ON f.playerID = p.playerID
    WHERE f.yearID = ?
      {pos_clause}
    GROUP BY p.nameLast, p.nameFirst
    ORDER BY stat_value DESC
    LIMIT 20
    """

    conn = get_duckdb()
    result = conn.execute(query, params).fetchall()

    return [{"player": r[0], "stat_value": r[1]} for r in result]


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


def get_player_stat(
    conn: duckdb.DuckDBPyConnection,
    player_name: str,
    stat: str,
    year: int | None = None,
) -> dict | None:
    """Get a single player's stat for a specific season (or their most recent if no year given).

    Args:
        conn: Active DuckDB connection.
        player_name: Full name e.g. "Ronald Acuna" or "Matt Olson".
            Suffixes like "Jr.", "Sr.", "III" are handled automatically.
        stat: The statistic to fetch (HR, RBI, etc.).
        year: Optional specific season year.

    Returns:
        Dict with keys: name, year, team, stat_value, or None if not found.
    """
    stat_def = get_stat(stat, table="batting")
    expr = stat_def.expression("b")

    # Split player name into first/last, stripping common suffixes
    parts = [p for p in player_name.strip().split() if not _is_suffix(p)]
    if len(parts) >= 2:
        first, last = parts[0], " ".join(parts[1:])  # Handle multi-word last names
    elif len(parts) == 1:
        last = parts[0]
        first = None
    else:
        return None

    norm_first = _normalize(first) if first else None
    norm_last = _normalize(last)

    # Both Python and DB use ASCII-folded last names for comparison.
    # DuckDB's strip_accents(LOWER(...)) normalizes accents, matching _normalize().
    if first:
        where_clause = (
            "strip_accents(LOWER(p.nameFirst)) = ? AND strip_accents(LOWER(p.nameLast)) = ?"
        )
        params: list = [norm_first, norm_last]
    else:
        where_clause = "strip_accents(LOWER(p.nameLast)) = ?"
        params = [norm_last]

    if year is not None:
        where_clause += " AND b.yearID = ?"
        params.append(year)

    query = f"""
    SELECT
        p.nameLast || ', ' || p.nameFirst AS name,
        b.yearID,
        b.teamID,
        {expr} AS stat_value
    FROM batting b
    JOIN people p ON b.playerID = p.playerID
    WHERE {where_clause}
      AND {expr} IS NOT NULL
    ORDER BY b.yearID DESC
    LIMIT 1
    """
    result = conn.execute(query, params).fetchone()
    if not result:
        return None
    return {
        "name": result[0],
        "year": result[1],
        "team": _team_name(result[2]),
        "stat_value": result[3],
    }
