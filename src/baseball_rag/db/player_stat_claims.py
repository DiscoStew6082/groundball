"""DuckDB verification for stat claims extracted from LLM biographies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, cast

import duckdb

from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.stat_registry import StatDefinition, StatTable, get_stat, normalize_stat

ClaimScope = Literal["career", "season"]
ClaimStatus = Literal["verified", "contradicted", "unsupported_stat", "invalid_value", "no_data"]
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


def verify_player_stat_claims(
    player_id: str,
    claims: list[PlayerStatClaim],
    *,
    conn: duckdb.DuckDBPyConnection | None = None,
) -> list[PlayerStatVerification]:
    """Verify supported career and season stat claims against DuckDB."""
    active_conn = conn or get_duckdb()
    return [_verify_one_claim(active_conn, player_id, claim) for claim in claims]


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
