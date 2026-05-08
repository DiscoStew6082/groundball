"""Central registry of SQL-addressable baseball statistics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

StatTable = Literal["batting", "pitching", "fielding"]


@dataclass(frozen=True)
class StatDefinition:
    """A whitelisted statistic that can be referenced in generated SQL."""

    canonical: str
    table: StatTable
    column: str | None
    sql_expr: str | None = None
    aggregate_sql_expr: str | None = None
    min_sample_clause: str | None = None
    aggregate_min_sample_clause: str | None = None
    higher_is_better: bool = True

    def expression(self, alias: str) -> str:
        """Return a SQL expression for this stat using a trusted table alias."""
        if self.sql_expr is not None:
            return self.sql_expr.format(alias=alias)
        if self.column is None:
            raise ValueError(f"Stat {self.canonical} has no column or expression")
        return f"{alias}.{quote_identifier(self.column)}"

    def aggregate_expression(self, alias: str) -> str:
        """Return a SQL aggregate expression for this stat over grouped rows."""
        if self.aggregate_sql_expr is not None:
            return self.aggregate_sql_expr.format(alias=alias)
        return f"SUM({self.expression(alias)})"

    def aggregate_sample_clause(self, alias: str) -> str | None:
        """Return a HAVING-compatible qualification guard for aggregate queries."""
        if self.aggregate_min_sample_clause is not None:
            return self.aggregate_min_sample_clause.format(alias=alias)
        if self.min_sample_clause is not None:
            return self.min_sample_clause.format(alias=alias)
        return None


def quote_identifier(identifier: str) -> str:
    """Quote a trusted SQL identifier for DuckDB."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


_REGISTRY: dict[str, StatDefinition] = {
    "HR": StatDefinition("HR", "batting", "HR"),
    "RBI": StatDefinition("RBI", "batting", "RBI"),
    "H": StatDefinition("H", "batting", "H"),
    "AB": StatDefinition("AB", "batting", "AB"),
    "R": StatDefinition("R", "batting", "R"),
    "2B": StatDefinition("2B", "batting", "2B"),
    "3B": StatDefinition("3B", "batting", "3B"),
    "SB": StatDefinition("SB", "batting", "SB"),
    "BB": StatDefinition("BB", "batting", "BB"),
    "SO": StatDefinition("SO", "batting", "SO"),
    "AVG": StatDefinition(
        "AVG",
        "batting",
        None,
        sql_expr="CAST({alias}.H AS DOUBLE) / NULLIF({alias}.AB, 0)",
        aggregate_sql_expr="CAST(SUM({alias}.H) AS DOUBLE) / NULLIF(SUM({alias}.AB), 0)",
        min_sample_clause="{alias}.AB >= 100",
        aggregate_min_sample_clause="SUM({alias}.AB) >= 100",
    ),
    "OPS": StatDefinition(
        "OPS",
        "batting",
        None,
        sql_expr=(
            "(CAST(COALESCE({alias}.H, 0) + COALESCE({alias}.BB, 0) + "
            "COALESCE({alias}.HBP, 0) AS DOUBLE) / "
            "NULLIF(COALESCE({alias}.AB, 0) + COALESCE({alias}.BB, 0) + "
            "COALESCE({alias}.HBP, 0) + COALESCE({alias}.SF, 0), 0)) + "
            '(CAST((COALESCE({alias}.H, 0) - COALESCE({alias}."2B", 0) - '
            'COALESCE({alias}."3B", 0) - COALESCE({alias}.HR, 0)) + '
            '2 * COALESCE({alias}."2B", 0) + 3 * COALESCE({alias}."3B", 0) + '
            "4 * COALESCE({alias}.HR, 0) AS DOUBLE) / "
            "NULLIF({alias}.AB, 0))"
        ),
        aggregate_sql_expr=(
            "(CAST(SUM(COALESCE({alias}.H, 0) + COALESCE({alias}.BB, 0) + "
            "COALESCE({alias}.HBP, 0)) AS DOUBLE) / "
            "NULLIF(SUM(COALESCE({alias}.AB, 0) + COALESCE({alias}.BB, 0) + "
            "COALESCE({alias}.HBP, 0) + COALESCE({alias}.SF, 0)), 0)) + "
            '(CAST(SUM((COALESCE({alias}.H, 0) - COALESCE({alias}."2B", 0) - '
            'COALESCE({alias}."3B", 0) - COALESCE({alias}.HR, 0)) + '
            '2 * COALESCE({alias}."2B", 0) + 3 * COALESCE({alias}."3B", 0) + '
            "4 * COALESCE({alias}.HR, 0)) AS DOUBLE) / "
            "NULLIF(SUM({alias}.AB), 0))"
        ),
        min_sample_clause="{alias}.AB >= 100",
        aggregate_min_sample_clause="SUM({alias}.AB) >= 100",
    ),
    "W": StatDefinition("W", "pitching", "W"),
    "L": StatDefinition("L", "pitching", "L"),
    "G": StatDefinition("G", "pitching", "G"),
    "GS": StatDefinition("GS", "pitching", "GS"),
    "SV": StatDefinition("SV", "pitching", "SV"),
    "ERA": StatDefinition(
        "ERA",
        "pitching",
        "ERA",
        aggregate_sql_expr="27.0 * SUM({alias}.ER) / NULLIF(SUM({alias}.IPouts), 0)",
        min_sample_clause="{alias}.IPouts >= 300",
        aggregate_min_sample_clause="SUM({alias}.IPouts) >= 300",
        higher_is_better=False,
    ),
    "WHIP": StatDefinition(
        "WHIP",
        "pitching",
        None,
        sql_expr="CAST({alias}.BB + {alias}.H AS DOUBLE) / NULLIF({alias}.IPouts / 3.0, 0)",
        aggregate_sql_expr=(
            "CAST(SUM({alias}.BB + {alias}.H) AS DOUBLE) / NULLIF(SUM({alias}.IPouts) / 3.0, 0)"
        ),
        min_sample_clause="{alias}.IPouts >= 300",
        aggregate_min_sample_clause="SUM({alias}.IPouts) >= 300",
        higher_is_better=False,
    ),
    "PO": StatDefinition("PO", "fielding", "PO"),
}

_ALIASES = {
    "K": "SO",
    "STRIKEOUTS": "SO",
    "HITS": "H",
    "HOMER": "HR",
    "HOMERS": "HR",
    "HOME_RUNS": "HR",
    "RBI": "RBI",
    "RBIS": "RBI",
    "RUNS_BATTED_IN": "RBI",
    "RUN_BATTED_IN": "RBI",
    "BAT_AVG": "AVG",
    "BATTING_AVERAGE": "AVG",
    "ON_BASE_PLUS_SLUGGING": "OPS",
    "PUTOUT": "PO",
    "PUTOUTS": "PO",
    "STOLEN_BASE": "SB",
    "STOLEN_BASES": "SB",
    "WINS": "W",
    "LOSSES": "L",
}

_TEXT_ALIASES: dict[str, str] = {
    "2b": "2B",
    "3b": "3B",
    "ab": "AB",
    "avg": "AVG",
    "bat avg": "AVG",
    "batting average": "AVG",
    "bb": "BB",
    "base on balls": "BB",
    "bases on balls": "BB",
    "era": "ERA",
    "earned run average": "ERA",
    "h": "H",
    "hits": "H",
    "home run": "HR",
    "home runs": "HR",
    "homer": "HR",
    "homers": "HR",
    "hr": "HR",
    "hrs": "HR",
    "k": "SO",
    "losses": "L",
    "on-base plus slugging": "OPS",
    "ops": "OPS",
    "po": "PO",
    "putout": "PO",
    "putouts": "PO",
    "rbi": "RBI",
    "rbis": "RBI",
    "run batted in": "RBI",
    "runs": "R",
    "runs batted in": "RBI",
    "sb": "SB",
    "so": "SO",
    "stolen base": "SB",
    "stolen bases": "SB",
    "strikeouts": "SO",
    "whip": "WHIP",
    "wins": "W",
}


def get_stat(stat: str, *, table: StatTable | None = None) -> StatDefinition:
    """Return a whitelisted stat definition or raise ValueError."""
    canonical = normalize_stat(stat)
    definition = _REGISTRY.get(canonical)
    if definition is None:
        supported = ", ".join(supported_stats())
        raise ValueError(f"Unsupported stat '{stat}'. Supported stats: {supported}")
    if table is not None and definition.table != table:
        raise ValueError(f"Stat '{canonical}' belongs to {definition.table}, not {table}")
    return definition


def normalize_stat(stat: str) -> str:
    """Normalize common user/model stat spellings to registry keys."""
    key = stat.strip().upper().replace(" ", "_").replace("-", "_")
    return _ALIASES.get(key, key)


def stat_aliases() -> Mapping[str, str]:
    """Return user-facing text aliases mapped to canonical stat names."""
    return dict(_TEXT_ALIASES)


def find_stat_in_text(text: str) -> str | None:
    """Return the first supported stat alias mentioned in free text."""
    lower_text = text.lower()
    for phrase, canonical in sorted(_TEXT_ALIASES.items(), key=lambda item: -len(item[0])):
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", lower_text):
            return canonical
    return None


def supported_stat_prompt_list() -> list[str]:
    """Return canonical stats and aliases useful in LLM routing prompts."""
    return sorted({*supported_stats(), *(_ALIASES.keys())})


def supported_stats(table: StatTable | None = None) -> list[str]:
    """Return supported canonical stat names."""
    return sorted(
        name for name, definition in _REGISTRY.items() if table is None or definition.table == table
    )


def supported_tables() -> set[StatTable]:
    """Return tables that may be used by generated query specs."""
    return {"batting", "pitching", "fielding"}
