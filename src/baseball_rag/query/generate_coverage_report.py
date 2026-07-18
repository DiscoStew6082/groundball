"""Generate release-blocking query coverage proof from the public query seams."""

from __future__ import annotations

import argparse
import json
import socket
from collections.abc import Mapping
from dataclasses import replace
from datetime import date
from itertools import combinations
from math import isclose
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

from baseball_rag.query.adapters import catalog_payload
from baseball_rag.query.contracts import (
    All,
    Compare,
    ExecutionFailed,
    ExecutionUnavailable,
    Export,
    Exported,
    InteractivePage,
    NeedsClarification,
    NoData,
    Not,
    Predicate,
    QueryPlanV1,
    QueryRecipe,
    RankSpec,
    Ready,
    Rejected,
    Rows,
    Scalar,
    SortSpec,
    ValueRef,
)
from baseball_rag.query.contracts import Any as AnyPredicate
from baseball_rag.query.coverage import (
    COVERAGE_MARKDOWN_PATH,
    COVERAGE_REPORT_PATH,
    REPORT_SCHEMA_VERSION,
    canonical_proof_id,
    current_proof_identity,
    render_coverage_markdown,
)
from baseball_rag.query.fingerprint import RowFingerprint
from baseball_rag.query.recipe_adapter import build_named_recipe, interpret_recipe
from baseball_rag.query.registry import (
    _combination_bindings,
    _named_recipe_bindings,
    _relationship_bindings,
    _source_bindings,
    combination_for,
    direct_value_sources,
    discover_fields,
    grain_by_identity,
    promoted_value_by_identity,
    published_values,
)
from baseball_rag.query.runtime import PublishedDataRuntime, published_data_runtime
from baseball_rag.query.service import execute, prepare

Gate = dict[str, Any]


def generate_coverage_report() -> dict[str, Any]:
    """Run every release-blocking gate and return one canonical read model."""
    with (
        patch.object(socket.socket, "connect", side_effect=_network_blocked),
        patch.object(socket, "create_connection", side_effect=_network_blocked),
    ):
        return _generate_coverage_report()


def _generate_coverage_report() -> dict[str, Any]:
    gates = [
        _capture_gate("catalog_schema_identity", _catalog_obligation_total(), _catalog_schema_gate),
        _capture_gate("raw_reachability", _raw_obligation_total(), _raw_gate),
        _capture_gate("promoted_exactness", _promoted_obligation_total(), _promoted_gate),
        _capture_gate("plan_compiler_safety", _plan_safety_obligation_total(), _plan_safety_gate),
        _capture_gate("outcome_evidence_integrity", _outcome_obligation_total(), _outcome_gate),
        _capture_gate("no_llm_no_mac", 5, _independence_gate),
    ]
    failures = [f"{gate['identity']}: {failure}" for gate in gates for failure in gate["failures"]]
    total = sum(int(gate["total"]) for gate in gates)
    covered = sum(int(gate["covered"]) for gate in gates)
    uncovered = total - covered
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "passing" if not failures and uncovered == 0 else "failing",
        "proof_identity": current_proof_identity(),
        "summary": {"covered": covered, "total": total, "uncovered": uncovered},
        "sources": gates[0]["details"].get("sources", []),
        "gates": gates,
        "failures": failures,
    }
    report["proof_id"] = canonical_proof_id(report)
    return report


def _network_blocked(*_args: object, **_kwargs: object) -> None:
    raise RuntimeError("Coverage generation forbids network access.")


def write_coverage_report(report: dict[str, Any]) -> None:
    """Write both representations from the same canonical report value."""
    COVERAGE_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    COVERAGE_REPORT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    COVERAGE_MARKDOWN_PATH.write_text(render_coverage_markdown(report), encoding="utf-8")


def _capture_gate(identity: str, total: int, check: Callable[[], dict[str, Any]]) -> Gate:
    try:
        details = check()
        observed = int(details.pop("covered", total))
        failures = list(details.pop("failures", []))
        obligations = list(details.pop("obligations", []))
    except Exception as exc:  # noqa: BLE001 - report every failed release gate
        details = {}
        observed = 0
        failures = [f"{type(exc).__name__}: {exc}"]
        obligations = []
    return {
        "identity": identity,
        "status": "passing" if not failures and observed == total else "failing",
        "covered": observed,
        "total": total,
        "failures": failures,
        "obligations": obligations,
        "details": details,
    }


def _catalog_schema_gate() -> dict[str, Any]:
    runtime = published_data_runtime()
    sources = []
    obligations = [_passed("compatibility:catalog-data-pair")]
    for source in _source_bindings():
        fields = discover_fields(source=source.identity)
        row = runtime.connection.execute(f'SELECT count(*) FROM "{source.relation}"').fetchone()
        observed_rows = int(row[0]) if row else -1
        if source.reference_manifest:
            record = json.loads(
                (Path(__file__).with_name("catalog") / source.reference_manifest).read_text()
            )
        else:
            matches = [
                item
                for item in runtime.manifest["files"]
                if item.get("table") == source.manifest_table
            ]
            record = matches[0]
        expected_rows = int(record["rows"])
        if observed_rows != expected_rows:
            raise AssertionError(f"{source.identity} row count drifted")
        described = runtime.connection.execute(f'DESCRIBE "{source.relation}"').fetchall()
        if len(described) != len(fields):
            raise AssertionError(f"{source.identity} field count drifted")
        sources.append(
            {
                "identity": source.identity,
                "expected_rows": expected_rows,
                "observed_rows": observed_rows,
                "expected_fields": len(fields),
                "observed_fields": len(described),
                "row_fingerprint": runtime.source_fingerprints[source.identity],
            }
        )
        obligations.append(_passed(f"source:{source.identity}:identity"))
        obligations.append(_passed(f"source:{source.identity}:rows"))
        obligations.extend(_passed(f"field:{field.identity}:schema") for field in fields)
    team_completeness = _team_reference_completeness(runtime)
    obligations.extend(team_completeness["obligations"])
    return {
        "covered": len(obligations),
        "obligations": obligations,
        "sources": sources,
        "team_reference_completeness": team_completeness["sources"],
    }


def _catalog_obligation_total() -> int:
    schema_total = 1 + sum(
        2 + len(discover_fields(source=source.identity)) for source in _source_bindings()
    )
    return schema_total + 3


def _team_reference_completeness(runtime: PublishedDataRuntime) -> dict[str, Any]:
    reference = next(source for source in _source_bindings() if source.identity == "TeamReference")
    results = []
    obligations = []
    for source_identity in ("Batting", "Pitching", "Fielding"):
        source = next(source for source in _source_bindings() if source.identity == source_identity)
        sql = (
            'SELECT COUNT(*) FROM (SELECT DISTINCT "yearID", "teamID" '
            f'FROM "{source.relation}" WHERE "yearID" IS NOT NULL AND "teamID" IS NOT NULL '
            'EXCEPT SELECT "yearID", "teamID" '
            f'FROM "{reference.relation}") AS missing_team_identities'
        )
        with runtime.connection_lock:
            row = runtime.connection.execute(sql).fetchone()
        missing = int(row[0]) if row else -1
        if missing != 0:
            raise AssertionError(
                f"{source_identity} has {missing} season/team identities missing from TeamReference"
            )
        results.append({"source": source_identity, "missing_identities": missing})
        obligations.append(_passed(f"team-identity-completeness:{source_identity}"))
    return {"sources": results, "obligations": obligations}


def _raw_obligation_total() -> int:
    fields = discover_fields()
    return (
        len(fields) * 5 + sum(len(field.operations) for field in fields) + len(_source_bindings())
    )


def _raw_gate() -> dict[str, Any]:
    runtime = published_data_runtime()
    all_fields = discover_fields()
    discovered = catalog_payload()["fields"]
    identities = [str(item["identity"]) for item in discovered]
    expected = [field.identity for field in all_fields]
    if sorted(identities) != sorted(expected) or len(identities) != len(set(identities)):
        raise AssertionError("catalog discovery does not enumerate every raw field exactly once")
    obligations = [_passed(f"discovery:unfiltered:{field.identity}") for field in all_fields]
    source_pages: dict[str, int] = {}
    for source in _source_bindings():
        source_fields = discover_fields(source=source.identity)
        page_seen: list[str] = []
        for offset in range(0, len(source_fields), 7):
            page = catalog_payload(source=source.identity, offset=offset, limit=7)
            page_seen.extend(str(item["identity"]) for item in page["fields"])
        if page_seen != [item.identity for item in source_fields]:
            raise AssertionError(f"{source.identity} discovery pagination drifted")
        source_pages[source.identity] = len(page_seen)
        obligations.extend(_passed(f"discovery:source:{item.identity}") for item in source_fields)
        obligations.extend(_passed(f"discovery:page:{item.identity}") for item in source_fields)

    for field in all_fields:
        searched = catalog_payload(search=field.identity, limit=500)["fields"]
        if field.identity not in {item["identity"] for item in searched}:
            raise AssertionError(f"{field.identity} is unreachable through search")
        obligations.append(_passed(f"discovery:search:{field.identity}"))
        source = next(item for item in _source_bindings() if item.identity == field.source)
        sample_row = runtime.connection.execute(
            f'SELECT "{field.column}" FROM "{source.relation}" '
            f'WHERE "{field.column}" IS NOT NULL LIMIT 1'
        ).fetchone()
        if sample_row is None:
            raise AssertionError(f"{field.identity} has no typed probe value")
        sample = _literal(sample_row[0])
        first_page = execute(
            _require_ready(
                QueryRecipe(
                    source=field.source,
                    selections=(field.identity,),
                    output=InteractivePage(size=1, offset=0),
                ),
                f"{field.identity} first query page",
            )
        )
        second_page = execute(
            _require_ready(
                QueryRecipe(
                    source=field.source,
                    selections=(field.identity,),
                    output=InteractivePage(size=1, offset=1),
                ),
                f"{field.identity} second query page",
            )
        )
        if not isinstance(first_page, Rows) or not isinstance(second_page, Rows):
            raise AssertionError(f"{field.identity} query pagination did not return rows")
        if not isinstance(first_page.plan.output, InteractivePage) or not isinstance(
            second_page.plan.output, InteractivePage
        ):
            raise AssertionError(f"{field.identity} query pagination lost its page contract")
        if (
            first_page.plan.output.offset != 0
            or second_page.plan.output.offset != 1
            or len(first_page.rows) != 1
            or len(second_page.rows) != 1
            or first_page.evidence.matched_row_count != second_page.evidence.matched_row_count
        ):
            raise AssertionError(f"{field.identity} query pagination drifted")
        obligations.append(_passed(f"raw-query-pagination:{field.identity}"))
        for operation in field.operations:
            recipe = _raw_operation_recipe(field.identity, field.source, operation, sample)
            planned = prepare(recipe)
            if not isinstance(planned, Ready):
                raise AssertionError(f"{field.identity} {operation} did not plan: {planned}")
            outcome = execute(planned.plan)
            if not isinstance(outcome, (Rows, NoData, Exported)):
                raise AssertionError(f"{field.identity} {operation} did not execute: {outcome}")
            if "?" in outcome.evidence.parameterized_sql and not outcome.evidence.bound_values:
                raise AssertionError(f"{field.identity} lost bound values")
            obligations.append(_passed(f"raw-operation:{field.identity}:{operation}"))
    traversal = _full_row_gate()
    obligations.extend(traversal["obligations"])
    return {
        "covered": len(obligations),
        "obligations": obligations,
        "raw_fields": len(all_fields),
        "operation_obligations": sum(len(field.operations) for field in all_fields),
        "source_filter_and_pagination": source_pages,
        "traversals": traversal["sources"],
    }


def _raw_operation_recipe(
    identity: str, source: str, operation: str, sample: str | int | float
) -> QueryRecipe:
    predicate = Compare(identity, "equals", sample)
    if operation in {
        "equals",
        "not_equals",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
    }:
        predicate = Compare(identity, operation, sample)
    elif operation == "one_of":
        predicate = Compare(identity, operation, (sample,))
    elif operation == "range":
        predicate = Compare(identity, operation, (sample, sample))
    groupings = (identity,) if operation == "group" else ()
    ordering = (SortSpec(identity, "ascending"),) if operation == "sort" else ()
    output = Export("json") if operation == "export" else InteractivePage(size=1)
    return QueryRecipe(
        source=source,
        selections=(identity,),
        predicate=predicate,
        groupings=groupings,
        ordering=ordering,
        output=output,
    )


def _full_row_gate() -> dict[str, Any]:
    runtime = published_data_runtime()
    traversals = []
    for source in _source_bindings():
        fields = discover_fields(source=source.identity)
        planned = prepare(
            QueryRecipe(
                source=source.identity,
                selections=tuple(field.identity for field in fields),
                output=Export("json"),
            )
        )
        if not isinstance(planned, Ready):
            raise AssertionError(f"{source.identity} full export did not plan")
        outcome = execute(planned.plan)
        if not isinstance(outcome, Exported):
            raise AssertionError(f"{source.identity} full export did not execute")
        fingerprint = RowFingerprint()
        for row in outcome.rows:
            fingerprint.add(row[field.identity] for field in fields)
        observed = fingerprint.hexdigest()
        expected = runtime.source_fingerprints[source.identity]
        if observed != expected or len(outcome.rows) != outcome.evidence.matched_row_count:
            raise AssertionError(f"{source.identity} full traversal changed or omitted rows")
        traversals.append(
            {
                "identity": source.identity,
                "rows": len(outcome.rows),
                "expected_fingerprint": expected,
                "observed_fingerprint": observed,
            }
        )
    return {
        "covered": len(traversals),
        "obligations": [_passed(f"full-traversal:{item['identity']}") for item in traversals],
        "sources": traversals,
    }


def _promoted_obligation_total() -> int:
    operation_total = sum(
        len(value.allowed_grains) * len(value.operations) for value in published_values()
    )
    relationship_total = len(_relationship_bindings()) * 2
    rollup_total = sum(
        len(value.allowed_grains)
        + int(bool(set(_value_grains(published_values())) - set(value.allowed_grains)))
        for value in published_values()
        if value.rollup is not None
    )
    combination_total = sum(
        len(binding.grains) * (2 ** len(binding.sources) - len(binding.sources) - 1)
        for binding in _combination_bindings()
    )
    named_recipe_total = len(_named_recipe_bindings())
    golden_total = 5 + sum(value.kind == "calculation" for value in published_values())
    return (
        operation_total
        + relationship_total
        + rollup_total
        + combination_total
        + named_recipe_total
        + golden_total
    )


def _promoted_gate() -> dict[str, Any]:
    obligations = []
    values = published_values()
    for value in values:
        for grain_identity in value.allowed_grains:
            grain = grain_by_identity(grain_identity)
            if grain is None:
                raise AssertionError(f"{value.identity} names missing grain {grain_identity}")
            direct = direct_value_sources(value.identity)
            candidates = [source for source in grain.sources if source in direct] or list(
                grain.sources
            )
            for operation in value.operations:
                executed = _execute_promoted_operation(
                    value.identity,
                    value.data_type,
                    grain_identity,
                    operation,
                    candidates,
                )
                obligations.append(_passed(executed))

    relationship_result = _relationship_obligations()
    obligations.extend(relationship_result["obligations"])
    rollup_result = _rollup_obligations()
    obligations.extend(rollup_result["obligations"])
    combination_obligations = _combination_obligations()
    obligations.extend(_passed(identity) for identity in combination_obligations)
    recipe_obligations = _named_recipe_obligations()
    obligations.extend(_passed(identity) for identity in recipe_obligations)
    goldens = _golden_gate()
    obligations.extend(goldens["obligations"])
    if len(obligations) != _promoted_obligation_total():
        expected_total = _promoted_obligation_total()
        raise AssertionError(
            f"promoted obligation total drifted: {len(obligations)} != {expected_total}"
        )
    return {
        "covered": len(obligations),
        "obligations": obligations,
        "value_grain_obligations": sum(len(item.allowed_grains) for item in values),
        "operation_obligations": sum(
            len(item.allowed_grains) * len(item.operations) for item in values
        ),
        "calculation_value_grains_executed": sum(
            len(item.allowed_grains) for item in values if item.kind == "calculation"
        ),
        "rollup_value_grains_executed": sum(
            len(item.allowed_grains) for item in values if item.rollup is not None
        ),
        "rollup_assertions": rollup_result["asserted"],
        "relationship_directions": relationship_result["directions"],
        "relationships_observed_in_plans": relationship_result["observed"],
        "relationship_reverse_rejections": relationship_result["rejected"],
        "goldens": goldens["goldens"],
    }


def _execute_promoted_operation(
    identity: str,
    data_type: str,
    grain: str,
    operation: str,
    candidates: list[str],
) -> str:
    predicate = None
    groupings: tuple[str, ...] = ()
    ordering: tuple[SortSpec, ...] = ()
    output: InteractivePage | Export = InteractivePage(size=1)
    if operation in _filter_operations(data_type):
        literal = _promoted_probe(data_type)
        predicate_literal: Scalar | tuple[Scalar, ...] = (
            (literal, literal)
            if operation == "range"
            else (literal,)
            if operation == "one_of"
            else literal
        )
        predicate = Compare(identity, operation, predicate_literal)
    elif operation == "group":
        groupings = (identity,)
    elif operation == "sort":
        ordering = (SortSpec(identity, "ascending"),)
    elif operation == "export":
        output = Export("json")
    elif operation != "select":
        raise AssertionError(f"{identity} declares unknown operation {operation!r}")

    last_outcome: object | None = None
    for source in candidates:
        planned = prepare(
            QueryRecipe(
                source=source,
                grain=grain,
                selections=(identity,),
                predicate=predicate,
                groupings=groupings,
                ordering=ordering,
                output=output,
            )
        )
        if not isinstance(planned, Ready):
            last_outcome = planned
            continue
        outcome = execute(planned.plan)
        last_outcome = outcome
        expected = (Exported,) if operation == "export" else (Rows, NoData)
        if isinstance(outcome, expected):
            prefix = "promoted-filter" if operation in _filter_operations(data_type) else "promoted"
            return f"{prefix}:{identity}:{grain}:{operation}"
    raise AssertionError(
        f"{identity} {operation} at {grain} did not plan and execute: {last_outcome}"
    )


def _relationship_obligations() -> dict[str, Any]:
    obligations = []
    directions = []
    observed = []
    rejected = []
    values = published_values()
    for relationship in _relationship_bindings():
        if relationship.cardinality == "left_one_to_right_many":
            anchor = relationship.right_source
            lookup = relationship.left_source
        else:
            anchor = relationship.left_source
            lookup = relationship.right_source
        candidates = [
            (grain, value)
            for grain in _value_grains(values)
            for value in values
            if grain in value.allowed_grains
            and anchor
            in (grain_binding.sources if (grain_binding := grain_by_identity(grain)) else ())
            and lookup in direct_value_sources(value.identity)
            and anchor not in direct_value_sources(value.identity)
        ]
        if not candidates:
            raise AssertionError(
                f"relationship {relationship.identity} has no published safe lookup direction"
            )
        grain, value = candidates[0]
        planned = prepare(
            QueryRecipe(
                source=anchor,
                grain=grain,
                selections=(value.identity,),
                output=InteractivePage(size=1),
            )
        )
        direction = f"{relationship.identity}:{anchor}->{lookup}"
        if (
            not isinstance(planned, Ready)
            or relationship.identity not in planned.plan.relationships
        ):
            raise AssertionError(f"relationship {direction} was not selected by planning")
        outcome = execute(planned.plan)
        if not isinstance(outcome, (Rows, NoData)):
            raise AssertionError(f"relationship {direction} did not execute")
        evidence_sources = {source.identity for source in outcome.evidence.sources}
        if not {anchor, lookup} <= evidence_sources:
            raise AssertionError(f"relationship {direction} lost source evidence")
        obligations.append(_passed(f"relationship:{direction}"))
        directions.append(direction)
        observed.append(direction)
        fact_value = next(
            (
                candidate
                for candidate in values
                if anchor in direct_value_sources(candidate.identity)
                and any(
                    anchor in grain_binding.sources
                    for grain_identity in candidate.allowed_grains
                    if (grain_binding := grain_by_identity(grain_identity)) is not None
                )
            ),
            None,
        )
        if fact_value is None:
            raise AssertionError(f"relationship {relationship.identity} has no fact-side probe")
        reverse_grain = next(
            grain_identity
            for grain_identity in fact_value.allowed_grains
            if (grain_binding := grain_by_identity(grain_identity)) is not None
            and anchor in grain_binding.sources
        )
        reverse = prepare(
            QueryRecipe(
                source=lookup,
                grain=reverse_grain,
                selections=(fact_value.identity,),
                output=InteractivePage(size=1),
            )
        )
        reverse_direction = f"{relationship.identity}:{lookup}->{anchor}"
        if not isinstance(reverse, Rejected):
            raise AssertionError(
                f"multiplicative relationship direction {reverse_direction} was not rejected"
            )
        obligations.append(_passed(f"relationship-reverse-rejected:{reverse_direction}"))
        rejected.append(reverse_direction)
    return {
        "obligations": obligations,
        "directions": directions,
        "observed": observed,
        "rejected": rejected,
    }


def _rollup_obligations() -> dict[str, Any]:
    obligations = []
    asserted = []
    all_grains = _value_grains(published_values())
    for value in published_values():
        if value.rollup is None:
            continue
        binding = promoted_value_by_identity(value.identity)
        if binding is None:
            raise AssertionError(f"rollup value {value.identity} is stale")
        for grain_identity in value.allowed_grains:
            grain = grain_by_identity(grain_identity)
            if grain is None:
                raise AssertionError(f"rollup value {value.identity} has a stale grain")
            direct = direct_value_sources(value.identity)
            candidates = [source for source in grain.sources if source in direct] or list(
                grain.sources
            )
            outcome = None
            for source in candidates:
                planned = prepare(
                    QueryRecipe(
                        source=source,
                        grain=grain_identity,
                        selections=(value.identity,),
                        output=InteractivePage(size=1),
                    )
                )
                if not isinstance(planned, Ready):
                    continue
                outcome = execute(planned.plan)
                if isinstance(outcome, (Rows, NoData)):
                    break
            if not isinstance(outcome, (Rows, NoData)):
                raise AssertionError(
                    f"{value.rollup} rollup {value.identity} at {grain_identity} did not execute"
                )
            if value.rollup == "recompute":
                calculation = next(
                    (
                        item
                        for item in outcome.evidence.calculations
                        if item.identity == value.identity
                    ),
                    None,
                )
                if (
                    calculation is None
                    or calculation.formula != binding.formula
                    or calculation.inputs != binding.components
                ):
                    raise AssertionError(
                        f"recomputed rollup {value.identity} lost formula/component evidence"
                    )
            identity = f"rollup-allowed:{value.rollup}:{value.identity}:{grain_identity}"
            obligations.append(_passed(identity))
            asserted.append(identity)
        forbidden_grains = tuple(grain for grain in all_grains if grain not in value.allowed_grains)
        if forbidden_grains:
            forbidden_grain = grain_by_identity(forbidden_grains[0])
            if forbidden_grain is None:
                raise AssertionError(f"forbidden rollup grain {forbidden_grains[0]} is stale")
            forbidden = prepare(
                QueryRecipe(
                    source=forbidden_grain.sources[0],
                    grain=forbidden_grains[0],
                    selections=(value.identity,),
                    output=InteractivePage(size=1),
                )
            )
            if not isinstance(forbidden, Rejected):
                raise AssertionError(
                    f"rollup {value.identity} accepted forbidden grain {forbidden_grains[0]}"
                )
            identity = f"rollup-forbidden:{value.identity}:{forbidden_grains[0]}"
            obligations.append(_passed(identity))
            asserted.append(identity)
    return {"obligations": obligations, "asserted": asserted}


def _value_grains(values: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(grain for value in values for grain in value.allowed_grains))


def _calculation_golden_checks() -> list[str]:
    batting = _run(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=(
                "batting.H",
                "batting.AB",
                "batting.BB",
                "batting.HBP",
                "batting.SF",
                "batting.2B",
                "batting.3B",
                "batting.HR",
                "batting.AVG",
                "batting.OBP",
                "batting.SLG",
                "batting.OPS",
            ),
            predicate=Compare("batting.AB", "greater_than", 0),
            output=InteractivePage(size=1),
        )
    )
    pitching = _run(
        QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=(
                "pitching.ER",
                "pitching.IPouts",
                "pitching.BB",
                "pitching.H",
                "pitching.IP",
                "pitching.ERA",
                "pitching.WHIP",
            ),
            predicate=Compare("pitching.IPouts", "greater_than", 0),
            output=InteractivePage(size=1),
        )
    )
    fielding = _run(
        QueryRecipe(
            source="Fielding",
            grain="player-position-season",
            selections=(
                "fielding.InnOuts",
                "fielding.PO",
                "fielding.A",
                "fielding.E",
                "fielding.innings",
                "fielding.FPCT",
            ),
            predicate=Compare("fielding.PO", "greater_than", 0),
            output=InteractivePage(size=1),
        )
    )
    if (
        not isinstance(batting, Rows)
        or not isinstance(pitching, Rows)
        or not isinstance(fielding, Rows)
    ):
        raise AssertionError("calculation golden fixtures returned no rows")

    batting_row = batting.rows[0]
    hits = _numeric(batting_row, "batting.H")
    at_bats = _numeric(batting_row, "batting.AB")
    walks = _numeric(batting_row, "batting.BB")
    hit_by_pitch = _numeric(batting_row, "batting.HBP")
    sacrifice_flies = _numeric(batting_row, "batting.SF")
    doubles = _numeric(batting_row, "batting.2B")
    triples = _numeric(batting_row, "batting.3B")
    home_runs = _numeric(batting_row, "batting.HR")
    expected_avg = hits / at_bats
    expected_obp = (hits + walks + hit_by_pitch) / (
        at_bats + walks + hit_by_pitch + sacrifice_flies
    )
    expected_slg = (hits + doubles + 2 * triples + 3 * home_runs) / at_bats
    expected_ops = expected_obp + expected_slg

    pitching_row = pitching.rows[0]
    pitching_outs = _numeric(pitching_row, "pitching.IPouts")
    expected_ip = pitching_outs // 3 + (pitching_outs % 3) / 10.0
    expected_era = 27 * _numeric(pitching_row, "pitching.ER") / pitching_outs
    expected_whip = (
        3
        * (_numeric(pitching_row, "pitching.BB") + _numeric(pitching_row, "pitching.H"))
        / pitching_outs
    )

    fielding_row = fielding.rows[0]
    fielding_outs = _numeric(fielding_row, "fielding.InnOuts")
    putouts = _numeric(fielding_row, "fielding.PO")
    assists = _numeric(fielding_row, "fielding.A")
    errors = _numeric(fielding_row, "fielding.E")
    expected_fielding_innings = fielding_outs // 3 + (fielding_outs % 3) / 10.0
    expected_fpct = (putouts + assists) / (putouts + assists + errors)

    expected = {
        "batting.AVG": (batting_row, expected_avg),
        "batting.OBP": (batting_row, expected_obp),
        "batting.SLG": (batting_row, expected_slg),
        "batting.OPS": (batting_row, expected_ops),
        "pitching.IP": (pitching_row, expected_ip),
        "pitching.ERA": (pitching_row, expected_era),
        "pitching.WHIP": (pitching_row, expected_whip),
        "fielding.innings": (fielding_row, expected_fielding_innings),
        "fielding.FPCT": (fielding_row, expected_fpct),
    }
    checks = []
    for identity, (row, expected_value) in expected.items():
        if not isclose(_numeric(row, identity), expected_value):
            raise AssertionError(f"{identity} did not match independent recomputation")
        checks.append(f"{identity} independent recomputation")
    return checks


def _numeric(row: Mapping[str, Any], identity: str) -> float:
    value = row.get(identity)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise AssertionError(f"{identity} did not produce a numeric calculation value")
    return float(value)


def _golden_gate() -> dict[str, Any]:
    checks = []
    rbi = _run_question("who had the most RBIs in 1962")
    _require_rows(rbi, [("Tommy Davis", 153)], ("player.name", "batting.RBI"))
    checks.append("1962 RBI Tommy Davis 153")

    forty = build_named_recipe("batting.40-40")
    if not isinstance(forty, QueryRecipe):
        raise AssertionError("40-40 recipe unavailable")
    forty_run = _run(forty)
    names = [row["player.name"] for row in forty_run.rows]
    if names != [
        "Jose Canseco",
        "Barry Bonds",
        "Alex Rodriguez",
        "Alfonso Soriano",
        "Ronald Acuña",
        "Shohei Ohtani",
    ]:
        raise AssertionError("40-40 golden changed")
    checks.append("six exact 40-40 rows")

    checks.extend(_calculation_golden_checks())

    duffy = _run(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.name", "season", "batting.H", "batting.AB", "batting.AVG"),
            predicate=All(
                (
                    Compare("season", "equals", 1894),
                    Compare("batting.AB", "greater_or_equal", 100),
                )
            ),
            ranking=RankSpec("batting.AVG", "highest", 1, "include_ties"),
        )
    )
    if (duffy.rows[0]["player.name"], duffy.rows[0]["batting.H"], duffy.rows[0]["batting.AB"]) != (
        "Hugh Duffy",
        237,
        539,
    ):
        raise AssertionError("Duffy explicit-floor golden changed")
    checks.append("Hugh Duffy 237/539")

    ohtani = _run_question("players with at least 30 HR and 10 pitching wins in one season")
    observed = [(row["season"], row["batting.HR"], row["pitching.W"]) for row in ohtani.rows]
    if observed != [(2022, 34, 15), (2023, 44, 10)]:
        raise AssertionError("Ohtani cross-discipline golden changed")
    checks.append("Ohtani independently aggregated seasons")

    tied = _run(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.id", "season", "batting.HR"),
            predicate=Compare("season", "equals", 2021),
            ranking=RankSpec("batting.HR", "highest", 1, "include_ties"),
        )
    )
    if [(row["player.id"], row["batting.HR"]) for row in tied.rows] != [
        ("guerrvl02", 48),
        ("perezsa02", 48),
    ]:
        raise AssertionError("2021 tie golden changed")
    checks.append("2021 home-run tie")
    obligations = [_passed(f"golden:{index}:{name}") for index, name in enumerate(checks, 1)]
    return {"covered": len(obligations), "obligations": obligations, "goldens": checks}


def _plan_safety_gate() -> dict[str, Any]:
    checks = []
    recipe = QueryRecipe(
        source="People",
        selections=("People.nameLast",),
        predicate=Compare("People.nameLast", "equals", "O'Neil'); DROP TABLE people; --"),
    )
    planned = prepare(recipe)
    if not isinstance(planned, Ready):
        raise AssertionError("adversarial literal did not plan as data")
    if QueryPlanV1.from_json(planned.plan.to_json()) != planned.plan:
        raise AssertionError("canonical plan round trip changed")
    checks.extend(["canonical serialization", "round-trip stability"])
    outcome = execute(planned.plan)
    if not isinstance(outcome, NoData):
        raise AssertionError("adversarial literal did not execute safely")
    if "DROP TABLE" in outcome.evidence.parameterized_sql or not outcome.evidence.bound_values:
        raise AssertionError("user literal reached compiled SQL")
    checks.append("parameterized adversarial literals")
    stale = prepare(replace(recipe, catalog_revision="stale"))
    if not isinstance(stale, Rejected):
        raise AssertionError("stale recipe reached compilation")
    checks.append("catalog pinning")
    arbitrary = prepare(replace(recipe, selections=("formula:People.ID+1",), predicate=None))
    if not isinstance(arbitrary, Rejected):
        raise AssertionError("arbitrary formula reached compilation")
    checks.append("formula allow-list")
    unsafe = execute(replace(planned.plan, source="People; DROP TABLE pitching"))
    if not isinstance(unsafe, ExecutionUnavailable):
        raise AssertionError("forged identifier reached SQL")
    checks.append("compiler-owned identifiers")
    tie = _run(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.id", "season", "batting.HR"),
            predicate=Compare("season", "equals", 2021),
            ranking=RankSpec("batting.HR", "highest", 1, "include_ties"),
        )
    )
    if len(tie.rows) != 2:
        raise AssertionError("include-ties plan is not deterministic")
    checks.append("deterministic ties")
    if "ROW_NUMBER()" not in outcome.evidence.parameterized_sql:
        raise AssertionError("raw rows lack deterministic total ordering")
    checks.append("deterministic total ordering")
    asserted = [f"safety:behavior:{index}:{name}" for index, name in enumerate(checks, 1)]
    asserted.extend(_plan_matrix_obligations())
    obligations = [_passed(identity) for identity in asserted]
    if len(obligations) != _plan_safety_obligation_total():
        raise AssertionError("plan safety obligation matrix drifted")
    return {
        "covered": len(obligations),
        "obligations": obligations,
        "asserted_obligations": asserted,
        "checks": checks,
    }


def _outcome_gate() -> dict[str, Any]:
    checks = []
    clarification = prepare(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.name", "batting.AVG"),
            ranking=RankSpec("batting.AVG", "highest", 1, "include_ties"),
        )
    )
    if not isinstance(clarification, NeedsClarification):
        raise AssertionError("clarification outcome unavailable")
    checks.append("NeedsClarification")
    rejected = prepare(QueryRecipe(source="Batting", selections=("not.published",)))
    if not isinstance(rejected, Rejected):
        raise AssertionError("rejected outcome unavailable")
    checks.append("Rejected")
    base = prepare(QueryRecipe(source="People", selections=("People.playerID",)))
    if not isinstance(base, Ready):
        raise AssertionError("outcome fixture did not plan")
    unavailable = execute(replace(base.plan, catalog_revision="stale"))
    if not isinstance(unavailable, ExecutionUnavailable):
        raise AssertionError("unavailable outcome unavailable")
    checks.append("ExecutionUnavailable")
    runtime = published_data_runtime()
    failing_runtime = SimpleNamespace(
        connection=SimpleNamespace(
            execute=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("deterministic execution failure")
            )
        ),
        connection_lock=runtime.connection_lock,
    )
    with patch("baseball_rag.query.service.published_data_runtime", return_value=failing_runtime):
        failed = execute(base.plan)
    if (
        not isinstance(failed, ExecutionFailed)
        or "deterministic execution failure" not in failed.reason
    ):
        raise AssertionError("failed outcome contract unavailable")
    checks.append("ExecutionFailed")
    no_data = _run(
        QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.name", "season", "batting.HR"),
            predicate=All(
                (
                    Compare("season", "equals", 2024),
                    Compare("batting.HR", "greater_or_equal", 100),
                )
            ),
        ),
        allow_no_data=True,
    )
    if not isinstance(no_data, NoData) or no_data.evidence.matched_row_count != 0:
        raise AssertionError("NoData evidence is incomplete")
    _assert_evidence(no_data)
    checks.append("NoData")
    rows = _run_question("who had the most RBIs in 1962")
    _assert_evidence(rows)
    checks.append("Rows")
    export = _run(
        QueryRecipe(
            source="People",
            selections=("People.playerID",),
            predicate=Compare("People.playerID", "equals", "aaronha01"),
            output=Export("csv"),
        )
    )
    if not isinstance(export, Exported) or "aaronha01" not in export.content:
        raise AssertionError("export outcome or evidence is incomplete")
    _assert_evidence(export)
    checks.append("Exported")
    obligations = [_passed(f"outcome:{name}") for name in checks]
    asserted_evidence = _evidence_obligations(rows, no_data, export)
    obligations.extend(_passed(identity) for identity in asserted_evidence)
    return {
        "covered": len(obligations),
        "obligations": obligations,
        "outcomes": checks,
        "asserted_evidence": asserted_evidence,
    }


def _outcome_obligation_total() -> int:
    return 7 + 15


def _evidence_obligations(rows: Rows, no_data: NoData, exported: Exported) -> list[str]:
    evidence = rows.evidence
    asserted: list[str] = []
    if QueryPlanV1.from_json(rows.plan.to_json()) != rows.plan:
        raise AssertionError("evidence plan is not canonically serializable")
    asserted.append("evidence:canonical-plan")
    if evidence.catalog_revision != rows.plan.catalog_revision:
        raise AssertionError("evidence catalog revision does not bind the plan")
    asserted.append("evidence:catalog-revision")
    if not evidence.data_release:
        raise AssertionError("evidence data release is missing")
    asserted.append("evidence:data-release")
    if not evidence.parameterized_sql or "?" not in evidence.parameterized_sql:
        raise AssertionError("evidence parameterized SQL is missing")
    asserted.append("evidence:parameterized-sql")
    if not evidence.bound_values or 1962 not in evidence.bound_values:
        raise AssertionError("evidence bound values are missing")
    asserted.append("evidence:bound-values")
    if not evidence.sources or any(
        not source.identity
        or not source.release
        or not source.row_fingerprint
        or source.expected_rows is None
        for source in evidence.sources
    ):
        raise AssertionError("evidence source metadata is incomplete")
    asserted.append("evidence:source-metadata")
    if evidence.row_count != len(rows.rows):
        raise AssertionError("evidence row count is not the immutable result size")
    asserted.append("evidence:row-count")
    if evidence.matched_row_count < evidence.row_count:
        raise AssertionError("evidence matched count is smaller than the returned count")
    asserted.append("evidence:matched-row-count")
    if not evidence.result_fingerprint:
        raise AssertionError("evidence result fingerprint is missing")
    asserted.append("evidence:result-fingerprint")
    immutable_probe: Any = rows.rows[0]
    try:
        immutable_probe["player.name"] = "forged"
    except TypeError:
        pass
    else:
        raise AssertionError("Query Run rows are mutable")
    asserted.append("evidence:immutable-rows")
    judge = _run_question("Aaron Judge's 2022 OPS")
    if not judge.evidence.calculations or any(
        not calculation.identity or not calculation.formula or not calculation.inputs
        for calculation in judge.evidence.calculations
    ):
        raise AssertionError("calculation evidence is incomplete")
    asserted.append("evidence:calculation-metadata")
    for label, outcome in (("Rows", rows), ("NoData", no_data), ("Exported", exported)):
        _assert_evidence(outcome)
        asserted.append(f"evidence:{label}-bundle")
    proof_identity = current_proof_identity()
    if (
        proof_identity["catalog_revision"] != evidence.catalog_revision
        or proof_identity["data_release"] != evidence.data_release
        or any(
            proof_identity["source_fingerprints"].get(source.identity) != source.row_fingerprint
            for source in evidence.sources
        )
    ):
        raise AssertionError("Query Run evidence does not bind the current proof identity")
    asserted.append("evidence:proof-identity")
    if len(asserted) != 15:
        raise AssertionError("evidence assertion matrix drifted")
    return asserted


def _independence_gate() -> dict[str, Any]:
    forbidden = ("baseball_rag.generation", "requests", "lmstudio", "darwin", "/users/")
    inspected = []
    module_names = (
        "adapters.py",
        "compiler.py",
        "contracts.py",
        "coverage.py",
        "fingerprint.py",
        "promoted.py",
        "recipe_adapter.py",
        "registry.py",
        "runtime.py",
        "service.py",
    )
    for name in module_names:
        path = Path(__file__).resolve().with_name(name)
        content = path.read_text(encoding="utf-8").casefold()
        hits = [token for token in forbidden if token in content]
        if hits:
            raise AssertionError(f"{path.name} has forbidden runtime dependency: {hits}")
        inspected.append(path.name)
    obligations = [
        _passed("independence:no-llm-import"),
        _passed("independence:no-network-runtime"),
        _passed("independence:no-mac-runtime"),
        _passed("independence:packaged-catalog"),
        _passed("independence:packaged-data"),
    ]
    return {
        "covered": len(obligations),
        "obligations": obligations,
        "network": "denied/not required",
        "inspected_modules": inspected,
    }


def _run_question(question: str) -> Rows:
    recipe = interpret_recipe(question)
    if not isinstance(recipe, QueryRecipe):
        raise AssertionError(f"question did not produce a recipe: {question}")
    outcome = _run(recipe)
    if not isinstance(outcome, Rows):
        raise AssertionError(f"question did not return rows: {question}")
    return outcome


def _require_ready(recipe: QueryRecipe, label: str) -> QueryPlanV1:
    planned = prepare(recipe)
    if not isinstance(planned, Ready):
        raise AssertionError(f"{label} did not plan: {planned}")
    return planned.plan


def _run(recipe: QueryRecipe, *, allow_no_data: bool = False) -> Rows | NoData | Exported:
    planned = prepare(recipe)
    if not isinstance(planned, Ready):
        raise AssertionError(f"recipe did not plan: {planned}")
    outcome = execute(planned.plan)
    if isinstance(outcome, (Rows, Exported)):
        return outcome
    if allow_no_data and isinstance(outcome, NoData):
        return outcome
    raise AssertionError(f"recipe did not execute successfully: {outcome}")


def _require_rows(outcome: Rows, expected: list[tuple[Any, ...]], keys: tuple[str, ...]) -> None:
    observed = [tuple(row[key] for key in keys) for row in outcome.rows]
    if observed != expected:
        raise AssertionError(f"golden rows changed: expected {expected}, observed {observed}")


def _assert_evidence(outcome: Rows | NoData | Exported) -> None:
    evidence = outcome.evidence
    if (
        not evidence.parameterized_sql
        or not evidence.catalog_revision
        or not evidence.data_release
        or not evidence.sources
        or not evidence.result_fingerprint
        or evidence.row_count != len(outcome.rows)
    ):
        raise AssertionError("Query Run evidence bundle is incomplete")


def _literal(value: object) -> str | int | float:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (str, int, float)):
        return value
    raise TypeError(f"unsupported raw probe literal: {type(value).__name__}")


def _filter_operations(data_type: str) -> tuple[str, ...]:
    if data_type == "text":
        return ("equals", "one_of")
    if data_type == "date":
        return ("equals", "before", "after", "range")
    return (
        "equals",
        "not_equals",
        "greater_than",
        "greater_or_equal",
        "less_than",
        "less_or_equal",
        "range",
    )


def _promoted_probe(data_type: str) -> str | int | float:
    if data_type == "text":
        return "coverage-probe"
    if data_type == "date":
        return "2000-01-01"
    if data_type == "integer":
        return 0
    return 0.0


def _combination_obligations() -> list[str]:
    values = {"Batting": "batting.HR", "Pitching": "pitching.W", "Fielding": "fielding.PO"}
    identities = []
    for grain in ("player-team-season", "player-season", "player-career"):
        for count in (2, 3):
            for subset in combinations(values, count):
                binding = combination_for(set(subset), grain)
                if binding is None:
                    raise AssertionError(f"combination missing for {subset} at {grain}")
                recipe = QueryRecipe(
                    source=subset[0],
                    grain=grain,
                    selections=tuple(values[source] for source in subset),
                    output=InteractivePage(size=1),
                )
                planned = prepare(recipe)
                if not isinstance(planned, Ready):
                    raise AssertionError(f"combination did not plan for {subset} at {grain}")
                outcome = execute(planned.plan)
                if not isinstance(outcome, (Rows, NoData)):
                    raise AssertionError(f"combination did not execute for {subset} at {grain}")
                identities.append(f"combination:{'+'.join(subset)}:{grain}")
    if len(identities) != 12:
        raise AssertionError("combination matrix must contain twelve cases")
    return identities


def _named_recipe_obligations() -> list[str]:
    cases: tuple[tuple[str, dict[str, Any]], ...] = (
        ("batting.30-30", {}),
        ("batting.40-40", {}),
        ("batting.500-home-runs", {}),
        ("batting.triple-crown", {"year": 2012, "league": "AL"}),
    )
    identities = []
    for identity, parameters in cases:
        recipe = build_named_recipe(identity, **parameters)
        if not isinstance(recipe, QueryRecipe):
            raise AssertionError(f"named recipe {identity} did not resolve")
        outcome = _run(recipe, allow_no_data=True)
        if not isinstance(outcome, (Rows, NoData)):
            raise AssertionError(f"named recipe {identity} did not execute")
        identities.append(f"named-recipe:{identity}")
    return identities


_PLAN_GRAINS = (
    "raw_rows",
    "group_by",
    "player-record",
    "player-team-season",
    "player-season",
    "player-season-league",
    "player-career",
    "team-season",
    "league-season",
    "player-position-season",
    "player-position-career",
)
_PLAN_PREDICATES = ("compare", "all", "any", "not")
_PLAN_RANKS = ("highest-include-ties", "highest-exact", "lowest-include-ties", "lowest-exact")
_PLAN_SORTS = ("ascending-first", "ascending-last", "descending-first", "descending-last")
_PLAN_OUTPUTS = ("interactive-page", "csv-export", "json-export")
_PLAN_DATA_TYPES = ("text", "integer", "number", "date", "baseball-innings")
_PLAN_LITERALS = ("scalar", "sequence", "value-reference")
_PLAN_ADVERSARIAL = (
    "stale-catalog",
    "stale-field",
    "invalid-type",
    "ambiguous-grain",
    "ambiguous-relationship",
    "forbidden-operation",
    "forged-source",
    "sql-like-literal",
)


def _plan_safety_obligation_total() -> int:
    return 8 + sum(
        len(items)
        for items in (
            _PLAN_GRAINS,
            _PLAN_PREDICATES,
            _PLAN_RANKS,
            _PLAN_SORTS,
            _PLAN_OUTPUTS,
            _PLAN_DATA_TYPES,
            _PLAN_LITERALS,
            _PLAN_ADVERSARIAL,
        )
    )


def _plan_matrix_obligations() -> list[str]:
    asserted: list[str] = []
    grain_cases = {
        "raw_rows": QueryRecipe(source="People", selections=("People.playerID",)),
        "group_by": QueryRecipe(
            source="People",
            selections=("People.birthCountry",),
            groupings=("People.birthCountry",),
        ),
        "player-record": QueryRecipe(
            source="People", grain="player-record", selections=("player.id",)
        ),
        "player-team-season": QueryRecipe(
            source="Batting", grain="player-team-season", selections=("player.id",)
        ),
        "player-season": QueryRecipe(
            source="Batting", grain="player-season", selections=("player.id",)
        ),
        "player-season-league": QueryRecipe(
            source="Batting", grain="player-season-league", selections=("league",)
        ),
        "player-career": QueryRecipe(
            source="Batting", grain="player-career", selections=("player.id",)
        ),
        "team-season": QueryRecipe(source="Batting", grain="team-season", selections=("season",)),
        "league-season": QueryRecipe(
            source="Batting", grain="league-season", selections=("season",)
        ),
        "player-position-season": QueryRecipe(
            source="Fielding", grain="player-position-season", selections=("position",)
        ),
        "player-position-career": QueryRecipe(
            source="Fielding", grain="player-position-career", selections=("position",)
        ),
    }
    for identity in _PLAN_GRAINS:
        _execute_matrix_recipe(grain_cases[identity], f"grain {identity}")
        asserted.append(f"safety:grain:{identity}")

    compare = Compare("People.nameLast", "equals", "Aaron")
    predicate_cases: dict[str, Predicate] = {
        "compare": compare,
        "all": All((compare, Compare("People.nameFirst", "equals", "Hank"))),
        "any": AnyPredicate((compare, Compare("People.nameLast", "equals", "Mays"))),
        "not": Not(compare),
    }
    for identity in _PLAN_PREDICATES:
        _execute_matrix_recipe(
            QueryRecipe(
                source="People",
                selections=("People.playerID",),
                predicate=predicate_cases[identity],
            ),
            f"predicate {identity}",
        )
        asserted.append(f"safety:predicate:{identity}")

    for identity in _PLAN_RANKS:
        direction, tie_label = identity.split("-", 1)
        tie_policy = "include_ties" if tie_label == "include-ties" else "exact_count"
        _execute_matrix_recipe(
            QueryRecipe(
                source="Batting",
                grain="player-season",
                selections=("player.id", "season", "batting.HR"),
                predicate=Compare("season", "equals", 2021),
                ranking=RankSpec("batting.HR", direction, 1, tie_policy),
            ),
            f"rank {identity}",
        )
        asserted.append(f"safety:rank:{identity}")

    for identity in _PLAN_SORTS:
        direction, nulls = identity.split("-", 1)
        _execute_matrix_recipe(
            QueryRecipe(
                source="People",
                selections=("People.playerID",),
                ordering=(SortSpec("People.playerID", direction, nulls),),
            ),
            f"sort {identity}",
        )
        asserted.append(f"safety:sort:{identity}")

    outputs: dict[str, InteractivePage | Export] = {
        "interactive-page": InteractivePage(size=1, offset=1),
        "csv-export": Export("csv"),
        "json-export": Export("json"),
    }
    for identity in _PLAN_OUTPUTS:
        outcome = _execute_matrix_recipe(
            QueryRecipe(
                source="People",
                selections=("People.playerID",),
                predicate=Compare("People.playerID", "equals", "aaronha01"),
                output=outputs[identity],
            ),
            f"output {identity}",
        )
        if identity.endswith("export") and not isinstance(outcome, Exported):
            raise AssertionError(f"output {identity} did not export")
        asserted.append(f"safety:output:{identity}")

    data_type_cases = {
        "text": QueryRecipe(
            source="People",
            selections=("People.nameLast",),
            predicate=Compare("People.nameLast", "equals", "Aaron"),
        ),
        "integer": QueryRecipe(
            source="Batting",
            selections=("Batting.yearID",),
            predicate=Compare("Batting.yearID", "equals", 2021),
        ),
        "number": QueryRecipe(
            source="Pitching",
            selections=("Pitching.ERA",),
            predicate=Compare("Pitching.ERA", "greater_or_equal", 0.0),
        ),
        "date": QueryRecipe(
            source="People",
            selections=("People.debut",),
            predicate=Compare("People.debut", "greater_than", "2000-01-01"),
        ),
        "baseball-innings": QueryRecipe(
            source="Fielding",
            grain="player-position-season",
            selections=("fielding.innings",),
            predicate=Compare("fielding.innings", "greater_or_equal", 0.0),
        ),
    }
    for identity in _PLAN_DATA_TYPES:
        _execute_matrix_recipe(data_type_cases[identity], f"data type {identity}")
        asserted.append(f"safety:data-type:{identity}")

    literal_cases = {
        "scalar": QueryRecipe(
            source="People",
            selections=("People.playerID",),
            predicate=Compare("People.playerID", "equals", "aaronha01"),
        ),
        "sequence": QueryRecipe(
            source="People",
            selections=("People.playerID",),
            predicate=Compare("People.playerID", "one_of", ("aaronha01", "mayswi01")),
        ),
        "value-reference": QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.id", "batting.HR", "batting.SB"),
            predicate=Compare("batting.HR", "equals", ValueRef("batting.SB")),
        ),
    }
    for identity in _PLAN_LITERALS:
        _execute_matrix_recipe(literal_cases[identity], f"literal {identity}")
        asserted.append(f"safety:literal:{identity}")

    safe = prepare(QueryRecipe(source="People", selections=("People.playerID",)))
    if not isinstance(safe, Ready):
        raise AssertionError("adversarial matrix fixture did not plan")
    adversarial_checks: dict[str, Callable[[], bool]] = {
        "stale-catalog": lambda: isinstance(
            prepare(
                QueryRecipe(
                    source="People",
                    selections=("People.playerID",),
                    catalog_revision="stale",
                )
            ),
            Rejected,
        ),
        "stale-field": lambda: isinstance(
            prepare(QueryRecipe(source="People", selections=("People.missing",))), Rejected
        ),
        "invalid-type": lambda: isinstance(
            prepare(
                QueryRecipe(
                    source="Batting",
                    selections=("Batting.yearID",),
                    predicate=Compare("Batting.yearID", "equals", "2021"),
                )
            ),
            Rejected,
        ),
        "ambiguous-grain": lambda: isinstance(
            prepare(QueryRecipe(source="Batting", grain="season-ish", selections=("batting.HR",))),
            Rejected,
        ),
        "ambiguous-relationship": lambda: isinstance(
            execute(replace(safe.plan, relationships=("team-reference-to-batting",))),
            ExecutionUnavailable,
        ),
        "forbidden-operation": lambda: isinstance(
            prepare(
                QueryRecipe(
                    source="People",
                    selections=("People.playerID",),
                    predicate=Compare("People.playerID", "contains", "aaron"),
                )
            ),
            Rejected,
        ),
        "forged-source": lambda: isinstance(
            execute(replace(safe.plan, source="People; DROP TABLE pitching")),
            ExecutionUnavailable,
        ),
        "sql-like-literal": lambda: _sql_like_literal_is_bound(),
    }
    for identity in _PLAN_ADVERSARIAL:
        if not adversarial_checks[identity]():
            raise AssertionError(f"adversarial case {identity} did not fail safely")
        asserted.append(f"safety:adversarial:{identity}")
    return asserted


def _execute_matrix_recipe(recipe: QueryRecipe, label: str) -> Rows | NoData | Exported:
    planned = prepare(recipe)
    if not isinstance(planned, Ready):
        raise AssertionError(f"{label} did not plan: {planned}")
    outcome = execute(planned.plan)
    if not isinstance(outcome, (Rows, NoData, Exported)):
        raise AssertionError(f"{label} did not execute: {outcome}")
    return outcome


def _sql_like_literal_is_bound() -> bool:
    literal = "O'Neil'); DROP TABLE people; --"
    outcome = _execute_matrix_recipe(
        QueryRecipe(
            source="People",
            selections=("People.playerID",),
            predicate=Compare("People.nameLast", "equals", literal),
        ),
        "SQL-like literal",
    )
    return (
        literal not in outcome.evidence.parameterized_sql
        and literal in outcome.evidence.bound_values
    )


def _passed(identity: str) -> dict[str, str]:
    return {"identity": identity, "status": "passing"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if checked-in proof differs")
    args = parser.parse_args()
    report = generate_coverage_report()
    machine = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    human = render_coverage_markdown(report)
    if args.check:
        if (
            not COVERAGE_REPORT_PATH.exists()
            or COVERAGE_REPORT_PATH.read_text(encoding="utf-8") != machine
            or not COVERAGE_MARKDOWN_PATH.exists()
            or COVERAGE_MARKDOWN_PATH.read_text(encoding="utf-8") != human
        ):
            raise SystemExit("Checked-in Coverage Report is stale; regenerate it.")
    else:
        write_coverage_report(report)
    if report["status"] != "passing":
        raise SystemExit("Coverage Report failed:\n" + "\n".join(report["failures"]))


if __name__ == "__main__":
    main()
