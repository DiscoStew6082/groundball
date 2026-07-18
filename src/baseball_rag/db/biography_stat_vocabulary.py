"""Vocabulary for biography stat-claim extraction and verification."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable, Literal, cast

from baseball_rag.query.registry import (
    field_by_identity,
    promoted_value_by_identity,
)
from baseball_rag.stat_mentions import for_biography_claims, infer_stat_table_hint

StatTable = Literal["batting", "pitching", "fielding"]
ColumnResolver = Callable[[str], str]

_BIOGRAPHY_CLAIM_VOCABULARY = for_biography_claims()
_BIOGRAPHY_CLAIM_IDENTITIES = (
    "batting.H",
    "batting.HR",
    "batting.RBI",
    "batting.SB",
    "batting.AVG",
    "batting.OPS",
    "pitching.W",
    "pitching.ERA",
    "pitching.WHIP",
    "batting.SO",
    "pitching.SO",
    "fielding.PO",
)
_DEFAULT_IDENTITIES = {
    "H": "batting.H",
    "HR": "batting.HR",
    "RBI": "batting.RBI",
    "SB": "batting.SB",
    "AVG": "batting.AVG",
    "OPS": "batting.OPS",
    "W": "pitching.W",
    "ERA": "pitching.ERA",
    "WHIP": "pitching.WHIP",
    "SO": "batting.SO",
    "PO": "fielding.PO",
}
_SUPPORTED_BIOGRAPHY_CLAIM_STATS = tuple(sorted(_DEFAULT_IDENTITIES))

_RETROSHEET_COLUMN_CANDIDATES: dict[StatTable, dict[str, tuple[str, ...]]] = {
    "batting": {
        "HR": ("b_hr", "HR"),
        "RBI": ("b_rbi", "RBI"),
        "H": ("b_h", "H"),
        "AB": ("b_ab", "AB"),
        "R": ("b_r", "R"),
        "2B": ("b_d", "2B"),
        "3B": ("b_t", "3B"),
        "SB": ("b_sb", "SB"),
        "BB": ("b_w", "BB"),
        "SO": ("b_k", "SO"),
        "HBP": ("b_hbp", "HBP"),
        "SF": ("b_sf", "SF"),
    },
    "pitching": {
        "W": ("wp", "W"),
        "L": ("lp", "L"),
        "GS": ("gs", "GS"),
        "SV": ("save", "SV"),
        "IPOUTS": ("p_ipouts", "IPouts"),
        "H": ("p_h", "H"),
        "ER": ("p_er", "ER"),
        "BB": ("p_w", "BB"),
        "SO": ("p_k", "SO"),
    },
    "fielding": {
        "PO": ("d_po", "PO"),
    },
}

_BIOGRAPHY_CLAIM_STAT_ALIASES = dict(_BIOGRAPHY_CLAIM_VOCABULARY.aliases)


@dataclass(frozen=True)
class BiographyStatDefinition:
    """Biography-facing projection of one published catalog value."""

    identity: str
    canonical: str
    table: StatTable
    source_field: str | None
    formula: str | None

    def aggregate_expression(
        self,
        alias: str,
        *,
        column_resolver: ColumnResolver | None = None,
    ) -> str:
        resolver = column_resolver or _lahman_column_resolver(alias)
        return _render_catalog_aggregate(self.identity, resolver)


def _definition(identity: str) -> BiographyStatDefinition:
    value = promoted_value_by_identity(identity)
    if value is None or identity not in _BIOGRAPHY_CLAIM_IDENTITIES:
        raise ValueError(f"Unsupported biography catalog value {identity!r}.")
    table = identity.partition(".")[0]
    if table not in {"batting", "pitching", "fielding"}:
        raise ValueError(f"Biography catalog value {identity!r} has no supported source.")
    return BiographyStatDefinition(
        identity=identity,
        canonical=identity.rsplit(".", 1)[-1],
        table=cast(StatTable, table),
        source_field=value.source_field,
        formula=value.formula,
    )


def supported_biography_claim_stats() -> list[str]:
    """Return the stats intentionally exposed to the biography JSON contract."""
    return sorted(_SUPPORTED_BIOGRAPHY_CLAIM_STATS)


def normalize_biography_claim_stat(stat: str) -> str:
    """Normalize biography claim stat aliases to the contract's canonical stats."""
    canonical = _BIOGRAPHY_CLAIM_VOCABULARY.normalize(stat)
    return canonical.strip().upper().replace(" ", "_").replace("-", "_")


def is_supported_biography_claim_stat(stat: str) -> bool:
    """Return True when a stat belongs to the biography claim contract."""
    return normalize_biography_claim_stat(stat) in _SUPPORTED_BIOGRAPHY_CLAIM_STATS


def biography_claim_stat_definitions(
    stat: str,
    *,
    table: StatTable | None = None,
    text: str | None = None,
) -> list[BiographyStatDefinition]:
    """Return published catalog values allowed for a biography stat claim."""
    canonical = normalize_biography_claim_stat(stat)
    if canonical not in _SUPPORTED_BIOGRAPHY_CLAIM_STATS:
        raise ValueError(f"Unsupported biography stat claim {stat!r}.")

    table_hint = table or infer_stat_table_hint(canonical, text=text)
    if table_hint is None:
        return [_definition(_DEFAULT_IDENTITIES[canonical])]

    primary = _stat_definition_for_table(canonical, table_hint)
    candidates = [primary]
    if table is None:
        default = _definition(_DEFAULT_IDENTITIES[canonical])
        if default.table != primary.table:
            candidates.append(default)
    return candidates


def _stat_definition_for_table(
    canonical: str,
    table: StatTable,
) -> BiographyStatDefinition:
    identity = f"{table}.{canonical}"
    if identity not in _BIOGRAPHY_CLAIM_IDENTITIES:
        raise ValueError(f"Stat {canonical!r} is not published for {table} biographies.")
    return _definition(identity)


def biography_claim_prompt_stat_list() -> str:
    """Return the biography claim stats formatted for prompt instructions."""
    stats = list(_SUPPORTED_BIOGRAPHY_CLAIM_STATS)
    return f"{', '.join(stats[:-1])}, or {stats[-1]}"


def biography_claim_stat_aliases() -> Mapping[str, str]:
    """Return user/model-facing stat spellings accepted for biography claims."""
    return dict(_BIOGRAPHY_CLAIM_STAT_ALIASES)


def biography_claim_stat_regex_source() -> str:
    """Return a regex alternation for supplied biography claim stat aliases."""
    return _BIOGRAPHY_CLAIM_VOCABULARY.regex_source()


def retrosheet_stat_column_candidates(table: StatTable, stat: str) -> tuple[str, ...]:
    """Return Retrosheet column candidates used for optional consensus evidence."""
    return _RETROSHEET_COLUMN_CANDIDATES.get(table, {}).get(
        normalize_biography_claim_stat(stat), ()
    )


def retrosheet_adapter_stats(table: StatTable) -> tuple[str, ...]:
    """Return source stats needed to render Retrosheet stat formulas for a table."""
    return tuple(_RETROSHEET_COLUMN_CANDIDATES.get(table, {}))


def quote_identifier(identifier: str) -> str:
    """Quote one catalog- or schema-discovered DuckDB identifier."""
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def _lahman_column_resolver(alias: str) -> ColumnResolver:
    def resolve(field_identity: str) -> str:
        field = field_by_identity(field_identity)
        if field is None:
            raise ValueError(f"Catalog calculation references stale field {field_identity!r}.")
        return f"{alias}.{quote_identifier(field.column)}"

    return resolve


def _render_catalog_aggregate(identity: str, resolve_column: ColumnResolver) -> str:
    value = promoted_value_by_identity(identity)
    if value is None:
        raise ValueError(f"Catalog calculation references stale value {identity!r}.")
    if value.source_field is not None:
        return _preserve_unknown_sum(resolve_column(value.source_field))
    if value.expression is None:
        raise ValueError(f"Catalog value {identity!r} has no aggregate expression.")
    return _render_expression(dict(value.expression), resolve_column)


def _render_expression(expression: dict[str, Any], resolve_column: ColumnResolver) -> str:
    if "field" in expression:
        return _preserve_unknown_sum(resolve_column(str(expression["field"])))
    if "value" in expression:
        return _render_catalog_aggregate(str(expression["value"]), resolve_column)
    if "constant" in expression:
        constant = expression["constant"]
        if not isinstance(constant, (int, float)) or isinstance(constant, bool):
            raise ValueError("Catalog calculation constants must be numeric.")
        return str(constant)
    operation = expression.get("op")
    arguments = [
        _render_expression(dict(item), resolve_column) for item in expression.get("args", [])
    ]
    if operation == "add" and arguments:
        return "(" + " + ".join(arguments) + ")"
    if operation == "subtract" and arguments:
        return "(" + " - ".join(arguments) + ")"
    if operation == "multiply" and arguments:
        return "(" + " * ".join(arguments) + ")"
    if operation == "divide" and len(arguments) == 2:
        return f"(CAST({arguments[0]} AS DOUBLE) / NULLIF({arguments[1]}, 0))"
    if operation == "baseball_innings" and len(arguments) == 1:
        return f"(FLOOR({arguments[0]} / 3) + ({arguments[0]} % 3) / 10.0)"
    raise ValueError(f"Unsupported catalog calculation operation {operation!r}.")


def _preserve_unknown_sum(expression: str) -> str:
    return f"CASE WHEN COUNT(*) = COUNT({expression}) THEN SUM({expression}) END"
