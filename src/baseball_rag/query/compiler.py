"""Trusted catalog-driven compilation for validated Query Plans."""

from __future__ import annotations

from typing import Any

from baseball_rag.query.contracts import (
    All,
    Compare,
    Export,
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
    combination_by_identity,
    direct_value_sources,
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
            "before": "<",
            "after": ">",
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


def compile_promoted_plan(
    plan: QueryPlanV1,
    *,
    include_match_aliases: bool = False,
) -> tuple[str, tuple[Scalar, ...]]:
    """Compile one validated promoted plan from catalog declarations only."""
    combination = next(
        (
            binding
            for identity in plan.relationships
            if (binding := combination_by_identity(identity)) is not None
        ),
        None,
    )
    if combination is not None:
        return _compile_composed_plan(plan, combination.sources)
    grain = grain_by_identity(plan.grain)
    source = source_by_identity(plan.source)
    if grain is None or source is None:
        raise ValueError("Plan is not a published promoted plan.")
    source_predicate, aggregate_predicate = _split_source_predicate(plan.predicate)
    references = set(plan.selections)
    references.update(plan.groupings)
    references.update(_predicate_values(aggregate_predicate))
    references.update(spec.value for spec in plan.ordering)
    if plan.ranking is not None:
        references.add(plan.ranking.value)
        references.update(plan.ranking.within)

    grain_keys = plan.groupings or grain.dimensions
    source_aliases, joins = _compile_relationships(plan)
    dimensions = set(grain_keys)
    dimensions.update(
        identity
        for identity in references
        if (value := promoted_value_by_identity(identity)) is not None
        and value.kind in {"dimension", "fact"}
    )

    dimension_sql = [
        _dimension_expression(identity, source_aliases, plan.source)
        for identity in sorted(dimensions)
    ]
    dimension_sql.extend(
        expression
        for identity in sorted(dimensions)
        for expression in _match_expressions(identity, source_aliases)
    )
    group_sql = [
        expression
        for identity in sorted(dimensions)
        for expression in _dimension_group_expressions(identity, source_aliases, plan.source)
    ]

    component_fields = _component_fields(references)
    aggregate_sql = []
    for field_identity in sorted(component_fields):
        field = field_by_identity(field_identity)
        if field is None or field.source not in source_aliases:
            raise ValueError(f"Promoted calculation references stale field {field_identity!r}.")
        aggregate_sql.append(
            f"{_preserve_unknown_sum(field_identity, source_aliases)} AS "
            f"{_quote(_component_alias(field_identity))}"
        )

    for identity in sorted(references):
        value = promoted_value_by_identity(identity)
        if value is None or value.kind not in {"count", "component"} or value.source_field is None:
            continue
        field = field_by_identity(value.source_field)
        if field is None:
            raise ValueError(f"Promoted value {identity!r} has a stale source field.")
        if value.null_policy != "preserve_unknown":
            raise ValueError(f"Promoted value {identity!r} has an unsupported null policy.")
        aggregate_sql.append(
            f"{_preserve_unknown_sum(value.source_field, source_aliases)} AS {_quote(identity)}"
        )

    rollup_parts = [*dimension_sql, *aggregate_sql]
    source_predicate_sql = "TRUE"
    bound_values: list[Scalar] = []
    if source_predicate is not None:
        source_predicate_sql, source_values = _compile_source_predicate(
            source_predicate,
            source_aliases,
            plan.source,
        )
        bound_values.extend(source_values)
    rollups = (
        f"SELECT {', '.join(rollup_parts)} FROM {_quote(source.relation)} "
        f"AS {source_aliases[plan.source]} "
        f"{' '.join(joins)} WHERE {source_predicate_sql} "
        f"GROUP BY {', '.join(group_sql)}"
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

    pre_predicate, post_predicate = _split_window_predicate(aggregate_predicate)
    pre_predicate_sql = "TRUE"
    if pre_predicate is not None:
        pre_predicate_sql, pre_values = _compile_alias_predicate(pre_predicate)
        bound_values.extend(pre_values)
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
    result_identities = list(plan.selections)
    if include_match_aliases:
        result_identities.extend(
            _match_alias(identity, index)
            for identity in sorted(references)
            for index in range(_match_expression_count(promoted_value_by_identity(identity)))
        )
    ordered = (
        f"SELECT {', '.join(_quote(item) for item in result_identities)}, "
        f"ROW_NUMBER() OVER (ORDER BY {', '.join(order_parts)}) AS __row_number "
        f"FROM {source_name}{rank_filter}"
    )
    page_predicate = "TRUE"
    if isinstance(plan.output, InteractivePage):
        first_row = plan.output.offset + 1
        last_row = plan.output.offset + plan.output.size
        page_predicate = f"__row_number BETWEEN {first_row} AND {last_row}"
    selected_aliases = ", ".join(_quote(item) for item in result_identities)
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


def _compile_composed_plan(
    plan: QueryPlanV1,
    allowed_sources: tuple[str, ...],
) -> tuple[str, tuple[Scalar, ...]]:
    grain = grain_by_identity(plan.grain)
    if grain is None or plan.groupings:
        raise ValueError("Composed queries require one named shared grain.")
    references = set(plan.selections)
    references.update(_predicate_values(plan.predicate))
    references.update(spec.value for spec in plan.ordering)
    if plan.ranking is not None:
        references.add(plan.ranking.value)
        references.update(plan.ranking.within)
    fact_sources = {plan.source}
    for identity in references:
        direct_sources = direct_value_sources(identity) & set(allowed_sources)
        if len(direct_sources) == 1:
            fact_sources.update(direct_sources)
        elif plan.source in direct_sources:
            fact_sources.add(plan.source)
    if len(fact_sources) < 2:
        raise ValueError("Composed plan does not reference multiple fact sources.")
    if any(
        (value := promoted_value_by_identity(identity)) is not None and value.kind == "window"
        for identity in references
    ):
        raise ValueError("Window values are not published across fact-source combinations.")

    ordered_sources = [plan.source, *sorted(fact_sources - {plan.source})]
    source_selections: dict[str, set[str]] = {
        source: set(grain.dimensions) for source in ordered_sources
    }
    column_owner: dict[str, str] = {identity: plan.source for identity in grain.dimensions}
    for identity in references:
        direct_sources = direct_value_sources(identity) & fact_sources
        owner = (
            plan.source
            if plan.source in direct_sources or not direct_sources
            else sorted(direct_sources)[0]
        )
        source_selections[owner].add(identity)
        column_owner[identity] = owner

    subqueries: list[str] = []
    bound_values: list[Scalar] = []
    lookup_relationships = [
        identity for identity in plan.relationships if combination_by_identity(identity) is None
    ]
    for index, source in enumerate(ordered_sources):
        relationships = tuple(
            identity
            for identity in lookup_relationships
            if (relationship := relationship_by_identity(identity)) is not None
            and source in {relationship.left_source, relationship.right_source}
        )
        subplan = QueryPlanV1(
            version=plan.version,
            catalog_revision=plan.catalog_revision,
            source=source,
            grain=plan.grain,
            selections=tuple(sorted(source_selections[source])),
            predicate=None,
            relationships=relationships,
            output=Export(),
        )
        sql, values = compile_promoted_plan(subplan, include_match_aliases=True)
        subqueries.append(f"fact_{index} AS ({sql})")
        bound_values.extend(values)

    source_index = {source: index for index, source in enumerate(ordered_sources)}
    projections = []
    projected_identities = set(grain.dimensions) | references
    for identity in sorted(projected_identities):
        owner = column_owner.get(identity, plan.source)
        projections.append(f"f{source_index[owner]}.{_quote(identity)} AS {_quote(identity)}")
    for identity in sorted(_predicate_values(plan.predicate)):
        owner = column_owner.get(identity, plan.source)
        value = promoted_value_by_identity(identity)
        projections.extend(
            f"f{source_index[owner]}.{_quote(_match_alias(identity, index))} AS "
            f"{_quote(_match_alias(identity, index))}"
            for index in range(_match_expression_count(value))
        )
    joins = []
    for index in range(1, len(ordered_sources)):
        conditions = " AND ".join(
            f"f0.{_quote(key)} = f{index}.{_quote(key)}" for key in grain.dimensions
        )
        joins.append(f"JOIN fact_{index} AS f{index} ON {conditions}")
    combined = f"SELECT {', '.join(projections)} FROM fact_0 AS f0 {' '.join(joins)}"

    predicate_sql = "TRUE"
    if plan.predicate is not None:
        predicate_sql, predicate_values = _compile_alias_predicate(plan.predicate)
        bound_values.extend(predicate_values)
    filtered = f"SELECT * FROM combined WHERE {predicate_sql}"

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
        function = "RANK" if rank.tie_policy == "include_ties" else "ROW_NUMBER"
        rank_order = f"{_quote(rank.value)} {direction} NULLS {nulls}"
        if rank.tie_policy == "exact_count":
            rank_order += ", " + ", ".join(
                f"{_quote(key)} ASC NULLS LAST" for key in grain.dimensions
            )
        ranking_cte = (
            f", ranked AS (SELECT filtered.*, {function}() OVER ({partition}"
            f"ORDER BY {rank_order}) AS __rank FROM filtered)"
        )
        source_name = "ranked"
        rank_filter = f" WHERE __rank <= {rank.count}"

    order_parts = _ordering(plan, grain.dimensions)
    selected = ", ".join(_quote(item) for item in plan.selections)
    ordered = (
        f"SELECT {selected}, ROW_NUMBER() OVER (ORDER BY {', '.join(order_parts)}) "
        f"AS __row_number FROM {source_name}{rank_filter}"
    )
    page_predicate = "TRUE"
    if isinstance(plan.output, InteractivePage):
        page_predicate = (
            f"__row_number BETWEEN {plan.output.offset + 1} "
            f"AND {plan.output.offset + plan.output.size}"
        )
    sql = (
        f"WITH {', '.join(subqueries)}, combined AS ({combined}), "
        f"filtered AS ({filtered}){ranking_cte}, ordered_rows AS ({ordered}), "
        f"match_count AS (SELECT COUNT(*) AS __matched_count FROM {source_name}"
        f"{rank_filter}) SELECT {selected}, match_count.__matched_count, "
        f"ordered_rows.__row_number IS NOT NULL AS __row_present FROM match_count "
        f"LEFT JOIN ordered_rows ON {page_predicate} ORDER BY ordered_rows.__row_number"
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
            if relationship.cardinality == "left_one_to_right_many":
                raise ValueError(f"Relationship {identity!r} would multiply the plan's fact rows.")
        elif relationship.right_source in aliases:
            joined_source = relationship.left_source
            if relationship.cardinality == "right_one_to_left_many":
                raise ValueError(f"Relationship {identity!r} would multiply the plan's fact rows.")
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


def _dimension_expression(
    identity: str,
    aliases: dict[str, str],
    anchor_source: str,
) -> str:
    expression = _dimension_raw_expression(identity, aliases, anchor_source)
    return f"{expression} AS {_quote(identity)}"


def _dimension_raw_expression(
    identity: str,
    aliases: dict[str, str],
    anchor_source: str,
) -> str:
    value = promoted_value_by_identity(identity)
    if value is None or value.kind not in {"dimension", "fact"}:
        raise ValueError(f"Unknown promoted non-aggregatable value {identity!r}.")
    if value.composition == "year" and value.source_field is not None:
        expression = f"EXTRACT(YEAR FROM {_field_sql(value.source_field, aliases)})"
    elif anchor_source in value.source_bindings:
        expression = _field_sql(value.source_bindings[anchor_source], aliases)
    elif value.source_field is not None:
        expression = _field_sql(value.source_field, aliases)
    elif value.composition == "join_nonempty_space" and value.source_fields:
        arguments = ", ".join(
            f"COALESCE({_field_sql(field, aliases)}, '')" for field in value.source_fields
        )
        expression = f"trim(concat_ws(' ', {arguments}))"
    else:
        raise ValueError(f"Dimension {identity!r} has no catalog-owned composition.")
    return expression


def _dimension_group_expressions(
    identity: str,
    aliases: dict[str, str],
    anchor_source: str,
) -> list[str]:
    value = promoted_value_by_identity(identity)
    if value is None or value.kind not in {"dimension", "fact"}:
        raise ValueError(f"Unknown promoted non-aggregatable value {identity!r}.")
    if value.composition == "year" and value.source_field is not None:
        return [f"EXTRACT(YEAR FROM {_field_sql(value.source_field, aliases)})"]
    fields: tuple[str, ...]
    if anchor_source in value.source_bindings:
        fields = (value.source_bindings[anchor_source],)
    else:
        fields = (value.source_field,) if value.source_field is not None else value.source_fields
    return [
        *(_field_sql(field, aliases) for field in fields),
        *(_field_sql(field, aliases) for field in value.match_fields),
    ]


def _match_expressions(identity: str, aliases: dict[str, str]) -> list[str]:
    value = promoted_value_by_identity(identity)
    if value is None:
        return []
    expressions = [
        f"{_field_sql(field, aliases)} AS {_quote(_match_alias(identity, index))}"
        for index, field in enumerate(value.match_fields)
    ]
    if value.match_composition == "join_nonempty_space" and value.match_fields:
        arguments = ", ".join(
            f"COALESCE({_field_sql(field, aliases)}, '')" for field in value.match_fields
        )
        expressions.append(
            f"trim(concat_ws(' ', {arguments})) AS "
            f"{_quote(_match_alias(identity, len(value.match_fields)))}"
        )
    return expressions


def _raw_match_expressions(identity: str, aliases: dict[str, str]) -> list[str]:
    value = promoted_value_by_identity(identity)
    if value is None:
        return []
    expressions = [_field_sql(field, aliases) for field in value.match_fields]
    if value.match_composition == "join_nonempty_space" and value.match_fields:
        arguments = ", ".join(
            f"COALESCE({_field_sql(field, aliases)}, '')" for field in value.match_fields
        )
        expressions.append(f"trim(concat_ws(' ', {arguments}))")
    return expressions


def _match_expression_count(value: Any) -> int:
    if value is None:
        return 0
    return len(value.match_fields) + (
        1 if value.match_composition == "join_nonempty_space" and value.match_fields else 0
    )


def _field_sql(identity: str, aliases: dict[str, str]) -> str:
    field = field_by_identity(identity)
    if field is None or field.source not in aliases:
        raise ValueError(f"Catalog field {identity!r} is not joined into this plan.")
    return f"{aliases[field.source]}.{_quote(field.column)}"


def _preserve_unknown_sum(identity: str, aliases: dict[str, str]) -> str:
    expression = _field_sql(identity, aliases)
    return f"CASE WHEN COUNT(*) = COUNT({expression}) THEN SUM({expression}) END"


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
    if operation == "baseball_innings" and len(arguments) == 1:
        return f"(FLOOR({arguments[0]} / 3) + ({arguments[0]} % 3) / 10.0)"
    raise ValueError(f"Unsupported catalog calculation operation {operation!r}.")


def _expression_values(expression: dict[str, Any]) -> set[str]:
    values = {str(expression["value"])} if "value" in expression else set()
    for item in expression.get("args", []):
        values.update(_expression_values(item))
    return values


def _expression_uses_value(expression: dict[str, Any]) -> bool:
    return bool(_expression_values(expression))


def _compile_source_predicate(
    predicate: Predicate,
    aliases: dict[str, str],
    anchor_source: str,
) -> tuple[str, list[Scalar]]:
    if isinstance(predicate, Compare):
        columns = [
            _dimension_raw_expression(predicate.value, aliases, anchor_source),
            *_raw_match_expressions(predicate.value, aliases),
        ]
        literal = predicate.literal
        if isinstance(literal, ValueRef):
            target = _dimension_raw_expression(literal.identity, aliases, anchor_source)
            operator = "=" if predicate.operator == "equals" else "<>"
            return f"{columns[0]} {operator} {target}", []
        if predicate.operator == "one_of":
            assert isinstance(literal, tuple)
            placeholders = ", ".join("?" for _ in literal)
            return (
                "(" + " OR ".join(f"{item} IN ({placeholders})" for item in columns) + ")",
                [item for _ in columns for item in literal],
            )
        if predicate.operator == "range":
            assert isinstance(literal, tuple)
            return f"{columns[0]} BETWEEN ? AND ?", list(literal)
        operators = {
            "equals": "=",
            "not_equals": "<>",
            "greater_than": ">",
            "greater_or_equal": ">=",
            "less_than": "<",
            "less_or_equal": "<=",
            "before": "<",
            "after": ">",
        }
        operator = operators[predicate.operator]
        assert not isinstance(literal, tuple)
        if predicate.operator == "equals" and len(columns) > 1:
            return (
                "(" + " OR ".join(f"{item} = ?" for item in columns) + ")",
                [literal] * len(columns),
            )
        return f"{columns[0]} {operator} ?", [literal]
    if isinstance(predicate, (All, AnyPredicate)):
        compiled = [
            _compile_source_predicate(item, aliases, anchor_source) for item in predicate.predicates
        ]
        connector = " AND " if isinstance(predicate, All) else " OR "
        return (
            "(" + connector.join(sql for sql, _ in compiled) + ")",
            [value for _, values in compiled for value in values],
        )
    if isinstance(predicate, Not):
        sql, values = _compile_source_predicate(predicate.predicate, aliases, anchor_source)
        return f"NOT ({sql})", values
    raise ValueError("Unsupported source predicate kind.")


def _compile_alias_predicate(predicate: Predicate) -> tuple[str, list[Scalar]]:
    if isinstance(predicate, Compare):
        column = _quote(predicate.value)
        value = promoted_value_by_identity(predicate.value)
        match_columns = [
            _quote(_match_alias(predicate.value, index))
            for index in range(_match_expression_count(value))
        ]
        literal = predicate.literal
        if predicate.operator == "one_of":
            assert isinstance(literal, tuple)
            columns = [column, *match_columns]
            placeholders = ", ".join("?" for _ in literal)
            return (
                "(" + " OR ".join(f"{item} IN ({placeholders})" for item in columns) + ")",
                [item for _ in columns for item in literal],
            )
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
            "before": "<",
            "after": ">",
        }
        operator = operators[predicate.operator]
        assert not isinstance(literal, tuple)
        if isinstance(literal, ValueRef):
            return f"{column} {operator} {_quote(literal.identity)}", []
        if predicate.operator == "equals" and match_columns:
            columns = [column, *match_columns]
            return (
                "(" + " OR ".join(f"{item} = ?" for item in columns) + ")",
                [literal] * len(columns),
            )
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


def _match_alias(identity: str, index: int) -> str:
    return f"__match_{identity}_{index}"


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


def _split_source_predicate(
    predicate: Predicate | None,
) -> tuple[Predicate | None, Predicate | None]:
    if predicate is None:
        return None, None
    if isinstance(predicate, All):
        source_items: list[Predicate] = []
        aggregate_items: list[Predicate] = []
        for child in predicate.predicates:
            source_child, aggregate_child = _split_source_predicate(child)
            if source_child is not None:
                source_items.append(source_child)
            if aggregate_child is not None:
                aggregate_items.append(aggregate_child)
        return _all_or_single(source_items), _all_or_single(aggregate_items)
    if _is_source_predicate(predicate):
        return predicate, None
    return None, predicate


def _all_or_single(predicates: list[Predicate]) -> Predicate | None:
    if not predicates:
        return None
    return predicates[0] if len(predicates) == 1 else All(tuple(predicates))


def _is_source_predicate(predicate: Predicate) -> bool:
    return all(
        (value := promoted_value_by_identity(identity)) is not None
        and value.kind in {"dimension", "fact"}
        for identity in _predicate_values(predicate)
    )


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
