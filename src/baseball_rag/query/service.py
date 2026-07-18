"""Planning, trusted compilation, execution, and evidence assembly."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from typing import Any, Iterable, Mapping

from baseball_rag.query.compiler import compile_promoted_plan, compile_raw_plan
from baseball_rag.query.contracts import (
    All,
    CalculationEvidence,
    Compare,
    ExecutionFailed,
    ExecutionOutcome,
    ExecutionUnavailable,
    Export,
    Exported,
    InteractivePage,
    NoData,
    Not,
    PlanningOutcome,
    Predicate,
    QueryEvidence,
    QueryPlanV1,
    QueryRecipe,
    Ready,
    Rejected,
    Rows,
    Scalar,
    SortSpec,
    SourceEvidence,
    ValueRef,
)
from baseball_rag.query.contracts import (
    Any as AnyPredicate,
)
from baseball_rag.query.promoted import (
    is_promoted_grain,
    prepare_promoted,
    validate_promoted_plan,
)
from baseball_rag.query.registry import (
    CATALOG_DIR,
    _SourceBinding,
    catalog_revision,
    combination_by_identity,
    direct_value_sources,
    field_by_identity,
    promoted_value_by_identity,
    relationship_by_identity,
    source_by_identity,
)
from baseball_rag.query.runtime import (
    PublishedDataUnavailableError,
    published_data_runtime,
)

PLAN_VERSION = "query-plan-v1"


def prepare(recipe: QueryRecipe) -> PlanningOutcome:
    """Validate and canonicalize a Query Recipe against the published catalog."""
    current_revision = catalog_revision()
    if recipe.catalog_revision not in {None, current_revision}:
        return Rejected(
            f"Catalog revision {recipe.catalog_revision!r} is stale; current revision is "
            f"{current_revision!r}."
        )
    if source_by_identity(recipe.source) is None:
        return Rejected(f"Source {recipe.source!r} is not published.")
    if not recipe.selections:
        return Rejected("At least one published value must be selected.")

    output_reason = _validate_output(recipe.output)
    if output_reason is not None:
        return Rejected(output_reason)
    if is_promoted_grain(recipe.grain):
        return prepare_promoted(
            recipe,
            catalog_revision=current_revision,
            plan_version=PLAN_VERSION,
        )

    grain = "group_by" if recipe.groupings else recipe.grain
    if grain not in {"raw_rows", "group_by"}:
        return Rejected(f"Grain {grain!r} is not published yet.")
    if grain == "group_by" and set(recipe.selections) != set(recipe.groupings):
        return Rejected("Raw grouping selections must exactly match the grouped values.")

    for identity in recipe.selections:
        rejection = _validate_field_operation(recipe.source, identity, "select")
        if rejection is not None:
            return rejection
    for identity in recipe.groupings:
        rejection = _validate_field_operation(recipe.source, identity, "group")
        if rejection is not None:
            return rejection

    if recipe.predicate is not None:
        rejection = _validate_predicate(recipe.source, recipe.predicate)
        if rejection is not None:
            return rejection
    rejection = _validate_ordering(recipe.source, recipe.selections, recipe.ordering)
    if rejection is not None:
        return rejection
    if recipe.ranking is not None:
        return Rejected("Ranking is not published by the raw query surface.")

    return Ready(
        QueryPlanV1(
            version=PLAN_VERSION,
            catalog_revision=current_revision,
            source=recipe.source,
            grain=grain,
            selections=recipe.selections,
            predicate=recipe.predicate,
            groupings=recipe.groupings,
            ranking=recipe.ranking,
            ordering=recipe.ordering,
            output=recipe.output,
        )
    )


def execute(plan: QueryPlanV1) -> ExecutionOutcome:
    """Execute a validated Query Plan using only registry-owned SQL identifiers."""
    current_revision = catalog_revision()
    if plan.catalog_revision != current_revision:
        return ExecutionUnavailable(
            f"Plan catalog revision {plan.catalog_revision!r} does not match {current_revision!r}."
        )
    if plan.version != PLAN_VERSION:
        return ExecutionUnavailable(f"Unsupported Query Plan version {plan.version!r}.")

    invalid_reason = _validate_plan(plan)
    if invalid_reason is not None:
        return ExecutionUnavailable(invalid_reason)
    source = source_by_identity(plan.source)
    if source is None or source.kind not in {
        "packaged_lahman_table",
        "synthesized_team_reference",
    }:
        return ExecutionUnavailable(f"Source {plan.source!r} is not executable.")

    try:
        if is_promoted_grain(plan.grain):
            sql, bound_values = compile_promoted_plan(plan)
        else:
            sql, bound_values = compile_raw_plan(plan, source.relation, source.primary_key)
        runtime = published_data_runtime()
        active_connection = runtime.connection
    except (ValueError, PublishedDataUnavailableError) as exc:
        return ExecutionUnavailable(str(exc))

    try:
        cursor = active_connection.execute(sql, list(bound_values))
        columns = [str(item[0]) for item in cursor.description]
        materialized = cursor.fetchall()
    except Exception as exc:
        return ExecutionFailed(f"Query execution failed: {exc}")

    matched_row_count = int(materialized[0][-2]) if materialized else 0
    result_columns = columns[:-2]
    rows = tuple(
        dict(
            zip(
                result_columns,
                (_json_scalar(value) for value in values[:-2]),
                strict=True,
            )
        )
        for values in materialized
        if bool(values[-1])
    )
    evidence_sources = [source]
    for relationship_identity in plan.relationships:
        relationship = relationship_by_identity(relationship_identity)
        if relationship is None:
            combination = combination_by_identity(relationship_identity)
            if combination is None:
                return ExecutionUnavailable(
                    f"Relationship {relationship_identity!r} is not published."
                )
            used_sources = {plan.source}
            for value_identity in _plan_references(plan):
                direct_sources = direct_value_sources(value_identity) & set(combination.sources)
                if len(direct_sources) == 1:
                    used_sources.update(direct_sources)
                elif plan.source in direct_sources:
                    used_sources.add(plan.source)
            for identity in combination.sources:
                if identity not in used_sources:
                    continue
                binding = source_by_identity(identity)
                if binding is not None and binding not in evidence_sources:
                    evidence_sources.append(binding)
            continue
        for identity in (relationship.left_source, relationship.right_source):
            binding = source_by_identity(identity)
            if binding is not None and binding not in evidence_sources:
                evidence_sources.append(binding)
    evidence = _evidence(
        plan=plan,
        sql=sql,
        bound_values=bound_values,
        rows=rows,
        matched_row_count=matched_row_count,
        sources=tuple(evidence_sources),
        manifest=runtime.manifest,
        data_release=runtime.data_release,
        source_fingerprints=runtime.source_fingerprints,
    )
    if not rows and matched_row_count == 0:
        return NoData(plan=plan, rows=rows, evidence=evidence)
    if isinstance(plan.output, Export):
        return Exported(
            plan=plan,
            rows=rows,
            evidence=evidence,
            format=plan.output.format,
            content=_render_export(rows, plan.output.format),
        )
    return Rows(plan=plan, rows=rows, evidence=evidence)


def _plan_references(plan: QueryPlanV1) -> set[str]:
    references = set(plan.selections)
    references.update(plan.groupings)
    references.update(spec.value for spec in plan.ordering)
    if plan.ranking is not None:
        references.add(plan.ranking.value)
        references.update(plan.ranking.within)
    references.update(_predicate_references(plan.predicate))
    return references


def _predicate_references(predicate: Predicate | None) -> set[str]:
    if predicate is None:
        return set()
    if isinstance(predicate, Compare):
        references = {predicate.value}
        if isinstance(predicate.literal, ValueRef):
            references.add(predicate.literal.identity)
        return references
    if isinstance(predicate, (All, AnyPredicate)):
        return set().union(*(_predicate_references(item) for item in predicate.predicates))
    return _predicate_references(predicate.predicate)


def _validate_field_operation(source: str, identity: str, operation: str) -> Rejected | None:
    field = field_by_identity(identity)
    if field is None or field.source != source:
        return Rejected(f"Value {identity!r} is not published for {source}.")
    if operation not in field.operations:
        return Rejected(f"Operation {operation!r} is not valid for {identity}.")
    return None


def _validate_predicate(source: str, predicate: Predicate) -> Rejected | None:
    if isinstance(predicate, Compare):
        return _validate_compare(source, predicate)
    if isinstance(predicate, (All, AnyPredicate)):
        if not predicate.predicates:
            return Rejected(f"{type(predicate).__name__} requires at least one predicate.")
        for child in predicate.predicates:
            rejection = _validate_predicate(source, child)
            if rejection is not None:
                return rejection
        return None
    if isinstance(predicate, Not):
        return _validate_predicate(source, predicate.predicate)
    return Rejected("Unsupported predicate kind.")


def _validate_compare(source: str, compare: Compare) -> Rejected | None:
    field = field_by_identity(compare.value)
    if field is None or field.source != source:
        return Rejected(f"Filter value {compare.value!r} is not published for {source}.")
    if compare.operator not in field.operations:
        return Rejected(f"Operator {compare.operator!r} is not valid for {compare.value}.")
    if not isinstance(compare.literal, (tuple, str, int, float, bool, type(None))):
        return Rejected("Raw-field comparisons require typed scalar literals.")
    literals = compare.literal if isinstance(compare.literal, tuple) else (compare.literal,)
    if compare.operator == "range" and len(literals) != 2:
        return Rejected(f"Range filter {compare.value!r} requires exactly two literals.")
    if compare.operator == "one_of" and not literals:
        return Rejected(f"One-of filter {compare.value!r} requires at least one literal.")
    if compare.operator not in {"range", "one_of"} and isinstance(compare.literal, tuple):
        return Rejected(f"Operator {compare.operator!r} requires one literal.")
    for literal in literals:
        reason = _validate_literal(field.data_type, literal)
        if reason is not None:
            return Rejected(f"Filter {compare.value!r} {reason}")
    return None


def _validate_literal(data_type: str, literal: Scalar) -> str | None:
    if data_type == "text":
        return None if isinstance(literal, str) else "requires a text literal."
    if data_type == "integer":
        valid = isinstance(literal, int) and not isinstance(literal, bool)
        return None if valid else "requires an integer literal."
    if data_type == "number":
        valid = isinstance(literal, (int, float)) and not isinstance(literal, bool)
        return None if valid else "requires a numeric literal."
    if data_type == "date":
        if not isinstance(literal, str):
            return "requires an ISO date literal."
        try:
            date.fromisoformat(literal)
        except ValueError:
            return "requires an ISO date literal."
        return None
    return f"uses unsupported catalog type {data_type!r}."


def _validate_ordering(
    source: str,
    selections: tuple[str, ...],
    ordering: tuple[SortSpec, ...],
) -> Rejected | None:
    for spec in ordering:
        if not isinstance(spec, SortSpec):
            return Rejected("Unsupported sort specification.")
        rejection = _validate_field_operation(source, spec.value, "sort")
        if rejection is not None:
            return rejection
        if spec.value not in selections:
            return Rejected("Raw sorting values must also be selected.")
        if spec.direction not in {"ascending", "descending"}:
            return Rejected(f"Sort direction {spec.direction!r} is not published.")
        if spec.nulls not in {"first", "last"}:
            return Rejected(f"Null placement {spec.nulls!r} is not published.")
    return None


def _validate_output(output: object) -> str | None:
    if isinstance(output, InteractivePage):
        if output.size <= 0 or output.offset < 0:
            return "Interactive page size must be positive and offset cannot be negative."
        return None
    if isinstance(output, Export):
        if output.format not in {"csv", "json"}:
            return f"Export format {output.format!r} is not published."
        return None
    return "Unsupported output kind."


def _validate_plan(plan: QueryPlanV1) -> str | None:
    if is_promoted_grain(plan.grain):
        return validate_promoted_plan(plan, plan_version=PLAN_VERSION)
    if plan.grain not in {"raw_rows", "group_by"}:
        return f"Grain {plan.grain!r} is not published yet."
    if plan.grain == "group_by" and set(plan.selections) != set(plan.groupings):
        return "Raw grouping selections must exactly match the grouped values."
    if plan.relationships:
        return "Relationships are not published by the raw query surface."
    if plan.ranking is not None:
        return "Ranking is not published by the raw query surface."
    if not plan.selections:
        return "At least one published value must be selected."
    for identity in plan.selections:
        rejection = _validate_field_operation(plan.source, identity, "select")
        if rejection is not None:
            return rejection.reason
    for identity in plan.groupings:
        rejection = _validate_field_operation(plan.source, identity, "group")
        if rejection is not None:
            return rejection.reason
    if plan.predicate is not None:
        rejection = _validate_predicate(plan.source, plan.predicate)
        if rejection is not None:
            return rejection.reason
    rejection = _validate_ordering(plan.source, plan.selections, plan.ordering)
    if rejection is not None:
        return rejection.reason
    return _validate_output(plan.output)


def _json_scalar(value: object) -> Scalar:
    """Normalize DuckDB values to the public JSON-scalar contract."""
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"Query returned unsupported scalar type {type(value).__name__!r}.")


def _evidence(
    *,
    plan: QueryPlanV1,
    sql: str,
    bound_values: tuple[Scalar, ...],
    rows: Iterable[dict[str, Scalar]],
    matched_row_count: int,
    sources: tuple[_SourceBinding, ...],
    manifest: dict[str, Any],
    data_release: str,
    source_fingerprints: Mapping[str, str],
) -> QueryEvidence:
    materialized_rows = tuple(rows)
    fingerprint_payload = json.dumps(
        materialized_rows,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    evidence_sources = []
    for source in sources:
        file_record: dict[str, Any] = next(
            (
                item
                for item in manifest.get("files", [])
                if item.get("table") == source.manifest_table
            ),
            {},
        )
        expected_rows = file_record.get("rows")
        sha256 = file_record.get("sha256")
        source_release = data_release
        if source.reference_manifest is not None:
            reference = json.loads(
                (CATALOG_DIR / source.reference_manifest).read_text(encoding="utf-8")
            )
            expected_rows = reference.get("rows")
            sha256 = reference.get("sha256")
            source_release = str(source.reference_version or reference.get("reference_version"))
        evidence_sources.append(
            SourceEvidence(
                identity=source.identity,
                kind=source.kind,
                release=source_release,
                expected_rows=expected_rows,
                sha256=sha256,
                row_fingerprint=source_fingerprints[source.identity],
            )
        )
    return QueryEvidence(
        parameterized_sql=sql,
        bound_values=bound_values,
        sources=tuple(evidence_sources),
        catalog_revision=plan.catalog_revision,
        data_release=data_release,
        row_count=len(materialized_rows),
        matched_row_count=matched_row_count,
        result_fingerprint=hashlib.sha256(fingerprint_payload).hexdigest(),
        calculations=tuple(
            CalculationEvidence(
                identity=identity,
                formula=value.formula,
                inputs=value.components,
            )
            for identity in plan.selections
            if (value := promoted_value_by_identity(identity)) is not None
            and value.kind == "calculation"
            and value.formula is not None
        ),
    )


def _render_export(rows: tuple[dict[str, Scalar], ...], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
    output = io.StringIO(newline="")
    fieldnames = list(rows[0])
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
