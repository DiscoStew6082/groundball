"""Trusted catalog-driven compilation for validated Query Plans."""

from __future__ import annotations

from typing import Any

from baseball_rag.query.contracts import (
    All,
    Compare,
    InteractivePage,
    Literal,
    Not,
    Predicate,
    QueryPlanV1,
    Scalar,
    ValueRef,
)
from baseball_rag.query.contracts import (
    Any as AnyPredicate,
)
from baseball_rag.query.registry import (
    _promoted_value_bindings,
    field_by_identity,
    grain_by_identity,
    promoted_value_by_identity,
    relationship_by_identity,
    source_by_identity,
)


def compile_raw_plan(
    plan: QueryPlanV1,
    relation: str,
    primary_key: tuple[str, ...],
) -> tuple[str, tuple[Scalar, ...]]:
    """Compile a validated single-source raw plan."""
    selected_parts: list[str] = []
    selected_aliases: list[str] = []
    selected_columns: set[str] = set()
    for identity in plan.selections:
        field = field_by_identity(identity)
        if field is None or field.source != plan.source:
            raise ValueError(f"Plan references stale field {identity!r}.")
        selected_parts.append(f"{_quote(field.column)} AS {_quote(field.identity)}")
        selected_aliases.append(_quote(field.identity))
        selected_columns.add(field.column)

    hidden_keys: list[str] = []
    if plan.grain == "raw_rows":
        for index, column in enumerate(primary_key):
            if column in selected_columns:
                continue
            alias = f"__key_{index}"
            selected_parts.append(f"{_quote(column)} AS {_quote(alias)}")
            hidden_keys.append(_quote(alias))

    where_sql = ""
    bound_values: tuple[Scalar, ...] = ()
    if plan.predicate is not None:
        predicate_sql, predicate_values = _compile_raw_predicate(plan.source, plan.predicate)
        where_sql = f" WHERE {predicate_sql}"
        bound_values = tuple(predicate_values)

    group_sql = ""
    if plan.grain == "group_by":
        grouping_columns = []
        for identity in plan.groupings:
            field = field_by_identity(identity)
            if field is None:
                raise ValueError(f"Plan references stale grouping field {identity!r}.")
            grouping_columns.append(_quote(field.column))
        group_sql = f" GROUP BY {', '.join(grouping_columns)}"

    base_sql = f"SELECT {', '.join(selected_parts)} FROM {_quote(relation)}{where_sql}{group_sql}"
    order_parts = []
    for spec in plan.ordering:
        direction = "ASC" if spec.direction == "ascending" else "DESC"
        nulls = "FIRST" if spec.nulls == "first" else "LAST"
        order_parts.append(f"{_quote(spec.value)} {direction} NULLS {nulls}")
    if plan.grain == "raw_rows":
        order_parts.extend(f"{key} ASC NULLS LAST" for key in hidden_keys)
        for column in primary_key:
            field_identity = f"{plan.source}.{column}"
            if field_identity in plan.selections and not any(
                spec.value == field_identity for spec in plan.ordering
            ):
                order_parts.append(f"{_quote(field_identity)} ASC NULLS LAST")
    else:
        for alias in selected_aliases:
            if not any(alias == _quote(spec.value) for spec in plan.ordering):
                order_parts.append(f"{alias} ASC NULLS LAST")

    page_predicate = "TRUE"
    if isinstance(plan.output, InteractivePage):
        first_row = plan.output.offset + 1
        last_row = plan.output.offset + plan.output.size
        page_predicate = f"__row_number BETWEEN {first_row} AND {last_row}"
    sql = (
        f"WITH published_rows AS ({base_sql}), "
        f"ordered_rows AS (SELECT {', '.join(selected_aliases)}, "
        f"ROW_NUMBER() OVER (ORDER BY {', '.join(order_parts)}) AS __row_number "
        f"FROM published_rows), "
        f"match_count AS (SELECT COUNT(*) AS __matched_count FROM published_rows) "
        f"SELECT {', '.join(selected_aliases)}, match_count.__matched_count, "
        f"ordered_rows.__row_number IS NOT NULL AS __row_present "
        f"FROM match_count LEFT JOIN ordered_rows ON {page_predicate} "
        f"ORDER BY ordered_rows.__row_number"
    )
    return sql, bound_values


def _compile_raw_predicate(source: str, predicate: Predicate) -> tuple[str, list[Scalar]]:
    if isinstance(predicate, Compare):
        field = field_by_identity(predicate.value)
        if field is None or field.source != source:
            raise ValueError(f"Plan references stale filter field {predicate.value!r}.")
        column = _quote(field.column)
        literal = predicate.literal
        if predicate.operator == "one_of":
            values = list(_cast_tuple(literal))
            return f"{column} IN ({', '.join('?' for _ in values)})", values
        if predicate.operator == "range":
            values = list(_cast_tuple(literal))
            return f"{column} BETWEEN ? AND ?", values
        operators = {
            "equals": "=",
            "not_equals": "<>",
            "greater_than": ">",
            "greater_or_equal": ">=",
            "less_than": "<",
            "less_or_equal": "<=",
        }
        sql_operator = operators.get(predicate.operator)
        if sql_operator is None:
            raise ValueError(f"Plan uses unsupported operator {predicate.operator!r}.")
        return f"{column} {sql_operator} ?", [_cast_scalar(literal)]
    if isinstance(predicate, (All, AnyPredicate)):
        compiled = [_compile_raw_predicate(source, item) for item in predicate.predicates]
        connector = " AND " if isinstance(predicate, All) else " OR "
        return (
            "(" + connector.join(sql for sql, _ in compiled) + ")",
            [value for _, values in compiled for value in values],
        )
    if isinstance(predicate, Not):
        sql, values = _compile_raw_predicate(source, predicate.predicate)
        return f"NOT ({sql})", values
    raise ValueError("Unsupported raw predicate kind.")


def _cast_tuple(literal: Literal) -> tuple[Scalar, ...]:
    if not isinstance(literal, tuple):
        raise ValueError("Plan operator requires a literal sequence.")
    return literal


def _cast_scalar(literal: Literal) -> Scalar:
    if not isinstance(literal, (str, int, float, bool, type(None))):
        raise ValueError("Plan operator requires one scalar literal.")
    return literal


def compile_promoted_plan(plan: QueryPlanV1) -> tuple[str, tuple[Scalar, ...]]:
    """Compile one validated promoted plan from catalog declarations only."""
    grain = grain_by_identity(plan.grain)
    source = source_by_identity(plan.source)
    if grain is None or source is None:
        raise ValueError("Plan is not a published promoted plan.")
    references = set(plan.selections)
    references.update(_predicate_values(plan.predicate))
    references.update(spec.value for spec in plan.ordering)
    if plan.ranking is not None:
        references.add(plan.ranking.value)
        references.update(plan.ranking.within)

    grain_keys = grain.dimensions
    dimensions = set(grain_keys)
    dimensions.update(
        identity
        for identity in references
        if (value := promoted_value_by_identity(identity)) is not None and value.kind == "dimension"
    )

    source_aliases, joins = _compile_relationships(plan)
    dimension_sql = [
        _dimension_expression(identity, source_aliases) for identity in sorted(dimensions)
    ]
    group_sql = [
        expression
        for identity in sorted(dimensions)
        for expression in _dimension_group_expressions(identity, source_aliases)
    ]

    component_fields = _component_fields(references)
    aggregate_sql = []
    for field_identity in sorted(component_fields):
        field = field_by_identity(field_identity)
        if field is None or field.source not in source_aliases:
            raise ValueError(f"Promoted calculation references stale field {field_identity!r}.")
        aggregate_sql.append(
            f"SUM(COALESCE({_field_sql(field_identity, source_aliases)}, 0)) AS "
            f"{_quote(_component_alias(field_identity))}"
        )

    for identity in sorted(references):
        value = promoted_value_by_identity(identity)
        if value is None or value.kind not in {"count", "component"} or value.source_field is None:
            continue
        field = field_by_identity(value.source_field)
        if field is None:
            raise ValueError(f"Promoted value {identity!r} has a stale source field.")
        aggregate_sql.append(
            f"SUM(COALESCE({_field_sql(value.source_field, source_aliases)}, 0)) "
            f"AS {_quote(identity)}"
        )

    rollup_parts = [*dimension_sql, *aggregate_sql]
    rollups = (
        f"SELECT {', '.join(rollup_parts)} FROM {_quote(source.relation)} "
        f"AS {source_aliases[plan.source]} "
        f"{' '.join(joins)} GROUP BY {', '.join(group_sql)}"
    )

    base_calculations = []
    derived_calculations = []
    required_calculations = _calculation_values(references)
    for value in _promoted_value_bindings():
        if value.identity not in required_calculations or value.expression is None:
            continue
        rendered = _compile_expression(dict(value.expression))
        item = f"{rendered} AS {_quote(value.identity)}"
        if _expression_uses_value(dict(value.expression)):
            derived_calculations.append(item)
        else:
            base_calculations.append(item)
    calculated = "SELECT rollups.*"
    if base_calculations:
        calculated += ", " + ", ".join(base_calculations)
    calculated += " FROM rollups"
    derived = "SELECT calculated.*"
    if derived_calculations:
        derived += ", " + ", ".join(derived_calculations)
    derived += " FROM calculated"

    pre_predicate, post_predicate = _split_window_predicate(plan.predicate)
    pre_predicate_sql = "TRUE"
    bound_values: list[Scalar] = []
    if pre_predicate is not None:
        pre_predicate_sql, bound_values = _compile_alias_predicate(pre_predicate)
    eligible = f"SELECT * FROM derived WHERE {pre_predicate_sql}"

    window_sql = []
    for identity in sorted(references):
        value = promoted_value_by_identity(identity)
        if value is None or value.kind != "window" or value.window_base is None:
            continue
        partition = ", ".join(_quote(item) for item in value.window_partition)
        base_expression = _quote(value.window_base)
        if value.window_eligibility is not None:
            minimum = _eligibility_floor(plan.predicate, value.window_eligibility)
            if minimum is None:
                raise ValueError(
                    f"Window value {identity!r} requires an explicit eligibility floor."
                )
            base_expression = (
                f"CASE WHEN {_quote(value.window_eligibility)} >= ? THEN {base_expression} END"
            )
            bound_values.append(minimum)
        window_sql.append(
            f"MAX({base_expression}) OVER (PARTITION BY {partition}) AS {_quote(identity)}"
        )
    windowed = "SELECT eligible.*"
    if window_sql:
        windowed += ", " + ", ".join(window_sql)
    windowed += " FROM eligible"

    post_predicate_sql = "TRUE"
    if post_predicate is not None:
        post_predicate_sql, post_values = _compile_alias_predicate(post_predicate)
        bound_values.extend(post_values)
    filtered = f"SELECT * FROM windowed WHERE {post_predicate_sql}"

    source_name = "filtered"
    ranking_cte = ""
    rank_filter = ""
    if plan.ranking is not None:
        rank = plan.ranking
        direction = "DESC" if rank.direction == "highest" else "ASC"
        nulls = "LAST" if rank.direction == "highest" else "FIRST"
        partition = (
            "PARTITION BY " + ", ".join(_quote(item) for item in rank.within) + " "
            if rank.within
            else ""
        )
        rank_function = "RANK" if rank.tie_policy == "include_ties" else "ROW_NUMBER"
        rank_order = f"{_quote(rank.value)} {direction} NULLS {nulls}"
        if rank.tie_policy == "exact_count":
            rank_order += ", " + ", ".join(f"{_quote(key)} ASC NULLS LAST" for key in grain_keys)
        ranking_cte = (
            f", ranked AS (SELECT filtered.*, {rank_function}() OVER ({partition}"
            f"ORDER BY {rank_order}) AS __rank "
            f"FROM filtered)"
        )
        source_name = "ranked"
        rank_filter = f" WHERE __rank <= {rank.count}"

    order_parts = _ordering(plan, grain_keys)
    ordered = (
        f"SELECT {', '.join(_quote(item) for item in plan.selections)}, "
        f"ROW_NUMBER() OVER (ORDER BY {', '.join(order_parts)}) AS __row_number "
        f"FROM {source_name}{rank_filter}"
    )
    page_predicate = "TRUE"
    if isinstance(plan.output, InteractivePage):
        first_row = plan.output.offset + 1
        last_row = plan.output.offset + plan.output.size
        page_predicate = f"__row_number BETWEEN {first_row} AND {last_row}"
    selected_aliases = ", ".join(_quote(item) for item in plan.selections)
    sql = (
        f"WITH rollups AS ({rollups}), calculated AS ({calculated}), "
        f"derived AS ({derived}), eligible AS ({eligible}), windowed AS ({windowed}), "
        f"filtered AS ({filtered}){ranking_cte}, "
        f"ordered_rows AS ({ordered}), "
        f"match_count AS (SELECT COUNT(*) AS __matched_count FROM {source_name}"
        f"{rank_filter}) "
        f"SELECT {selected_aliases}, match_count.__matched_count, "
        f"ordered_rows.__row_number IS NOT NULL AS __row_present "
        f"FROM match_count LEFT JOIN ordered_rows ON {page_predicate} "
        f"ORDER BY ordered_rows.__row_number"
    )
    return sql, tuple(bound_values)


def _compile_relationships(plan: QueryPlanV1) -> tuple[dict[str, str], list[str]]:
    aliases = {plan.source: "s0"}
    joins: list[str] = []
    for index, identity in enumerate(plan.relationships, start=1):
        relationship = relationship_by_identity(identity)
        if relationship is None:
            raise ValueError(f"Plan references stale relationship {identity!r}.")
        if relationship.left_source in aliases:
            joined_source = relationship.right_source
        elif relationship.right_source in aliases:
            joined_source = relationship.left_source
        else:
            raise ValueError(f"Relationship {identity!r} is disconnected from the plan source.")
        binding = source_by_identity(joined_source)
        if binding is None:
            raise ValueError(f"Relationship {identity!r} references a stale source.")
        aliases[joined_source] = f"s{index}"
        conditions = [
            f"{_field_sql(left, aliases)} = {_field_sql(right, aliases)}"
            for left, right in relationship.keys
        ]
        joins.append(
            f"JOIN {_quote(binding.relation)} AS {aliases[joined_source]} "
            f"ON {' AND '.join(conditions)}"
        )
    return aliases, joins


def _dimension_expression(identity: str, aliases: dict[str, str]) -> str:
    value = promoted_value_by_identity(identity)
    if value is None or value.kind != "dimension":
        raise ValueError(f"Unknown promoted dimension {identity!r}.")
    if value.source_field is not None:
        expression = _field_sql(value.source_field, aliases)
    elif value.composition == "join_nonempty_space" and value.source_fields:
        arguments = ", ".join(
            f"COALESCE({_field_sql(field, aliases)}, '')" for field in value.source_fields
        )
        expression = f"trim(concat_ws(' ', {arguments}))"
    else:
        raise ValueError(f"Dimension {identity!r} has no catalog-owned composition.")
    return f"{expression} AS {_quote(identity)}"


def _dimension_group_expressions(identity: str, aliases: dict[str, str]) -> list[str]:
    value = promoted_value_by_identity(identity)
    if value is None or value.kind != "dimension":
        raise ValueError(f"Unknown promoted dimension {identity!r}.")
    fields = (value.source_field,) if value.source_field is not None else value.source_fields
    return [_field_sql(field, aliases) for field in fields]


def _field_sql(identity: str, aliases: dict[str, str]) -> str:
    field = field_by_identity(identity)
    if field is None or field.source not in aliases:
        raise ValueError(f"Catalog field {identity!r} is not joined into this plan.")
    return f"{aliases[field.source]}.{_quote(field.column)}"


def _component_fields(references: set[str]) -> set[str]:
    fields: set[str] = set()
    pending = list(references)
    seen: set[str] = set()
    while pending:
        identity = pending.pop()
        if identity in seen:
            continue
        seen.add(identity)
        value = promoted_value_by_identity(identity)
        if value is None or value.kind != "calculation":
            continue
        fields.update(value.components)
        if value.expression is not None:
            pending.extend(_expression_values(dict(value.expression)))
    return fields


def _calculation_values(references: set[str]) -> set[str]:
    calculations: set[str] = set()
    pending = list(references)
    while pending:
        identity = pending.pop()
        if identity in calculations:
            continue
        value = promoted_value_by_identity(identity)
        if value is None or value.kind != "calculation" or value.expression is None:
            continue
        calculations.add(identity)
        pending.extend(_expression_values(dict(value.expression)))
    return calculations


def _compile_expression(expression: dict[str, Any]) -> str:
    if "field" in expression:
        return _quote(_component_alias(str(expression["field"])))
    if "value" in expression:
        return _quote(str(expression["value"]))
    if "constant" in expression:
        constant = expression["constant"]
        if not isinstance(constant, (int, float)) or isinstance(constant, bool):
            raise ValueError("Catalog calculation constants must be numeric.")
        return str(constant)
    operation = expression.get("op")
    arguments = [_compile_expression(item) for item in expression.get("args", [])]
    if operation == "add" and arguments:
        return "(" + " + ".join(arguments) + ")"
    if operation == "subtract" and arguments:
        return "(" + " - ".join(arguments) + ")"
    if operation == "multiply" and arguments:
        return "(" + " * ".join(arguments) + ")"
    if operation == "divide" and len(arguments) == 2:
        return f"(CAST({arguments[0]} AS DOUBLE) / NULLIF({arguments[1]}, 0))"
    raise ValueError(f"Unsupported catalog calculation operation {operation!r}.")


def _expression_values(expression: dict[str, Any]) -> set[str]:
    values = {str(expression["value"])} if "value" in expression else set()
    for item in expression.get("args", []):
        values.update(_expression_values(item))
    return values


def _expression_uses_value(expression: dict[str, Any]) -> bool:
    return bool(_expression_values(expression))


def _compile_alias_predicate(predicate: Predicate) -> tuple[str, list[Scalar]]:
    if isinstance(predicate, Compare):
        column = _quote(predicate.value)
        literal = predicate.literal
        if predicate.operator == "one_of":
            assert isinstance(literal, tuple)
            return f"{column} IN ({', '.join('?' for _ in literal)})", list(literal)
        if predicate.operator == "range":
            assert isinstance(literal, tuple)
            return f"{column} BETWEEN ? AND ?", list(literal)
        operators = {
            "equals": "=",
            "not_equals": "<>",
            "greater_than": ">",
            "greater_or_equal": ">=",
            "less_than": "<",
            "less_or_equal": "<=",
        }
        operator = operators[predicate.operator]
        assert not isinstance(literal, tuple)
        if isinstance(literal, ValueRef):
            return f"{column} {operator} {_quote(literal.identity)}", []
        return f"{column} {operator} ?", [literal]
    if isinstance(predicate, (All, AnyPredicate)):
        compiled = [_compile_alias_predicate(item) for item in predicate.predicates]
        connector = " AND " if isinstance(predicate, All) else " OR "
        return (
            "(" + connector.join(sql for sql, _ in compiled) + ")",
            [value for _, values in compiled for value in values],
        )
    if isinstance(predicate, Not):
        sql, values = _compile_alias_predicate(predicate.predicate)
        return f"NOT ({sql})", values
    raise ValueError("Unsupported promoted predicate kind.")


def _ordering(plan: QueryPlanV1, grain_keys: tuple[str, ...]) -> list[str]:
    parts: list[str] = []
    if plan.ordering:
        for spec in plan.ordering:
            direction = "ASC" if spec.direction == "ascending" else "DESC"
            nulls = "FIRST" if spec.nulls == "first" else "LAST"
            parts.append(f"{_quote(spec.value)} {direction} NULLS {nulls}")
    elif plan.ranking is not None:
        direction = "DESC" if plan.ranking.direction == "highest" else "ASC"
        parts.append(f"{_quote(plan.ranking.value)} {direction} NULLS LAST")
    for key in grain_keys:
        if not any(part.startswith(_quote(key) + " ") for part in parts):
            parts.append(f"{_quote(key)} ASC NULLS LAST")
    return parts


def _predicate_values(predicate: Predicate | None) -> set[str]:
    if predicate is None:
        return set()
    if isinstance(predicate, Compare):
        values = {predicate.value}
        if isinstance(predicate.literal, ValueRef):
            values.add(predicate.literal.identity)
        return values
    if isinstance(predicate, (All, AnyPredicate)):
        return set().union(*(_predicate_values(item) for item in predicate.predicates))
    return _predicate_values(predicate.predicate)


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _component_alias(identity: str) -> str:
    return f"__component_{identity}"


def _split_window_predicate(
    predicate: Predicate | None,
) -> tuple[Predicate | None, Predicate | None]:
    if predicate is None:
        return None, None
    if isinstance(predicate, All):
        pre: list[Predicate] = []
        post: list[Predicate] = []
        for child in predicate.predicates:
            (post if _uses_window_value(child) or _is_eligibility_floor(child) else pre).append(
                child
            )
        return (
            All(tuple(pre)) if len(pre) > 1 else (pre[0] if pre else None),
            All(tuple(post)) if len(post) > 1 else (post[0] if post else None),
        )
    return (None, predicate) if _uses_window_value(predicate) else (predicate, None)


def _uses_window_value(predicate: Predicate) -> bool:
    return any(
        (value := promoted_value_by_identity(identity)) is not None and value.kind == "window"
        for identity in _predicate_values(predicate)
    )


def _is_eligibility_floor(predicate: Predicate) -> bool:
    return (
        isinstance(predicate, Compare)
        and predicate.operator == "greater_or_equal"
        and any(
            value.window_eligibility == predicate.value
            for value in _promoted_value_bindings()
            if value.kind == "window"
        )
    )


def _eligibility_floor(predicate: Predicate | None, identity: str) -> Scalar | None:
    if predicate is None:
        return None
    if isinstance(predicate, Compare):
        if (
            predicate.value == identity
            and predicate.operator == "greater_or_equal"
            and not isinstance(predicate.literal, (tuple, ValueRef))
        ):
            return predicate.literal
        return None
    if isinstance(predicate, All):
        return next(
            (
                floor
                for item in predicate.predicates
                if (floor := _eligibility_floor(item, identity)) is not None
            ),
            None,
        )
    return None
