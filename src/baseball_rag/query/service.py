"""Planning, trusted compilation, execution, and evidence assembly."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from duckdb import DuckDBPyConnection

from baseball_rag.db.duckdb_schema import DATA_DIR, get_duckdb
from baseball_rag.query.contracts import (
    Compare,
    ExecutionFailed,
    ExecutionOutcome,
    ExecutionUnavailable,
    NoData,
    PlanningOutcome,
    QueryEvidence,
    QueryPlanV1,
    QueryRecipe,
    Ready,
    Rejected,
    Rows,
    Scalar,
    SourceEvidence,
)
from baseball_rag.query.registry import (
    CATALOG_DIR,
    _SourceBinding,
    catalog_revision,
    field_by_identity,
    source_by_identity,
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
    if recipe.grain != "raw_rows":
        return Rejected(f"Grain {recipe.grain!r} is not published yet.")
    if source_by_identity(recipe.source) is None:
        return Rejected(f"Source {recipe.source!r} is not published.")
    if not recipe.selections:
        return Rejected("At least one published value must be selected.")

    for identity in recipe.selections:
        field = field_by_identity(identity)
        if field is None or field.source != recipe.source:
            return Rejected(f"Value {identity!r} is not published for {recipe.source}.")
        if "select" not in field.operations:
            return Rejected(f"Value {identity!r} cannot be selected.")

    if recipe.predicate is not None:
        rejection = _validate_compare(recipe.source, recipe.predicate)
        if rejection is not None:
            return rejection

    return Ready(
        QueryPlanV1(
            version=PLAN_VERSION,
            catalog_revision=current_revision,
            source=recipe.source,
            grain=recipe.grain,
            selections=recipe.selections,
            predicate=recipe.predicate,
        )
    )


def execute(
    plan: QueryPlanV1,
) -> ExecutionOutcome:
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
        sql, bound_values = _compile(plan, source.relation, source.primary_key)
    except ValueError as exc:
        return ExecutionUnavailable(str(exc))

    try:
        active_connection = get_duckdb()
        _ensure_source(active_connection, source)
        cursor = active_connection.execute(sql, list(bound_values))
        columns = [str(item[0]) for item in cursor.description]
        rows = tuple(dict(zip(columns, values, strict=True)) for values in cursor.fetchall())
    except Exception as exc:
        return ExecutionFailed(f"Query execution failed: {exc}")

    evidence = _evidence(
        plan=plan,
        sql=sql,
        bound_values=bound_values,
        rows=rows,
        source_identity=source.identity,
        source_kind=source.kind,
        manifest_table=source.manifest_table,
        reference_manifest=source.reference_manifest,
        reference_version=source.reference_version,
    )
    outcome = Rows if rows else NoData
    return outcome(plan=plan, rows=rows, evidence=evidence)


def _validate_compare(source: str, compare: Compare) -> Rejected | None:
    field = field_by_identity(compare.value)
    if field is None or field.source != source:
        return Rejected(f"Filter value {compare.value!r} is not published for {source}.")
    if compare.operator not in {"equals"}:
        return Rejected(f"Operator {compare.operator!r} is not published for {compare.value}.")
    if compare.operator not in field.operations:
        return Rejected(f"Operator {compare.operator!r} is not valid for {compare.value}.")
    if field.data_type == "text" and not isinstance(compare.literal, str):
        return Rejected(f"Filter {compare.value!r} requires a text literal.")
    if field.data_type == "integer" and (
        not isinstance(compare.literal, int) or isinstance(compare.literal, bool)
    ):
        return Rejected(f"Filter {compare.value!r} requires an integer literal.")
    return None


def _validate_plan(plan: QueryPlanV1) -> str | None:
    if plan.grain != "raw_rows":
        return f"Grain {plan.grain!r} is not published yet."
    if plan.relationships:
        return "Relationships are not published by the raw-query tracer."
    if plan.ranking is not None:
        return "Ranking is not published by the raw-query tracer."
    if plan.ordering:
        return "Custom ordering is not published by the raw-query tracer."
    if plan.output != "interactive_page":
        return f"Output {plan.output!r} is not published by the raw-query tracer."
    if not plan.selections:
        return "At least one published value must be selected."
    for identity in plan.selections:
        field = field_by_identity(identity)
        if field is None or field.source != plan.source:
            return f"Plan references stale field {identity!r}."
    if plan.predicate is not None:
        rejection = _validate_compare(plan.source, plan.predicate)
        if rejection is not None:
            return rejection.reason
    return None


def _compile(
    plan: QueryPlanV1,
    relation: str,
    primary_key: tuple[str, ...],
) -> tuple[str, tuple[Scalar, ...]]:
    selected = []
    for identity in plan.selections:
        field = field_by_identity(identity)
        if field is None or field.source != plan.source:
            raise ValueError(f"Plan references stale field {identity!r}.")
        selected.append(f"{_quote(field.column)} AS {_quote(field.identity)}")

    where = ""
    bound_values: tuple[Scalar, ...] = ()
    if plan.predicate is not None:
        field = field_by_identity(plan.predicate.value)
        if field is None or field.source != plan.source:
            raise ValueError(f"Plan references stale filter field {plan.predicate.value!r}.")
        if plan.predicate.operator != "equals":
            raise ValueError(f"Plan uses unsupported operator {plan.predicate.operator!r}.")
        where = f" WHERE {_quote(field.column)} = ?"
        bound_values = (plan.predicate.literal,)

    order = ", ".join(_quote(column) for column in primary_key)
    sql = f"SELECT {', '.join(selected)} FROM {_quote(relation)}{where} ORDER BY {order}"
    return sql, bound_values


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _ensure_source(active_connection: DuckDBPyConnection, source: _SourceBinding) -> None:
    if source.kind != "synthesized_team_reference":
        return
    if source.asset is None or source.reference_manifest is None:
        raise ValueError(f"Synthesized source {source.identity!r} has no bound asset.")
    asset_path = CATALOG_DIR / source.asset
    manifest_path = CATALOG_DIR / source.reference_manifest
    reference_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    content = asset_path.read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    if digest != reference_manifest["sha256"]:
        raise ValueError(f"Synthesized source {source.identity!r} failed its checksum.")
    active_connection.execute(
        f"CREATE OR REPLACE TABLE {_quote(source.relation)} AS SELECT * FROM read_csv_auto(?)",
        [str(asset_path)],
    )


def _evidence(
    *,
    plan: QueryPlanV1,
    sql: str,
    bound_values: tuple[Scalar, ...],
    rows: Iterable[dict[str, Scalar]],
    source_identity: str,
    source_kind: str,
    manifest_table: str | None,
    reference_manifest: str | None,
    reference_version: str | None,
) -> QueryEvidence:
    manifest = json.loads((Path(DATA_DIR) / "manifest.json").read_text(encoding="utf-8"))
    file_record: dict[str, Any] = next(
        (item for item in manifest.get("files", []) if item.get("table") == manifest_table),
        {},
    )
    data_release = str(manifest.get("dataset", {}).get("upstream_release") or "unavailable")
    materialized_rows = tuple(rows)
    fingerprint_payload = json.dumps(
        materialized_rows,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    expected_rows = file_record.get("rows")
    sha256 = file_record.get("sha256")
    source_release = data_release
    if reference_manifest is not None:
        reference = json.loads((CATALOG_DIR / reference_manifest).read_text(encoding="utf-8"))
        expected_rows = reference.get("rows")
        sha256 = reference.get("sha256")
        source_release = str(reference_version or reference.get("reference_version"))
    source = SourceEvidence(
        identity=source_identity,
        kind=source_kind,
        release=source_release,
        expected_rows=expected_rows,
        sha256=sha256,
    )
    return QueryEvidence(
        parameterized_sql=sql,
        bound_values=bound_values,
        sources=(source,),
        catalog_revision=plan.catalog_revision,
        data_release=data_release,
        row_count=len(materialized_rows),
        result_fingerprint=hashlib.sha256(fingerprint_payload).hexdigest(),
    )
