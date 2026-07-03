"""Central registry of SQL-addressable baseball statistics."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from baseball_rag.stat_mentions import (
    for_routing,
    infer_stat_table_hint,
    stat_normalization_aliases,
)

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

    def expression(self, alias: str, *, adapter: "StatSqlAdapter | None" = None) -> str:
        """Return a SQL expression for this stat using a trusted table alias."""
        if adapter is not None:
            return _source_expression(self, alias, adapter)
        if self.sql_expr is not None:
            return self.sql_expr.format(alias=alias)
        if self.column is None:
            raise ValueError(f"Stat {self.canonical} has no column or expression")
        return f"{alias}.{quote_identifier(self.column)}"

    def aggregate_expression(self, alias: str, *, adapter: "StatSqlAdapter | None" = None) -> str:
        """Return a SQL aggregate expression for this stat over grouped rows."""
        if adapter is not None:
            return _source_aggregate_expression(self, alias, adapter)
        if self.aggregate_sql_expr is not None:
            return self.aggregate_sql_expr.format(alias=alias)
        return f"SUM({self.expression(alias)})"

    def aggregate_sample_clause(
        self,
        alias: str,
        *,
        adapter: "StatSqlAdapter | None" = None,
    ) -> str | None:
        """Return a HAVING-compatible qualification guard for aggregate queries."""
        if adapter is not None:
            return _source_aggregate_sample_clause(self, alias, adapter)
        if self.aggregate_min_sample_clause is not None:
            return self.aggregate_min_sample_clause.format(alias=alias)
        if self.min_sample_clause is not None:
            return self.min_sample_clause.format(alias=alias)
        return None

    def sample_clause(
        self,
        alias: str,
        *,
        aggregate: bool = False,
        threshold: int | str | None = None,
        adapter: "StatSqlAdapter | None" = None,
    ) -> str | None:
        """Return a qualification guard, optionally replacing the default threshold."""
        clause = (
            self.aggregate_sample_clause(alias, adapter=adapter)
            if aggregate
            else (
                _source_sample_clause(self, alias, adapter)
                if adapter is not None
                else _local_sample_clause(self, alias)
            )
        )
        if clause is None or threshold is None:
            return clause
        return re.sub(r">=\s*\d+(?:\.\d+)?", f">= {threshold}", clause, count=1)


@dataclass(frozen=True)
class StatSqlAdapter:
    """Column vocabulary for rendering stat SQL against a source table."""

    table: StatTable
    columns: Mapping[str, str]
    numeric_columns: bool = False

    def column(self, alias: str, stat: str) -> str:
        column = self.columns.get(stat.upper())
        if column is None:
            raise ValueError(f"{self.table} source cannot render {stat}")
        expression = f"{alias}.{column}"
        if self.numeric_columns:
            return f"TRY_CAST({expression} AS DOUBLE)"
        return expression


def quote_identifier(identifier: str) -> str:
    """Quote a trusted SQL identifier for DuckDB."""
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _source_expression(definition: StatDefinition, alias: str, adapter: StatSqlAdapter) -> str:
    stat = definition.canonical
    if stat == "AVG":
        return (
            f"CAST({adapter.column(alias, 'H')} AS DOUBLE) / "
            f"NULLIF({adapter.column(alias, 'AB')}, 0)"
        )
    if stat == "OPS":
        hit = adapter.column(alias, "H")
        walk = adapter.column(alias, "BB")
        hbp = adapter.column(alias, "HBP")
        at_bat = adapter.column(alias, "AB")
        sacrifice_fly = adapter.column(alias, "SF")
        double = adapter.column(alias, "2B")
        triple = adapter.column(alias, "3B")
        homer = adapter.column(alias, "HR")
        return (
            f"(CAST(COALESCE({hit}, 0) + COALESCE({walk}, 0) + "
            f"COALESCE({hbp}, 0) AS DOUBLE) / "
            f"NULLIF(COALESCE({at_bat}, 0) + COALESCE({walk}, 0) + "
            f"COALESCE({hbp}, 0) + COALESCE({sacrifice_fly}, 0), 0)) + "
            f"(CAST((COALESCE({hit}, 0) - COALESCE({double}, 0) - "
            f"COALESCE({triple}, 0) - COALESCE({homer}, 0)) + "
            f"2 * COALESCE({double}, 0) + 3 * COALESCE({triple}, 0) + "
            f"4 * COALESCE({homer}, 0) AS DOUBLE) / NULLIF({at_bat}, 0))"
        )
    if stat == "ERA":
        return (
            f"27.0 * {adapter.column(alias, 'ER')} / NULLIF({adapter.column(alias, 'IPOUTS')}, 0)"
        )
    if stat == "WHIP":
        return (
            f"CAST({adapter.column(alias, 'BB')} + {adapter.column(alias, 'H')} AS DOUBLE) / "
            f"NULLIF({adapter.column(alias, 'IPOUTS')} / 3.0, 0)"
        )
    return adapter.column(alias, definition.column or definition.canonical)


def _source_aggregate_expression(
    definition: StatDefinition,
    alias: str,
    adapter: StatSqlAdapter,
) -> str:
    stat = definition.canonical
    if stat == "AVG":
        return (
            f"CAST(SUM({adapter.column(alias, 'H')}) AS DOUBLE) / "
            f"NULLIF(SUM({adapter.column(alias, 'AB')}), 0)"
        )
    if stat == "OPS":
        hit = adapter.column(alias, "H")
        walk = adapter.column(alias, "BB")
        hbp = adapter.column(alias, "HBP")
        at_bat = adapter.column(alias, "AB")
        sacrifice_fly = adapter.column(alias, "SF")
        double = adapter.column(alias, "2B")
        triple = adapter.column(alias, "3B")
        homer = adapter.column(alias, "HR")
        return (
            f"(CAST(SUM(COALESCE({hit}, 0) + COALESCE({walk}, 0) + "
            f"COALESCE({hbp}, 0)) AS DOUBLE) / "
            f"NULLIF(SUM(COALESCE({at_bat}, 0) + COALESCE({walk}, 0) + "
            f"COALESCE({hbp}, 0) + COALESCE({sacrifice_fly}, 0)), 0)) + "
            f"(CAST(SUM((COALESCE({hit}, 0) - COALESCE({double}, 0) - "
            f"COALESCE({triple}, 0) - COALESCE({homer}, 0)) + "
            f"2 * COALESCE({double}, 0) + 3 * COALESCE({triple}, 0) + "
            f"4 * COALESCE({homer}, 0)) AS DOUBLE) / "
            f"NULLIF(SUM({at_bat}), 0))"
        )
    if stat == "ERA":
        return (
            f"27.0 * SUM({adapter.column(alias, 'ER')}) / "
            f"NULLIF(SUM({adapter.column(alias, 'IPOUTS')}), 0)"
        )
    if stat == "WHIP":
        return (
            f"CAST(SUM({adapter.column(alias, 'BB')} + {adapter.column(alias, 'H')}) "
            f"AS DOUBLE) / NULLIF(SUM({adapter.column(alias, 'IPOUTS')}) / 3.0, 0)"
        )
    return f"SUM({adapter.column(alias, definition.column or stat)})"


def _source_aggregate_sample_clause(
    definition: StatDefinition,
    alias: str,
    adapter: StatSqlAdapter,
) -> str | None:
    if definition.canonical in {"AVG", "OPS"}:
        return f"SUM({adapter.column(alias, 'AB')}) >= 100"
    if definition.canonical in {"ERA", "WHIP"}:
        return f"SUM({adapter.column(alias, 'IPOUTS')}) >= 300"
    return None


def _source_sample_clause(
    definition: StatDefinition,
    alias: str,
    adapter: StatSqlAdapter,
) -> str | None:
    if definition.canonical in {"AVG", "OPS"}:
        return f"{adapter.column(alias, 'AB')} >= 100"
    if definition.canonical in {"ERA", "WHIP"}:
        return f"{adapter.column(alias, 'IPOUTS')} >= 300"
    return None


def _local_sample_clause(definition: StatDefinition, alias: str) -> str | None:
    if definition.min_sample_clause is None:
        return None
    return definition.min_sample_clause.format(alias=alias)


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

_ALIASES = dict(stat_normalization_aliases())
_TEXT_ALIASES = dict(for_routing().aliases)


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
    return for_routing().find_stat(text)


def infer_stat_table(stat: str, *, text: str | None = None) -> StatTable | None:
    """Infer a contextual stat table from surrounding natural-language text."""
    return infer_stat_table_hint(normalize_stat(stat), text=text)


def supported_stat_prompt_list() -> list[str]:
    """Return canonical stats and aliases useful in LLM routing prompts."""
    return sorted({*supported_stats(), *(_ALIASES.keys())})


def stat_formula_notes() -> str:
    """Return prompt-facing notes for derived stat formulas and ranking semantics."""
    lines: list[str] = []
    for definition in sorted(_REGISTRY.values(), key=lambda item: (item.table, item.canonical)):
        if definition.sql_expr is None and definition.aggregate_sql_expr is None:
            continue
        ranking = (
            "higher values rank better"
            if definition.higher_is_better
            else "lower values rank better"
        )
        parts = [
            f"  {definition.table}: {definition.canonical} = "
            f"{definition.expression(definition.table)}"
        ]
        sample_clause = definition.min_sample_clause or definition.aggregate_min_sample_clause
        if sample_clause is not None:
            parts.append(f"minimum sample: {sample_clause.format(alias='').lstrip('.')}")
        parts.append(ranking)
        lines.append("; ".join(parts))
    return "\n".join(lines)


def supported_stats(table: StatTable | None = None) -> list[str]:
    """Return supported canonical stat names."""
    return sorted(
        name for name, definition in _REGISTRY.items() if table is None or definition.table == table
    )


def supported_tables() -> set[StatTable]:
    """Return tables that may be used by generated query specs."""
    return {"batting", "pitching", "fielding"}
