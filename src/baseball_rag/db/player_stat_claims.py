"""DuckDB verification for stat claims extracted from LLM biographies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, cast

import duckdb

from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.stat_registry import (
    StatDefinition,
    StatTable,
    get_stat,
    normalize_stat,
    quote_identifier,
)

ClaimScope = Literal["career", "season"]
ClaimStatus = Literal["verified", "contradicted", "unsupported_stat", "invalid_value", "no_data"]
ConsensusStatus = Literal[
    "verified_by_all",
    "verified_primary_only",
    "verified_secondary_only",
    "contradicted_by_all",
    "conflict",
    "unsupported",
]
_CONTEXTUAL_STATS: dict[tuple[str, StatTable], StatDefinition] = {
    ("SO", "pitching"): StatDefinition("SO", "pitching", "SO"),
}
_STAT_TABLES: set[str] = {"batting", "pitching", "fielding"}
_PITCHING_SO_TERMS = (
    "as a pitcher",
    "batters",
    "on the mound",
    "pitched",
    "pitcher",
    "pitching",
)
_BATTING_SO_TERMS = (
    "as a batter",
    "as a hitter",
    "at the plate",
    "batting strikeout",
    "batting strikeouts",
)


@dataclass(frozen=True)
class PlayerStatClaim:
    """A stat claim emitted by the biography LLM contract."""

    stat: str
    value: object
    year: int | None = None
    scope: ClaimScope | None = None
    text: str | None = None
    table: StatTable | None = None

    @classmethod
    def from_payload(cls, payload: object) -> "PlayerStatClaim":
        if not isinstance(payload, dict):
            raise ValueError("stat claim must be a JSON object")
        stat = payload.get("stat")
        if not isinstance(stat, str) or not stat.strip():
            raise ValueError("stat claim requires a non-empty stat")
        year = payload.get("year")
        if year is not None:
            try:
                year = int(year)
            except (TypeError, ValueError) as exc:
                raise ValueError("stat claim year must be an integer") from exc
        scope = payload.get("scope")
        if scope is not None and scope not in {"career", "season"}:
            raise ValueError("stat claim scope must be career or season")
        raw_table = payload.get("table")
        table: StatTable | None = None
        if raw_table is not None:
            if not isinstance(raw_table, str) or raw_table not in _STAT_TABLES:
                raise ValueError("stat claim table must be batting, pitching, or fielding")
            table = cast(StatTable, raw_table)
        text = payload.get("text") or payload.get("context")
        return cls(
            stat=stat,
            value=payload.get("value"),
            year=year,
            scope=scope,
            text=str(text) if text is not None else None,
            table=table,
        )

    @property
    def resolved_scope(self) -> ClaimScope:
        if self.scope is not None:
            return self.scope
        return "season" if self.year is not None else "career"


@dataclass(frozen=True)
class PlayerStatVerification:
    """DuckDB verification result for one biography stat claim."""

    claim: PlayerStatClaim
    status: ClaimStatus
    actual_value: int | float | None
    table: str | None
    sql: str | None
    params: list[object]
    warning: str | None = None

    @property
    def verified(self) -> bool:
        return self.status == "verified"

    def to_row(self) -> dict[str, Any]:
        return {
            "stat": self.claim.stat,
            "claimed_value": self.claim.value,
            "actual_value": self.actual_value,
            "year": self.claim.year,
            "scope": self.claim.resolved_scope,
            "text": self.claim.text,
            "status": self.status,
            "table": self.table,
            "warning": self.warning,
        }


@dataclass(frozen=True)
class RetrosheetStatVerification:
    """Retrosheet verification result for one biography stat claim."""

    status: str
    actual_value: int | float | None
    table: str | None
    sql: str | None
    params: list[object]
    warning: str | None = None


@dataclass(frozen=True)
class PlayerStatConsensusVerification:
    """Consensus verification result comparing Lahman primary data to Retrosheet."""

    primary: PlayerStatVerification
    consensus_status: ConsensusStatus
    secondary: RetrosheetStatVerification

    def to_row(self) -> dict[str, Any]:
        row = self.primary.to_row()
        row["sql"] = self.primary.sql
        row.update(
            {
                "consensus_status": self.consensus_status,
                "primary_status": self.primary.status,
                "primary_actual_value": self.primary.actual_value,
                "secondary_status": self.secondary.status,
                "secondary_actual_value": self.secondary.actual_value,
                "secondary_table": self.secondary.table,
                "secondary_warning": self.secondary.warning,
            }
        )
        return row


def verify_player_stat_claims(
    player_id: str,
    claims: list[PlayerStatClaim],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[PlayerStatVerification]:
    """Verify supported career and season stat claims against DuckDB."""
    active_conn = conn or get_duckdb()
    return [_verify_one_claim(active_conn, player_id, claim) for claim in claims]


def verify_player_stat_claims_consensus(
    player_id: str,
    claims: list[PlayerStatClaim],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[PlayerStatConsensusVerification]:
    """Verify player stat claims against Lahman primary data and Retrosheet consensus."""
    active_conn = conn or get_duckdb()
    return [_verify_one_claim_consensus(active_conn, player_id, claim) for claim in claims]


def _verify_one_claim_consensus(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    claim: PlayerStatClaim,
) -> PlayerStatConsensusVerification:
    primary = _verify_one_claim(conn, player_id, claim)
    secondary = _verify_one_retrosheet_claim(conn, player_id, claim)
    consensus_status = _consensus_status(primary, secondary)
    return PlayerStatConsensusVerification(
        primary=primary,
        consensus_status=consensus_status,
        secondary=secondary,
    )


def _verify_one_claim(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    claim: PlayerStatClaim,
) -> PlayerStatVerification:
    claimed_value = _coerce_numeric(claim.value)
    if claimed_value is None:
        return PlayerStatVerification(
            claim=claim,
            status="invalid_value",
            actual_value=None,
            table=None,
            sql=None,
            params=[],
            warning=f"Could not interpret claimed {claim.stat} value {claim.value!r}.",
        )

    try:
        stat_defs = _candidate_stat_definitions(claim)
    except ValueError:
        return PlayerStatVerification(
            claim=claim,
            status="unsupported_stat",
            actual_value=None,
            table=None,
            sql=None,
            params=[],
            warning=f"Unsupported biography stat claim {claim.stat!r}.",
        )

    last_lookup: tuple[StatDefinition, str, list[object]] | None = None
    for stat_def in stat_defs:
        row, sql, params = _lookup_player_stat(conn, player_id, stat_def, claim)
        if row is not None:
            return _verification_from_row(
                claim=claim,
                claimed_value=claimed_value,
                row=row,
                stat_def=stat_def,
                sql=sql,
                params=params,
            )
        last_lookup = (stat_def, sql, params)

    stat_def, sql, params = last_lookup or (stat_defs[0], "", [])
    return PlayerStatVerification(
        claim=claim,
        status="no_data",
        actual_value=None,
        table=stat_def.table,
        sql=sql,
        params=params,
        warning=f"No DuckDB row could verify {claim.stat} for {claim.resolved_scope}.",
    )


def _verification_from_row(
    *,
    claim: PlayerStatClaim,
    claimed_value: float,
    row: tuple,
    stat_def: StatDefinition,
    sql: str,
    params: list[object],
) -> PlayerStatVerification:
    actual_value = _normalize_numeric(row[0])
    status: ClaimStatus = (
        "verified" if _values_match(claimed_value, actual_value) else "contradicted"
    )
    warning = None
    if status == "contradicted":
        scope_label = f"{claim.resolved_scope} {claim.year}" if claim.year else claim.resolved_scope
        warning = (
            f"DuckDB has {actual_value:g} for {claim.stat} ({scope_label}), not {claimed_value:g}."
        )
    return PlayerStatVerification(
        claim=claim,
        status=status,
        actual_value=_format_numeric(actual_value),
        table=stat_def.table,
        sql=sql,
        params=params,
        warning=warning,
    )


def _candidate_stat_definitions(claim: PlayerStatClaim) -> list[StatDefinition]:
    canonical = normalize_stat(claim.stat)
    table_hint = claim.table or _infer_claim_table(claim)
    if table_hint is None:
        return [get_stat(canonical)]

    primary = _stat_definition_for_table(canonical, table_hint)
    candidates = [primary]
    if claim.table is None:
        default = get_stat(canonical)
        if default.table != primary.table:
            candidates.append(default)
    return candidates


def _stat_definition_for_table(canonical: str, table: StatTable) -> StatDefinition:
    try:
        return get_stat(canonical, table=table)
    except ValueError:
        contextual = _CONTEXTUAL_STATS.get((canonical, table))
        if contextual is not None:
            return contextual
        raise


def _infer_claim_table(claim: PlayerStatClaim) -> StatTable | None:
    if normalize_stat(claim.stat) != "SO" or not claim.text:
        return None
    text = claim.text.casefold()
    if any(term in text for term in _BATTING_SO_TERMS):
        return "batting"
    if any(term in text for term in _PITCHING_SO_TERMS):
        return "pitching"
    return None


def _lookup_player_stat(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    stat_def: StatDefinition,
    claim: PlayerStatClaim,
) -> tuple[tuple | None, str, list[object]]:
    alias = {"batting": "b", "pitching": "pi", "fielding": "f"}[stat_def.table]
    expr = stat_def.aggregate_expression(alias)
    sample_clause = stat_def.aggregate_sample_clause(alias)
    having_parts = [f"{expr} IS NOT NULL"]
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)

    if claim.resolved_scope == "season":
        if claim.year is None:
            return None, "Season stat lookup skipped because no year was supplied", []
        sql = f"""
        SELECT {expr} AS stat_value
        FROM {stat_def.table} {alias}
        WHERE {alias}.playerID = ?
          AND {alias}.yearID = ?
        GROUP BY {alias}.playerID, {alias}.yearID
        HAVING {having_clause}
        """
        params: list[object] = [player_id, claim.year]
    else:
        sql = f"""
        SELECT {expr} AS stat_value
        FROM {stat_def.table} {alias}
        WHERE {alias}.playerID = ?
        HAVING {having_clause}
        """
        params = [player_id]
    return conn.execute(sql, params).fetchone(), sql, params


def _verify_one_retrosheet_claim(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    claim: PlayerStatClaim,
) -> RetrosheetStatVerification:
    claimed_value = _coerce_numeric(claim.value)
    if claimed_value is None:
        return RetrosheetStatVerification(
            status="unsupported",
            actual_value=None,
            table=None,
            sql=None,
            params=[],
            warning=f"Could not interpret claimed {claim.stat} value {claim.value!r}.",
        )

    try:
        stat_defs = _candidate_stat_definitions(claim)
    except ValueError:
        return RetrosheetStatVerification(
            status="unsupported",
            actual_value=None,
            table=None,
            sql=None,
            params=[],
            warning=f"Unsupported Retrosheet stat claim {claim.stat!r}.",
        )

    stat_def = stat_defs[0]
    retro_id, warning = _lookup_retro_id(conn, player_id)
    if retro_id is None:
        return RetrosheetStatVerification(
            status="unsupported",
            actual_value=None,
            table=None,
            sql=None,
            params=[],
            warning=warning,
        )

    bio_warning = _validate_retrosheet_biofile(conn, retro_id)
    if bio_warning is not None:
        return RetrosheetStatVerification(
            status="unsupported",
            actual_value=None,
            table="retrosheet_biofile",
            sql=None,
            params=[retro_id],
            warning=bio_warning,
        )

    row, sql, params, table, lookup_warning = _lookup_retrosheet_stat(
        conn,
        retro_id,
        stat_def,
        claim,
    )
    if row is None:
        return RetrosheetStatVerification(
            status="no_data" if lookup_warning is None else "unsupported",
            actual_value=None,
            table=table,
            sql=sql,
            params=params,
            warning=lookup_warning
            or f"No Retrosheet row could verify {claim.stat} for {claim.resolved_scope}.",
        )

    actual_value = _normalize_numeric(row[0])
    status = "verified" if _values_match(claimed_value, actual_value) else "contradicted"
    warning = None
    if status == "contradicted":
        scope_label = f"{claim.resolved_scope} {claim.year}" if claim.year else claim.resolved_scope
        warning = (
            f"Retrosheet has {actual_value:g} for {claim.stat} ({scope_label}), "
            f"not {claimed_value:g}."
        )
    return RetrosheetStatVerification(
        status=status,
        actual_value=_format_numeric(actual_value),
        table=table,
        sql=sql,
        params=params,
        warning=warning,
    )


def _consensus_status(
    primary: PlayerStatVerification,
    secondary: RetrosheetStatVerification,
) -> ConsensusStatus:
    primary_verified = primary.status == "verified"
    secondary_verified = secondary.status == "verified"

    if primary.actual_value is not None and secondary.actual_value is not None:
        if _values_match(float(primary.actual_value), float(secondary.actual_value)):
            if primary_verified and secondary_verified:
                return "verified_by_all"
            return "contradicted_by_all"
        return "conflict"
    if primary_verified:
        return "verified_primary_only"
    if secondary_verified:
        return "verified_secondary_only"
    return "unsupported"


def _lookup_retro_id(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
) -> tuple[str | None, str | None]:
    if not _table_exists(conn, "people"):
        return None, "Retrosheet verification requires people.retroID mapping."
    if "retroid" not in _table_columns(conn, "people"):
        return None, "Retrosheet verification requires people.retroID mapping."

    row = conn.execute(
        "SELECT retroID FROM people WHERE playerID = ?",
        [player_id],
    ).fetchone()
    if row is None or row[0] is None or str(row[0]).strip() == "":
        return None, f"No people.retroID mapping exists for Lahman playerID {player_id!r}."
    return str(row[0]), None


def _validate_retrosheet_biofile(
    conn: duckdb.DuckDBPyConnection,
    retro_id: str,
) -> str | None:
    table = "retrosheet_biofile"
    if not _table_exists(conn, table):
        return "Retrosheet biofile table retrosheet_biofile is not available."

    id_column = _first_existing_column(
        conn,
        table,
        ("retroID", "retro_id", "retrosheet_id", "player_id", "id", "ID"),
    )
    if id_column is None:
        return "Retrosheet biofile table has no recognizable player id column."

    sql = f"SELECT 1 FROM {table} WHERE {id_column} = ? LIMIT 1"
    if conn.execute(sql, [retro_id]).fetchone() is None:
        return f"Retrosheet biofile has no row for retroID {retro_id!r}."
    return None


def _lookup_retrosheet_stat(
    conn: duckdb.DuckDBPyConnection,
    retro_id: str,
    stat_def: StatDefinition,
    claim: PlayerStatClaim,
) -> tuple[tuple | None, str | None, list[object], str | None, str | None]:
    table = f"retrosheet_{stat_def.table}"
    if not _table_exists(conn, table):
        return None, None, [], table, f"Retrosheet table {table} is not available."

    alias = {"batting": "rb", "pitching": "rp", "fielding": "rf"}[stat_def.table]
    player_column = _first_existing_column(
        conn,
        table,
        ("retroID", "retro_id", "retrosheet_id", "player_id", "batter", "pitcher", "fielder"),
    )
    if player_column is None:
        return None, None, [], table, f"Retrosheet table {table} has no player id column."

    year_column = _first_existing_column(conn, table, ("yearID", "year_id", "season", "year"))
    expr = _retrosheet_aggregate_expression(conn, table, alias, stat_def)
    if expr is None:
        return (
            None,
            None,
            [],
            table,
            f"Retrosheet table {table} cannot verify {stat_def.canonical}.",
        )

    having_parts = [f"{expr} IS NOT NULL"]
    sample_clause = _retrosheet_sample_clause(conn, table, alias, stat_def)
    if sample_clause:
        having_parts.append(sample_clause)
    having_clause = " AND ".join(having_parts)

    if claim.resolved_scope == "season":
        if claim.year is None:
            return (
                None,
                "Season Retrosheet lookup skipped because no year was supplied",
                [],
                table,
                None,
            )
        if year_column is None:
            return None, None, [], table, f"Retrosheet table {table} has no season column."
        sql = f"""
        SELECT {expr} AS stat_value
        FROM {table} {alias}
        WHERE {alias}.{player_column} = ?
          AND {alias}.{year_column} = ?
        GROUP BY {alias}.{player_column}, {alias}.{year_column}
        HAVING {having_clause}
        """
        params: list[object] = [retro_id, claim.year]
    else:
        sql = f"""
        SELECT {expr} AS stat_value
        FROM {table} {alias}
        WHERE {alias}.{player_column} = ?
        HAVING {having_clause}
        """
        params = [retro_id]
    return conn.execute(sql, params).fetchone(), sql, params, table, None


def _retrosheet_aggregate_expression(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    alias: str,
    stat_def: StatDefinition,
) -> str | None:
    stat = stat_def.canonical
    columns = _table_columns(conn, table)

    if stat == "AVG":
        if {"h", "ab"}.issubset(columns):
            return f"CAST(SUM({alias}.H) AS DOUBLE) / NULLIF(SUM({alias}.AB), 0)"
        return None
    if stat == "OPS":
        required = {"h", "bb", "hbp", "ab", "sf", "2b", "3b", "hr"}
        if required.issubset(columns):
            return (
                f"(CAST(SUM(COALESCE({alias}.H, 0) + COALESCE({alias}.BB, 0) + "
                f"COALESCE({alias}.HBP, 0)) AS DOUBLE) / "
                f"NULLIF(SUM(COALESCE({alias}.AB, 0) + COALESCE({alias}.BB, 0) + "
                f"COALESCE({alias}.HBP, 0) + COALESCE({alias}.SF, 0)), 0)) + "
                f'(CAST(SUM((COALESCE({alias}.H, 0) - COALESCE({alias}."2B", 0) - '
                f'COALESCE({alias}."3B", 0) - COALESCE({alias}.HR, 0)) + '
                f'2 * COALESCE({alias}."2B", 0) + 3 * COALESCE({alias}."3B", 0) + '
                f"4 * COALESCE({alias}.HR, 0)) AS DOUBLE) / "
                f"NULLIF(SUM({alias}.AB), 0))"
            )
        return None
    if stat == "ERA":
        if {"er", "ipouts"}.issubset(columns):
            return f"27.0 * SUM({alias}.ER) / NULLIF(SUM({alias}.IPouts), 0)"
        return None
    if stat == "WHIP":
        if {"bb", "h", "ipouts"}.issubset(columns):
            return (
                f"CAST(SUM({alias}.BB + {alias}.H) AS DOUBLE) / "
                f"NULLIF(SUM({alias}.IPouts) / 3.0, 0)"
            )
        return None
    if stat == "G" and "g" not in columns:
        game_column = _first_existing_column(conn, table, ("game_id", "gameID", "gameid"))
        if game_column is not None:
            return f"COUNT(DISTINCT {alias}.{game_column})"

    column = _first_existing_column(conn, table, (stat_def.column or stat,))
    if column is None:
        return None
    return f"SUM({alias}.{column})"


def _retrosheet_sample_clause(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    alias: str,
    stat_def: StatDefinition,
) -> str | None:
    if stat_def.canonical in {"AVG", "OPS"} and "ab" in _table_columns(conn, table):
        return f"SUM({alias}.AB) >= 100"
    if stat_def.canonical in {"ERA", "WHIP"} and "ipouts" in _table_columns(conn, table):
        return f"SUM({alias}.IPouts) >= 300"
    return None


def _table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE lower(table_name) = lower(?) LIMIT 1",
        [table],
    ).fetchone()
    return row is not None


def _table_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    return set(_table_column_lookup(conn, table))


def _table_column_lookup(conn: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    rows = conn.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE lower(table_name) = lower(?)
        """,
        [table],
    ).fetchall()
    return {str(row[0]).casefold(): str(row[0]) for row in rows}


def _first_existing_column(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    candidates: tuple[str, ...],
) -> str | None:
    columns = _table_column_lookup(conn, table)
    for candidate in candidates:
        column = columns.get(candidate.casefold())
        if column is not None:
            return quote_identifier(column)
    return None


def _coerce_numeric(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().replace(",", "")
        if stripped.startswith("."):
            stripped = f"0{stripped}"
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _normalize_numeric(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    return float(str(value))


def _values_match(claimed: float, actual: float) -> bool:
    if float(claimed).is_integer() and float(actual).is_integer():
        return int(claimed) == int(actual)
    return round(claimed, 3) == round(actual, 3)


def _format_numeric(value: float) -> int | float:
    if value.is_integer():
        return int(value)
    return value
