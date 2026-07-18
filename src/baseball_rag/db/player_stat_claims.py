"""DuckDB verification for stat claims extracted from LLM biographies."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, cast

import duckdb

from baseball_rag.db.biography_stat_vocabulary import (
    BiographyStatDefinition,
    StatTable,
    biography_claim_stat_definitions,
    quote_identifier,
    retrosheet_adapter_stats,
    retrosheet_stat_column_candidates,
)
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.player_identity import resolve_retrosheet_id
from baseball_rag.provenance import compact_consensus_data_manifest

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
_STAT_TABLES: set[str] = {"batting", "pitching", "fielding"}


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
        text = payload.get("text")
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
class ClaimEvidence:
    """Evidence collected from one stat-claim source Adapter."""

    source_name: Literal["Lahman", "Retrosheet"]
    verification: PlayerStatVerification | RetrosheetStatVerification


@dataclass(frozen=True)
class PlayerStatConsensusVerification:
    """Consensus verification result comparing Lahman primary data to Retrosheet."""

    primary: PlayerStatVerification
    consensus_status: ConsensusStatus
    secondary: RetrosheetStatVerification

    def to_row(self) -> dict[str, Any]:
        row = self.primary.to_row()
        visible_sql, visible_params = _visible_consensus_query(self.primary, self.secondary)
        row["sql"] = visible_sql
        row["params"] = visible_params
        row.update(
            {
                "consensus_status": self.consensus_status,
                "primary_status": self.primary.status,
                "primary_actual_value": self.primary.actual_value,
                "primary_sql": self.primary.sql,
                "primary_params": self.primary.params,
                "secondary_status": self.secondary.status,
                "secondary_actual_value": self.secondary.actual_value,
                "secondary_table": self.secondary.table,
                "secondary_warning": self.secondary.warning,
                "secondary_sql": self.secondary.sql,
                "secondary_params": self.secondary.params,
                "primary_source": "Lahman",
                "secondary_source": "Retrosheet",
                "source_label": "Lahman and Retrosheet consensus",
                "source_detail": "Lahman primary evidence with Retrosheet consensus evidence",
            }
        )
        return row


def _visible_consensus_query(
    primary: PlayerStatVerification,
    secondary: RetrosheetStatVerification,
) -> tuple[str | None, list[object]]:
    if secondary.status == "verified" and primary.status in {
        "contradicted",
        "no_data",
        "unsupported_stat",
    }:
        return secondary.sql, secondary.params
    return primary.sql, primary.params


@dataclass(frozen=True)
class BiographyStatClaimConsensusPresentation:
    """Read model for presenting biography claim consensus evidence."""

    note: str
    warnings: list[str]
    rows: list[dict[str, Any]]
    summary: dict[str, Any]
    tables: list[str]
    sql: str | None
    source_detail: str
    data_manifest: dict[str, Any]


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


def shape_biography_stat_claim_consensus(
    verifications: list[Any],
) -> BiographyStatClaimConsensusPresentation:
    """Shape claim verification results for biography answer presentation."""
    rows = [_verification_row(verification) for verification in verifications]
    summary = biography_claim_summary(verifications)
    tables = verification_tables(verifications)
    return BiographyStatClaimConsensusPresentation(
        note=biography_verification_note(verifications),
        warnings=verification_warnings(verifications),
        rows=rows,
        summary=summary,
        tables=tables,
        sql=single_verification_sql(verifications),
        source_detail=consensus_source_detail(tables),
        data_manifest=consensus_data_manifest(),
    )


def biography_verification_note(verifications: list[Any]) -> str:
    contradicted = [
        verification
        for verification in verifications
        if consensus_category(verification) == "contradicted_by_all"
    ]
    conflicts = [
        verification
        for verification in verifications
        if consensus_category(verification) == "conflicts"
    ]
    unresolved = [
        verification
        for verification in verifications
        if verification_warning(verification)
        and consensus_category(verification) not in {"contradicted_by_all", "conflicts"}
    ]

    parts = [_verification_scorecard(biography_claim_summary(verifications))]
    if contradicted:
        summary = biography_claim_summary(verifications)
        verified_count = summary["verified_by_all"]
        prefix = (
            "Most stat claims were verified by all sources. "
            if verified_count > len(verifications) / 2
            else ""
        )
        parts.append(f"{prefix}{_contradiction_sentence(contradicted)}")
    if conflicts:
        parts.append(_conflict_sentence(conflicts))
    if unresolved:
        parts.append(_unverifiable_sentence(unresolved))
    return " ".join(parts)


def biography_claim_summary(verifications: list[Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_claims": len(verifications),
        "verified_by_all": 0,
        "primary_only": 0,
        "secondary_only": 0,
        "contradicted_by_all": 0,
        "conflicts": 0,
        "unsupported": 0,
    }
    for verification in verifications:
        category = consensus_category(verification)
        summary[category] += 1
    summary["score"] = (
        "passing"
        if summary["total_claims"] > 0 and summary["verified_by_all"] == summary["total_claims"]
        else "failing"
    )
    return summary


def verification_warnings(verifications: list[Any]) -> list[str]:
    return [
        warning for verification in verifications if (warning := verification_warning(verification))
    ]


def consensus_category(verification: Any) -> str:
    row = _verification_row(verification)
    status = str(row.get("consensus_status") or row.get("status") or "").casefold()
    if status in {"verified_by_all", "verified_all", "verified"}:
        return "verified_by_all"
    if status in {"primary_only", "verified_primary_only", "lahman_only"}:
        return "primary_only"
    if status in {"secondary_only", "verified_secondary_only", "retrosheet_only"}:
        return "secondary_only"
    if status in {"contradicted_by_all", "contradicted_all", "contradicted"}:
        return "contradicted_by_all"
    if status in {"conflict", "conflicts", "conflicting", "source_conflict"}:
        return "conflicts"
    if status in {"unsupported", "unsupported_stat", "invalid_value", "no_data"}:
        return "unsupported"

    primary_status = str(row.get("primary_status") or "").casefold()
    secondary_status = str(row.get("secondary_status") or "").casefold()
    if primary_status == "verified" and secondary_status == "verified":
        return "verified_by_all"
    if primary_status == "verified" and secondary_status in {"", "no_data", "unsupported"}:
        return "primary_only"
    if secondary_status == "verified" and primary_status in {"", "no_data", "unsupported"}:
        return "secondary_only"
    if primary_status == "contradicted" and secondary_status == "contradicted":
        return "contradicted_by_all"
    if primary_status and secondary_status and primary_status != secondary_status:
        return "conflicts"
    return "unsupported"


def verification_warning(verification: Any) -> str | None:
    row = _verification_row(verification)
    category = consensus_category(verification)
    if category in {"verified_by_all", "primary_only", "secondary_only"}:
        return None
    warning = row.get("warning") or row.get("secondary_warning")
    return str(warning) if warning else None


def verification_tables(verifications: list[Any]) -> list[str]:
    tables = sorted(
        {
            str(_verification_row(verification).get("table"))
            for verification in verifications
            if _verification_row(verification).get("table")
        }
    )
    return tables or ["people"]


def single_verification_sql(verifications: list[Any]) -> str | None:
    sql_values = {
        sql
        for verification in verifications
        if (sql := _visible_verification_sql(_verification_row(verification)))
    }
    if len(sql_values) == 1:
        return str(next(iter(sql_values)))
    return None


def _visible_verification_sql(row: dict[str, Any]) -> str | None:
    consensus_status = str(row.get("consensus_status") or "").casefold()
    primary_status = str(row.get("primary_status") or "").casefold()
    secondary_status = str(row.get("secondary_status") or "").casefold()
    if (
        row.get("secondary_sql")
        and secondary_status == "verified"
        and (
            consensus_status in {"verified_secondary_only", "secondary_only", "conflict"}
            or primary_status in {"", "no_data", "unsupported", "unsupported_stat"}
        )
    ):
        return str(row["secondary_sql"])
    return cast(str | None, row.get("sql") or row.get("primary_sql") or row.get("secondary_sql"))


def consensus_source_detail(tables: list[str]) -> str:
    return (
        f"Tables: {', '.join(tables)}. "
        "Primary source: Lahman-derived local Hugging Face NeuML/baseballdata CSVs. "
        "Secondary source: Retrosheet consensus evidence exposed by the claim verifier."
    )


def consensus_data_manifest() -> dict[str, Any]:
    return compact_consensus_data_manifest()


def _verification_scorecard(summary: dict[str, Any]) -> str:
    return (
        f"Stat claim consensus: total claims {summary['total_claims']}, "
        f"verified by all {summary['verified_by_all']}, "
        f"primary only {summary['primary_only']}, "
        f"secondary only {summary['secondary_only']}, "
        f"contradicted by all {summary['contradicted_by_all']}, "
        f"conflicts {summary['conflicts']}, "
        f"unsupported {summary['unsupported']}. "
        f"Score: {summary['score']} "
        f"({summary['verified_by_all']}/{summary['total_claims']} verified by all)."
    )


def _contradiction_sentence(verifications: list[Any]) -> str:
    count_label = (
        "One stat claim was"
        if len(verifications) == 1
        else f"{len(verifications)} stat claims were"
    )
    details = "; ".join(_contradiction_detail(verification) for verification in verifications)
    return f"{count_label} contradicted by Lahman and Retrosheet: {details}."


def _contradiction_detail(verification: Any) -> str:
    row = _verification_row(verification)
    stat = row.get("stat")
    claimed_value = row.get("claimed_value")
    actual_value = _consensus_actual_value(row)
    scope = _verification_scope_label(row)
    return (
        f"{stat} was claimed as {_format_claim_value(claimed_value)}, "
        f"but Lahman/Retrosheet consensus has {_format_claim_value(actual_value)} for {scope}"
    )


def _conflict_sentence(verifications: list[Any]) -> str:
    details = "; ".join(_conflict_detail(verification) for verification in verifications)
    if len(verifications) == 1:
        return f"One stat claim had conflicting Lahman and Retrosheet evidence: {details}."
    return (
        f"{len(verifications)} stat claims had conflicting Lahman and Retrosheet evidence: "
        f"{details}."
    )


def _conflict_detail(verification: Any) -> str:
    row = _verification_row(verification)
    stat = row.get("stat")
    claimed_value = _format_claim_value(row.get("claimed_value"))
    primary_value = _format_claim_value(row.get("primary_actual_value"))
    secondary_value = _format_claim_value(row.get("secondary_actual_value"))
    return (
        f"{stat} was claimed as {claimed_value}, "
        f"Lahman has {primary_value}, and Retrosheet has {secondary_value}"
    )


def _unverifiable_sentence(verifications: list[Any]) -> str:
    details = "; ".join(_unverifiable_detail(verification) for verification in verifications)
    if len(verifications) == 1:
        return f"One stat claim was not verifiable against Lahman and Retrosheet: {details}."
    return (
        f"{len(verifications)} stat claims were not verifiable against Lahman and Retrosheet: "
        f"{details}."
    )


def _unverifiable_detail(verification: Any) -> str:
    row = _verification_row(verification)
    stat = row.get("stat")
    value = _format_claim_value(row.get("claimed_value"))
    status = str(row.get("status") or "").casefold()
    if status == "unsupported_stat":
        return (
            f"{stat} was claimed as {value}, "
            "but Lahman/Retrosheet consensus verification does not support that stat"
        )
    if status == "invalid_value":
        return f"{stat} value {value} could not be interpreted as a number"
    if status == "no_data":
        scope = _verification_scope_label(row)
        return (
            f"{stat} was claimed as {value}, but Lahman/Retrosheet had no {scope} row to verify it"
        )
    if row.get("primary_status") == "contradicted":
        actual_value = _format_claim_value(row.get("primary_actual_value"))
        return (
            f"{stat} was claimed as {value}, "
            f"Lahman has {actual_value}, and Retrosheet did not verify it"
        )
    if consensus_category(verification) == "primary_only":
        return f"{stat} was claimed as {value}, and only Lahman verified it"
    if consensus_category(verification) == "secondary_only":
        return f"{stat} was claimed as {value}, and only Retrosheet verified it"
    return f"{stat} was claimed as {value}, but Lahman/Retrosheet could not verify it"


def _format_claim_value(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _verification_row(verification: Any) -> dict[str, Any]:
    to_row = getattr(verification, "to_row", None)
    if callable(to_row):
        row = dict(to_row())
    elif isinstance(verification, dict):
        row = dict(verification)
    else:
        claim = getattr(verification, "claim", None)
        row = {
            "stat": getattr(claim, "stat", getattr(verification, "stat", None)),
            "claimed_value": getattr(claim, "value", getattr(verification, "claimed_value", None)),
            "actual_value": getattr(verification, "actual_value", None),
            "year": getattr(claim, "year", getattr(verification, "year", None)),
            "scope": getattr(
                claim,
                "resolved_scope",
                getattr(verification, "scope", None),
            ),
            "text": getattr(claim, "text", getattr(verification, "text", None)),
            "status": getattr(verification, "status", None),
            "table": getattr(verification, "table", None),
            "warning": getattr(verification, "warning", None),
        }

    row.setdefault("primary_source", "Lahman")
    row.setdefault("secondary_source", "Retrosheet")
    row.setdefault("source_label", "Lahman and Retrosheet consensus")
    row.setdefault("source_detail", "Lahman primary evidence with Retrosheet consensus evidence")
    return row


def _consensus_actual_value(row: dict[str, Any]) -> Any:
    actual = row.get("actual_value")
    if actual is not None:
        return actual
    primary = row.get("primary_actual_value")
    secondary = row.get("secondary_actual_value")
    if primary == secondary:
        return primary
    return primary if primary is not None else secondary


def _verification_scope_label(row: dict[str, Any]) -> str:
    scope = row.get("scope") or "career"
    year = row.get("year")
    return str(scope) if year is None else f"{scope} {year}"


def _verify_one_claim_consensus(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    claim: PlayerStatClaim,
) -> PlayerStatConsensusVerification:
    primary_evidence = _lahman_evidence(conn, player_id, claim)
    secondary_evidence = _retrosheet_evidence(conn, player_id, claim)
    primary = cast(PlayerStatVerification, primary_evidence.verification)
    secondary = cast(RetrosheetStatVerification, secondary_evidence.verification)
    consensus_status = _consensus_status(primary, secondary)
    return PlayerStatConsensusVerification(
        primary=primary,
        consensus_status=consensus_status,
        secondary=secondary,
    )


def _lahman_evidence(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    claim: PlayerStatClaim,
) -> ClaimEvidence:
    return ClaimEvidence("Lahman", _verify_one_claim(conn, player_id, claim))


def _retrosheet_evidence(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    claim: PlayerStatClaim,
) -> ClaimEvidence:
    return ClaimEvidence("Retrosheet", _verify_one_retrosheet_claim(conn, player_id, claim))


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

    last_lookup: tuple[BiographyStatDefinition, str, list[object]] | None = None
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
    stat_def: BiographyStatDefinition,
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


def _candidate_stat_definitions(claim: PlayerStatClaim) -> list[BiographyStatDefinition]:
    return biography_claim_stat_definitions(
        claim.stat,
        table=claim.table,
        text=claim.text,
    )


def _lookup_player_stat(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
    stat_def: BiographyStatDefinition,
    claim: PlayerStatClaim,
) -> tuple[tuple | None, str, list[object]]:
    alias = {"batting": "b", "pitching": "pi", "fielding": "f"}[stat_def.table]
    expr = stat_def.aggregate_expression(alias)
    having_clause = f"{expr} IS NOT NULL"

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
    retro_id, warning = resolve_retrosheet_id(conn, player_id)
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
    stat_def: BiographyStatDefinition,
    claim: PlayerStatClaim,
) -> tuple[tuple | None, str | None, list[object], str | None, str | None]:
    table = f"retrosheet_{stat_def.table}"
    if not _table_exists(conn, table):
        return None, None, [], table, f"Retrosheet table {table} is not available."

    alias = {"batting": "rb", "pitching": "rp", "fielding": "rf"}[stat_def.table]
    player_column = _first_existing_column(
        conn,
        table,
        (
            "retroID",
            "retro_id",
            "retrosheet_id",
            "player_id",
            "id",
            "ID",
            "batter",
            "pitcher",
            "fielder",
        ),
    )
    if player_column is None:
        return None, None, [], table, f"Retrosheet table {table} has no player id column."

    year_expr = _retrosheet_year_expression(conn, table, alias)
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
    having_clause = " AND ".join(having_parts)
    filter_clause = _retrosheet_filter_clause(conn, table, alias)

    if claim.resolved_scope == "season":
        if claim.year is None:
            return (
                None,
                "Season Retrosheet lookup skipped because no year was supplied",
                [],
                table,
                None,
            )
        if year_expr is None:
            return None, None, [], table, f"Retrosheet table {table} has no season column."
        sql = f"""
        SELECT {expr} AS stat_value
        FROM {table} {alias}
        WHERE {alias}.{player_column} = ?
          AND {year_expr} = ?
          {filter_clause}
        GROUP BY {alias}.{player_column}, {year_expr}
        HAVING {having_clause}
        """
        params: list[object] = [retro_id, claim.year]
    else:
        sql = f"""
        SELECT {expr} AS stat_value
        FROM {table} {alias}
        WHERE {alias}.{player_column} = ?
          {filter_clause}
        HAVING {having_clause}
        """
        params = [retro_id]
    return conn.execute(sql, params).fetchone(), sql, params, table, None


def _retrosheet_aggregate_expression(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    alias: str,
    stat_def: BiographyStatDefinition,
) -> str | None:
    column_map = {
        stat: column
        for stat in retrosheet_adapter_stats(stat_def.table)
        if (column := _retrosheet_stat_column(conn, table, stat_def.table, stat)) is not None
    }

    def resolve(field_identity: str) -> str:
        source, _, stat_name = field_identity.partition(".")
        if source.casefold() != stat_def.table:
            raise ValueError(f"Retrosheet {stat_def.table} cannot render {field_identity}.")
        column = column_map.get(stat_name.upper())
        if column is None:
            raise ValueError(f"Retrosheet {stat_def.table} cannot render {stat_name}.")
        return f"TRY_CAST({alias}.{column} AS DOUBLE)"

    try:
        return stat_def.aggregate_expression(alias, column_resolver=resolve)
    except ValueError:
        return None


def _retrosheet_filter_clause(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    alias: str,
) -> str:
    filters = []
    stattype_column = _first_existing_column(conn, table, ("stattype",))
    if stattype_column is not None:
        filters.append(f"LOWER(CAST({alias}.{stattype_column} AS VARCHAR)) = 'value'")
    gametype_column = _first_existing_column(conn, table, ("gametype",))
    if gametype_column is not None:
        filters.append(
            f"LOWER(CAST({alias}.{gametype_column} AS VARCHAR)) IN ('regular', 'playoff')"
        )
    if not filters:
        return ""
    return "AND " + "\n          AND ".join(filters)


def _retrosheet_year_expression(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    alias: str,
) -> str | None:
    year_column = _first_existing_column(conn, table, ("yearID", "year_id", "season", "year"))
    if year_column is not None:
        return f"{alias}.{year_column}"
    date_column = _first_existing_column(conn, table, ("date", "game_date"))
    if date_column is not None:
        return f"TRY_CAST(SUBSTR(CAST({alias}.{date_column} AS VARCHAR), 1, 4) AS INTEGER)"
    return None


def _retrosheet_stat_column(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    stat_table: StatTable,
    stat: str,
) -> str | None:
    candidates = retrosheet_stat_column_candidates(stat_table, stat) or (stat,)
    return _first_existing_column(conn, table, candidates)


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
