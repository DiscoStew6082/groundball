"""Deterministic SQL assembly from typed freeform intents."""

from baseball_rag.db.freeform_types import AssembledSQL, QuerySpec
from baseball_rag.db.stat_registry import StatTable, get_stat, supported_tables


def _leader_condition(tbl: StatTable, stat: str) -> str:
    """Return the WHERE clause fragment for a league-wide leader condition."""
    stat_def = get_stat(stat, table=tbl)
    outer = stat_def.expression(tbl)
    inner_expr = stat_def.expression("b2")
    aggregate = "MAX" if stat_def.higher_is_better else "MIN"
    inner = (
        f"SELECT {aggregate}({inner_expr}) FROM {tbl} b2 "
        f"WHERE b2.yearID = {tbl}.yearID AND b2.lgID = {tbl}.lgID"
    )
    if stat_def.min_sample_clause:
        inner += f" AND {stat_def.min_sample_clause.format(alias='b2')}"

    return f"{outer} = ({inner})"


def _assemble_sql(intent: QuerySpec) -> AssembledSQL:
    """Build parameterized SQL deterministically from a QuerySpec."""
    if not intent.stat_tables:
        raise ValueError("intent.stat_tables cannot be empty")

    union_parts: list[str] = []
    params: list[object] = []

    for tbl in intent.stat_tables:
        if tbl not in supported_tables():
            raise ValueError(f"Unsupported stat table '{tbl}'")
        join_conditions = [f"p.playerID = {tbl}.playerID"]

        if intent.team_name_pattern is not None:
            from_part = (
                f"SELECT DISTINCT p.nameFirst, p.nameLast "
                f"FROM people p "
                f"JOIN {tbl} ON {' AND '.join(join_conditions)} "
                f"JOIN teams t ON {tbl}.teamID = t.teamID "
                f"AND t.name ILIKE ?"
            )
            params.append(f"%{intent.team_name_pattern}%")
        else:
            from_part = (
                f"SELECT DISTINCT p.nameFirst, p.nameLast "
                f"FROM people p "
                f"JOIN {tbl} ON {' AND '.join(join_conditions)}"
            )

        where_parts: list[str] = []
        if intent.year_value is not None:
            where_parts.append(f"{tbl}.yearID = ?")
            params.append(intent.year_value)

        for stat in intent.leader_stats:
            where_parts.append(_leader_condition(tbl, stat))

        if where_parts:
            from_part += " WHERE " + " AND ".join(where_parts)

        union_parts.append(from_part)

    if len(union_parts) == 1:
        return AssembledSQL(union_parts[0], params)
    return AssembledSQL("\nUNION\n".join(union_parts), params)
