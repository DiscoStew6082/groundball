"""Complete raw-surface behavior through the published query Interfaces."""

import hashlib
import json
import shutil
from collections import Counter
from dataclasses import replace
from pathlib import Path

from baseball_rag.query import (
    All,
    Compare,
    ExecutionUnavailable,
    Export,
    Exported,
    InteractivePage,
    QueryRecipe,
    Ready,
    Rows,
    SortSpec,
    discover_fields,
    execute,
    prepare,
)
from baseball_rag.query import runtime as query_runtime
from baseball_rag.query.generate_catalog_compatibility import render_compatibility
from baseball_rag.query.generate_raw_inventory import render_inventory
from baseball_rag.query.registry import CATALOG_DIR


def test_discovery_exposes_every_raw_field_exactly_once():
    fields = discover_fields()

    assert len(fields) == 98
    assert len({field.identity for field in fields}) == 98
    assert Counter(field.source for field in fields) == {
        "People": 25,
        "Batting": 22,
        "Pitching": 30,
        "Fielding": 18,
        "TeamReference": 3,
    }


def test_checked_in_inventory_and_compatibility_are_generated_from_full_inputs():
    inventory = render_inventory(Path("data"))
    compatibility = render_compatibility(Path("data"))

    assert (CATALOG_DIR / "raw_fields.json").read_bytes() == inventory
    assert (CATALOG_DIR / "compatibility.json").read_bytes() == compatibility
    payload = json.loads(compatibility)
    source_registry = CATALOG_DIR / "published_sources.json"
    assert (
        payload["source_registry_sha256"]
        == hashlib.sha256(source_registry.read_bytes()).hexdigest()
    )
    assert payload["source_registry_revision"] == "lahman-sources-v1"
    assert payload["team_reference_revision"] == "season-aware-v1"
    assert (
        payload["catalog_sha256"]
        == hashlib.sha256((CATALOG_DIR / "published_catalog.json").read_bytes()).hexdigest()
    )
    assert (
        payload["team_reference_manifest_sha256"]
        == hashlib.sha256(
            (CATALOG_DIR / "assets/team_reference.manifest.json").read_bytes()
        ).hexdigest()
    )
    assert (
        payload["raw_inventory_sha256"]
        == hashlib.sha256((CATALOG_DIR / "raw_fields.json").read_bytes()).hexdigest()
    )
    published = json.loads((CATALOG_DIR / "published_catalog.json").read_text())
    assert payload["promoted_catalog_sha256"] == {
        filename: hashlib.sha256((CATALOG_DIR / filename).read_bytes()).hexdigest()
        for filename in published["promoted"]
    }


def test_raw_numeric_filters_sorting_and_paging_are_deterministic():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            selections=("Batting.playerID", "Batting.yearID", "Batting.GIDP"),
            predicate=All(
                (
                    Compare("Batting.yearID", "equals", 2024),
                    Compare("Batting.GIDP", "greater_than", 0),
                )
            ),
            ordering=(
                SortSpec("Batting.GIDP", "descending"),
                SortSpec("Batting.playerID", "ascending"),
            ),
            output=InteractivePage(size=5, offset=0),
        )
    )
    assert isinstance(planned, Ready)

    first_page = execute(planned.plan)
    second_page = execute(replace(planned.plan, output=InteractivePage(size=5, offset=5)))

    assert isinstance(first_page, Rows)
    assert isinstance(second_page, Rows)
    assert len(first_page.rows) == len(second_page.rows) == 5
    assert {tuple(row.items()) for row in first_page.rows}.isdisjoint(
        {tuple(row.items()) for row in second_page.rows}
    )
    assert [row["Batting.GIDP"] for row in first_page.rows] == sorted(
        (row["Batting.GIDP"] for row in first_page.rows), reverse=True
    )
    assert first_page.evidence.matched_row_count > len(first_page.rows)


def test_exhausted_page_is_empty_rows_without_erasing_the_match_count():
    planned = prepare(
        QueryRecipe(
            source="People",
            selections=("People.playerID",),
            predicate=Compare("People.birthCity", "equals", "Brooklyn"),
            output=InteractivePage(size=25, offset=100_000),
        )
    )
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert executed.rows == ()
    assert executed.evidence.matched_row_count > 0


def test_raw_grouping_returns_each_distinct_value_once():
    planned = prepare(
        QueryRecipe(
            source="Batting",
            selections=("Batting.lgID",),
            groupings=("Batting.lgID",),
            ordering=(SortSpec("Batting.lgID", "ascending"),),
        )
    )
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    leagues = [row["Batting.lgID"] for row in executed.rows]
    assert leagues == sorted(set(leagues), key=lambda value: (value is None, value))


def test_export_contains_the_full_match_set_not_only_the_interactive_page():
    recipe = QueryRecipe(
        source="People",
        selections=("People.playerID", "People.birthCity"),
        predicate=Compare("People.birthCity", "equals", "Brooklyn"),
        ordering=(SortSpec("People.playerID", "ascending"),),
        output=Export(format="json"),
    )
    planned = prepare(recipe)
    assert isinstance(planned, Ready)

    exported = execute(planned.plan)
    page = execute(replace(planned.plan, output=InteractivePage(size=25)))

    assert isinstance(exported, Exported)
    assert isinstance(page, Rows)
    decoded = json.loads(exported.content)
    assert len(decoded) == exported.evidence.matched_row_count == len(exported.rows)
    assert len(decoded) > len(page.rows)
    assert decoded[:25] == [dict(row) for row in page.rows]


def test_representative_published_source_export_preserves_complete_rows_and_evidence():
    source = "TeamReference"
    expected_rows = 3_613
    selections = tuple(field.identity for field in discover_fields(source=source))
    planned = prepare(
        QueryRecipe(
            source=source,
            selections=selections,
            output=Export(format="csv"),
        )
    )
    assert isinstance(planned, Ready)

    exported = execute(planned.plan)

    assert isinstance(exported, Exported)
    assert exported.evidence.matched_row_count == expected_rows
    assert exported.evidence.row_count == expected_rows
    assert exported.evidence.sources[0].expected_rows == expected_rows
    assert exported.evidence.sources[0].row_fingerprint == _row_fingerprint(
        exported.rows, selections
    )
    assert exported.evidence.result_fingerprint


def test_incompatible_installed_schema_is_unavailable_before_query_execution(tmp_path, monkeypatch):
    source_dir = Path("data").resolve()
    shutil.copyfile(source_dir / "manifest.json", tmp_path / "manifest.json")
    for filename in ("Batting.csv", "Pitching.csv", "Fielding.csv"):
        (tmp_path / filename).symlink_to(source_dir / filename)
    (tmp_path / "People.csv").write_text(
        "playerID,birthCity,unexpected\nprobe01,Brooklyn,drift\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GROUNDBALL_DATA_DIR", str(tmp_path))
    planned = prepare(QueryRecipe(source="People", selections=("People.playerID",)))
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, ExecutionUnavailable)
    assert "checksum" in executed.reason


def test_missing_installed_manifest_is_a_typed_unavailable_outcome(tmp_path, monkeypatch):
    monkeypatch.setenv("GROUNDBALL_DATA_DIR", str(tmp_path))
    planned = prepare(QueryRecipe(source="People", selections=("People.playerID",)))
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, ExecutionUnavailable)
    assert "manifest" in executed.reason.lower()


def test_missing_catalog_asset_is_a_typed_unavailable_outcome(tmp_path, monkeypatch):
    planned = prepare(QueryRecipe(source="People", selections=("People.playerID",)))
    assert isinstance(planned, Ready)
    monkeypatch.setattr(query_runtime, "CATALOG_DIR", tmp_path)
    monkeypatch.setenv("GROUNDBALL_DATA_DIR", str(tmp_path / "uninstalled-data"))

    executed = execute(planned.plan)

    assert isinstance(executed, ExecutionUnavailable)
    assert "catalog asset" in executed.reason.lower()


def test_date_values_are_normalized_to_public_json_scalars():
    planned = prepare(
        QueryRecipe(
            source="People",
            selections=("People.playerID", "People.debut"),
            predicate=Compare("People.playerID", "equals", "aaronha01"),
        )
    )
    assert isinstance(planned, Ready)

    executed = execute(planned.plan)

    assert isinstance(executed, Rows)
    assert executed.rows[0]["People.debut"] == "1954-04-13"


def test_every_raw_field_prepares_every_declared_generic_operation():
    samples = {
        "text": "probe",
        "integer": 1,
        "number": 1.5,
        "date": "2000-01-01",
    }
    for field in discover_fields():
        base = QueryRecipe(source=field.source, selections=(field.identity,))
        assert isinstance(prepare(base), Ready), field.identity
        for operation in field.operations:
            if operation == "select":
                recipe = base
            elif operation == "group":
                recipe = replace(base, groupings=(field.identity,))
            elif operation == "sort":
                recipe = replace(
                    base,
                    ordering=(SortSpec(field.identity, "ascending"),),
                )
            elif operation == "export":
                recipe = replace(base, output=Export("json"))
            else:
                sample = samples[field.data_type]
                literal = (sample, sample) if operation in {"one_of", "range"} else sample
                recipe = replace(
                    base,
                    predicate=Compare(field.identity, operation, literal),
                )
            planned = prepare(recipe)
            assert isinstance(planned, Ready), (field.identity, operation, planned)


def _row_fingerprint(rows, columns):
    modulus = 1 << 256
    digest_sum = 0
    digest_xor = 0
    for row in rows:
        encoded = json.dumps(
            [row[column] for column in columns],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        value = int.from_bytes(hashlib.sha256(encoded).digest())
        digest_sum = (digest_sum + value) % modulus
        digest_xor ^= value
    summary = f"{len(rows)}:{digest_sum:064x}:{digest_xor:064x}".encode()
    return hashlib.sha256(summary).hexdigest()
