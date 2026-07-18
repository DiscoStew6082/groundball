"""Catalog-driven planning for promoted query semantics."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal, InvalidOperation

from baseball_rag.query.contracts import (
    All,
    Any,
    Compare,
    NeedsClarification,
    Not,
    PlanningOutcome,
    Predicate,
    QueryPlanV1,
    QueryRecipe,
    RankSpec,
    Ready,
    Rejected,
    Scalar,
    SortSpec,
    ValueRef,
)
from baseball_rag.query.registry import (
    _relationship_bindings,
    canonical_promoted_identity,
    field_by_identity,
    grain_by_identity,
    is_promoted_grouping,
    promoted_value_by_identity,
)


def is_promoted_grain(identity: str) -> bool:
    return grain_by_identity(identity) is not None


def prepare_promoted(
    recipe: QueryRecipe,
    *,
    catalog_revision: str,
    plan_version: str,
) -> PlanningOutcome:
    grain = grain_by_identity(recipe.grain)
    if grain is None:
        return Rejected(f"Grain {recipe.grain!r} is not published yet.")
    if recipe.source not in grain.sources:
        return Rejected(f"Grain {recipe.grain!r} is not published for {recipe.source}.")
    selections_or_rejection = _canonical_values(recipe.selections, recipe.grain, recipe.source)
    if isinstance(selections_or_rejection, Rejected):
        return selections_or_rejection
    selections = selections_or_rejection
    groupings_or_rejection = _canonical_values(recipe.groupings, recipe.grain, recipe.source)
    if isinstance(groupings_or_rejection, Rejected):
        return groupings_or_rejection
    groupings = groupings_or_rejection
    if any(not is_promoted_grouping(identity) for identity in groupings):
        return Rejected("Every promoted grouping must be explicitly published.")
    if not set(groupings) <= set(selections):
        return Rejected("Every promoted grouping must also be selected.")
    if groupings and any(
        (value := promoted_value_by_identity(identity)) is not None
        and value.kind in {"dimension", "fact"}
        and identity not in groupings
        for identity in selections
    ):
        return Rejected("Selected dimensions and facts must be explicit promoted grouping keys.")

    predicate: Predicate | None = None
    if recipe.predicate is not None:
        predicate_or_rejection = _canonical_predicate(recipe.predicate, recipe.grain, recipe.source)
        if isinstance(predicate_or_rejection, Rejected):
            return predicate_or_rejection
        predicate = predicate_or_rejection
        if groupings and _has_unsafe_grouped_predicate(predicate):
            return Rejected(
                "One grouped predicate cannot mix source dimensions with post-aggregate values."
            )
        for reference in _predicate_values(predicate):
            value = promoted_value_by_identity(reference)
            if (
                value is not None
                and value.kind == "window"
                and value.window_eligibility is not None
                and not _has_explicit_floor(predicate, value.window_eligibility)
            ):
                return NeedsClarification(
                    f"What reviewed {value.window_eligibility} eligibility floor should "
                    f"{value.friendly_name} use?"
                )

    ranking: RankSpec | None = None
    if recipe.ranking is not None:
        ranking_or_outcome = _canonical_ranking(recipe.ranking, recipe.grain, recipe.source)
        if isinstance(ranking_or_outcome, Rejected):
            return ranking_or_outcome
        ranking = ranking_or_outcome
        if groupings:
            ranked_value = promoted_value_by_identity(ranking.value)
            if (
                ranked_value is not None
                and ranked_value.kind in {"dimension", "fact"}
                and ranking.value not in groupings
            ):
                return Rejected("A grouped rank dimension must be a grouping key.")
            if not set(ranking.within) <= set(groupings):
                return Rejected("Grouped rank partitions must be grouping keys.")
        ranked_value = promoted_value_by_identity(ranking.value)
        if (
            ranked_value is not None
            and ranked_value.kind == "calculation"
            and ranked_value.eligibility_component is not None
            and not _has_explicit_floor(predicate, ranked_value.eligibility_component)
        ):
            return NeedsClarification(
                "What explicit sample floor or reviewed eligibility rule should this "
                f"{ranked_value.friendly_name} leaderboard use?"
            )

    ordering: list[SortSpec] = []
    for spec in recipe.ordering:
        identity = canonical_promoted_identity(spec.value, source=recipe.source)
        if identity is None:
            return Rejected(f"Sort value {spec.value!r} is not published.")
        rejection = _validate_value_at_grain(identity, recipe.grain)
        if rejection is not None:
            return rejection
        if spec.direction not in {"ascending", "descending"}:
            return Rejected(f"Sort direction {spec.direction!r} is not published.")
        if spec.nulls not in {"first", "last"}:
            return Rejected(f"Null placement {spec.nulls!r} is not published.")
        if groupings and identity not in selections:
            return Rejected("Grouped sort values must be selected result values.")
        ordering.append(replace(spec, value=identity))

    refs = set(selections)
    refs.update(groupings or grain.dimensions)
    refs.update(_predicate_values(predicate))
    refs.update(spec.value for spec in ordering)
    if ranking is not None:
        refs.add(ranking.value)
        refs.update(ranking.within)
    required_sources = set().union(
        *(_value_sources(identity, anchor_source=recipe.source) for identity in refs)
    )
    relationships = []
    for required_source in sorted(required_sources - {recipe.source}):
        candidates = [
            relationship
            for relationship in _relationship_bindings()
            if {relationship.left_source, relationship.right_source}
            == {recipe.source, required_source}
        ]
        if len(candidates) != 1:
            return Rejected(
                f"No single published relationship connects {recipe.source} and {required_source}."
            )
        relationships.append(candidates[0].identity)

    return Ready(
        QueryPlanV1(
            version=plan_version,
            catalog_revision=catalog_revision,
            source=recipe.source,
            grain=recipe.grain,
            selections=selections,
            groupings=groupings,
            predicate=predicate,
            relationships=tuple(relationships),
            ranking=ranking,
            ordering=tuple(ordering),
            output=recipe.output,
        )
    )


def validate_promoted_plan(plan: QueryPlanV1, *, plan_version: str) -> str | None:
    """Revalidate a deserialized promoted plan and reject semantic forgery."""
    outcome = prepare_promoted(
        QueryRecipe(
            source=plan.source,
            grain=plan.grain,
            selections=plan.selections,
            groupings=plan.groupings,
            predicate=plan.predicate,
            ranking=plan.ranking,
            ordering=plan.ordering,
            output=plan.output,
        ),
        catalog_revision=plan.catalog_revision,
        plan_version=plan_version,
    )
    if isinstance(outcome, Ready) and outcome.plan == plan:
        return None
    if isinstance(outcome, (Rejected, NeedsClarification)):
        return outcome.reason if isinstance(outcome, Rejected) else outcome.question
    return "Promoted Query Plan is not canonical."


def _canonical_values(
    values: tuple[str, ...], grain: str, source: str
) -> tuple[str, ...] | Rejected:
    canonical: list[str] = []
    for reference in values:
        identity = canonical_promoted_identity(reference, source=source)
        if identity is None:
            return Rejected(f"Value {reference!r} is not published.")
        rejection = _validate_value_at_grain(identity, grain)
        if rejection is not None:
            return rejection
        canonical.append(identity)
    return tuple(canonical)


def _canonical_predicate(predicate: Predicate, grain: str, source: str) -> Predicate | Rejected:
    if isinstance(predicate, Compare):
        identity = canonical_promoted_identity(predicate.value, source=source)
        if identity is None:
            return Rejected(f"Filter value {predicate.value!r} is not published.")
        rejection = _validate_value_at_grain(identity, grain)
        if rejection is not None:
            return rejection
        value = promoted_value_by_identity(identity)
        assert value is not None
        if predicate.operator not in _operations(value.data_type):
            return Rejected(f"Operator {predicate.operator!r} is not valid for {identity}.")
        if isinstance(predicate.literal, ValueRef):
            target_identity = canonical_promoted_identity(predicate.literal.identity, source=source)
            if target_identity is None:
                return Rejected(
                    f"Comparison value {predicate.literal.identity!r} is not published."
                )
            target_rejection = _validate_value_at_grain(target_identity, grain)
            if target_rejection is not None:
                return target_rejection
            target = promoted_value_by_identity(target_identity)
            assert target is not None
            if target.data_type != value.data_type:
                return Rejected("Compared catalog values must have compatible types.")
            if predicate.operator not in {"equals", "not_equals"}:
                return Rejected("Catalog-value comparisons support equality only.")
            return replace(
                predicate,
                value=identity,
                literal=ValueRef(target_identity),
            )
        literals = (
            predicate.literal if isinstance(predicate.literal, tuple) else (predicate.literal,)
        )
        if predicate.operator == "range" and len(literals) != 2:
            return Rejected(f"Range filter {identity!r} requires exactly two literals.")
        if predicate.operator == "one_of" and not literals:
            return Rejected(f"One-of filter {identity!r} requires at least one literal.")
        if predicate.operator not in {"range", "one_of"} and isinstance(predicate.literal, tuple):
            return Rejected(f"Operator {predicate.operator!r} requires one literal.")
        if any(not _literal_matches(value.data_type, literal) for literal in literals):
            return Rejected(f"Filter {identity!r} requires a {value.data_type} literal.")
        return replace(predicate, value=identity)
    if isinstance(predicate, (All, Any)):
        if not predicate.predicates:
            return Rejected(f"{type(predicate).__name__} requires at least one predicate.")
        children: list[Predicate] = []
        for item in predicate.predicates:
            canonical = _canonical_predicate(item, grain, source)
            if isinstance(canonical, Rejected):
                return canonical
            children.append(canonical)
        return type(predicate)(tuple(children))
    if isinstance(predicate, Not):
        child = _canonical_predicate(predicate.predicate, grain, source)
        return child if isinstance(child, Rejected) else Not(child)
    return Rejected("Unsupported predicate kind.")


def _canonical_ranking(ranking: RankSpec, grain: str, source: str) -> RankSpec | Rejected:
    identity = canonical_promoted_identity(ranking.value, source=source)
    if identity is None:
        return Rejected(f"Rank value {ranking.value!r} is not published.")
    rejection = _validate_value_at_grain(identity, grain)
    if rejection is not None:
        return rejection
    if ranking.direction not in {"highest", "lowest"}:
        return Rejected(f"Rank direction {ranking.direction!r} is not published.")
    if ranking.count <= 0:
        return Rejected("Rank count must be positive.")
    if ranking.tie_policy not in {"include_ties", "exact_count"}:
        return Rejected(f"Tie policy {ranking.tie_policy!r} is not published.")
    within_or_rejection = _canonical_values(ranking.within, grain, source)
    if isinstance(within_or_rejection, Rejected):
        return within_or_rejection
    for partition_identity in within_or_rejection:
        value = promoted_value_by_identity(partition_identity)
        if value is None or value.kind != "dimension":
            return Rejected(f"Rank partition {partition_identity!r} must be a published dimension.")
    return replace(ranking, value=identity, within=within_or_rejection)


def _validate_value_at_grain(identity: str, grain: str) -> Rejected | None:
    value = promoted_value_by_identity(identity)
    if value is None:
        return Rejected(f"Value {identity!r} is not published.")
    allowed = set(value.allowed_grains)
    if grain not in allowed:
        return Rejected(f"Value {identity!r} is not published at grain {grain!r}.")
    return None


def _operations(data_type: str) -> set[str]:
    if data_type == "text":
        return {"equals", "one_of"}
    if data_type == "date":
        return {"equals", "before", "after", "range"}
    return {
        "equals",
        "not_equals",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "range",
    }


def _literal_matches(data_type: str, literal: Scalar) -> bool:
    if data_type == "text":
        return isinstance(literal, str)
    if data_type == "integer":
        return isinstance(literal, int) and not isinstance(literal, bool)
    if data_type == "number":
        return isinstance(literal, (int, float)) and not isinstance(literal, bool)
    if data_type == "baseball_innings":
        if not isinstance(literal, (int, float)) or isinstance(literal, bool) or literal < 0:
            return False
        try:
            tenths = Decimal(str(literal)) * 10
        except InvalidOperation:
            return False
        return tenths == tenths.to_integral_value() and int(tenths) % 10 in {0, 1, 2}
    if data_type == "date" and isinstance(literal, str):
        try:
            date.fromisoformat(literal)
        except ValueError:
            return False
        return True
    return False


def _predicate_values(predicate: Predicate | None) -> set[str]:
    if predicate is None:
        return set()
    if isinstance(predicate, Compare):
        values = {predicate.value}
        if isinstance(predicate.literal, ValueRef):
            values.add(predicate.literal.identity)
        return values
    if isinstance(predicate, (All, Any)):
        return set().union(*(_predicate_values(item) for item in predicate.predicates))
    return _predicate_values(predicate.predicate)


def _has_explicit_floor(predicate: Predicate | None, identity: str) -> bool:
    if predicate is None:
        return False
    if isinstance(predicate, Compare):
        return (
            predicate.value == identity
            and predicate.operator == "greater_or_equal"
            and isinstance(predicate.literal, (int, float))
            and not isinstance(predicate.literal, bool)
            and predicate.literal > 0
        )
    if isinstance(predicate, All):
        return any(_has_explicit_floor(item, identity) for item in predicate.predicates)
    return False


def _has_unsafe_grouped_predicate(predicate: Predicate) -> bool:
    if isinstance(predicate, Compare):
        return len(_predicate_stages(predicate)) > 1
    if isinstance(predicate, Any):
        if len(_predicate_stages(predicate)) > 1:
            return True
        return any(_has_unsafe_grouped_predicate(item) for item in predicate.predicates)
    if isinstance(predicate, All):
        return any(_has_unsafe_grouped_predicate(item) for item in predicate.predicates)
    if isinstance(predicate, Not):
        return len(_predicate_stages(predicate.predicate)) > 1 or _has_unsafe_grouped_predicate(
            predicate.predicate
        )
    return True


def _predicate_stages(predicate: Predicate) -> set[str]:
    if isinstance(predicate, Compare):
        stages: set[str] = set()
        for identity in _predicate_values(predicate):
            value = promoted_value_by_identity(identity)
            if value is None:
                continue
            if value.kind in {"dimension", "fact"}:
                stages.add("source")
            else:
                stages.add("post")
        return stages
    if isinstance(predicate, (All, Any)):
        return set().union(*(_predicate_stages(item) for item in predicate.predicates))
    return _predicate_stages(predicate.predicate)


def _value_sources(
    identity: str,
    *,
    anchor_source: str,
    seen: set[str] | None = None,
) -> set[str]:
    visited = set() if seen is None else seen
    if identity in visited:
        return set()
    visited.add(identity)
    value = promoted_value_by_identity(identity)
    if value is None:
        return set()
    if anchor_source in value.source_bindings:
        return {anchor_source}
    sources: set[str] = set()
    for field_identity in (
        *((value.source_field,) if value.source_field is not None else ()),
        *value.source_fields,
        *value.components,
    ):
        field = field_by_identity(field_identity)
        if field is not None:
            sources.add(field.source)
    for dependency in (value.window_base, value.window_eligibility):
        if dependency is not None:
            sources.update(
                _value_sources(
                    dependency,
                    anchor_source=anchor_source,
                    seen=visited,
                )
            )
    return sources
