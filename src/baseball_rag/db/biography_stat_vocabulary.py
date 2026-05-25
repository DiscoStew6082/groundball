"""Vocabulary for biography stat-claim extraction and verification."""

from __future__ import annotations

from collections.abc import Mapping

from baseball_rag.db.stat_registry import (
    StatDefinition,
    StatTable,
    get_stat,
    infer_stat_table,
    normalize_stat,
)
from baseball_rag.stat_mentions import for_biography_claims

_BIOGRAPHY_CLAIM_VOCABULARY = for_biography_claims()
_SUPPORTED_BIOGRAPHY_CLAIM_STATS = _BIOGRAPHY_CLAIM_VOCABULARY.supported_stats

_CONTEXTUAL_STAT_DEFINITIONS: dict[tuple[str, StatTable], StatDefinition] = {
    ("SO", "pitching"): StatDefinition("SO", "pitching", "SO"),
}

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


def supported_biography_claim_stats() -> list[str]:
    """Return the stats intentionally exposed to the biography JSON contract."""
    return sorted(_SUPPORTED_BIOGRAPHY_CLAIM_STATS)


def normalize_biography_claim_stat(stat: str) -> str:
    """Normalize biography claim stat aliases to the contract's canonical stats."""
    canonical = _BIOGRAPHY_CLAIM_VOCABULARY.normalize(stat)
    return normalize_stat(canonical)


def is_supported_biography_claim_stat(stat: str) -> bool:
    """Return True when a stat belongs to the biography claim contract."""
    return normalize_biography_claim_stat(stat) in _SUPPORTED_BIOGRAPHY_CLAIM_STATS


def biography_claim_stat_definitions(
    stat: str,
    *,
    table: StatTable | None = None,
    text: str | None = None,
) -> list[StatDefinition]:
    """Return registry definitions allowed for a biography stat claim."""
    canonical = normalize_biography_claim_stat(stat)
    if canonical not in _SUPPORTED_BIOGRAPHY_CLAIM_STATS:
        raise ValueError(f"Unsupported biography stat claim {stat!r}.")

    table_hint = table or infer_stat_table(stat, text=text)
    if table_hint is None:
        return [get_stat(canonical)]

    primary = _stat_definition_for_table(canonical, table_hint)
    candidates = [primary]
    if table is None:
        default = get_stat(canonical)
        if default.table != primary.table:
            candidates.append(default)
    return candidates


def _stat_definition_for_table(canonical: str, table: StatTable) -> StatDefinition:
    try:
        return get_stat(canonical, table=table)
    except ValueError:
        contextual = _CONTEXTUAL_STAT_DEFINITIONS.get((canonical, table))
        if contextual is not None:
            return contextual
        raise


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
    return _RETROSHEET_COLUMN_CANDIDATES.get(table, {}).get(normalize_stat(stat), ())


def retrosheet_adapter_stats(table: StatTable) -> tuple[str, ...]:
    """Return source stats needed to render Retrosheet stat formulas for a table."""
    return tuple(_RETROSHEET_COLUMN_CANDIDATES.get(table, {}))
