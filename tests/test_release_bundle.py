from __future__ import annotations

import csv
import hashlib
import json
import shutil
from pathlib import Path

import pytest

from baseball_rag.release_bundle import (
    ReleaseBundleError,
    assemble_release_bundle,
    check_release_bundle,
)

SOURCE_COMMIT = "a" * 40


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode() if isinstance(content, str) else content)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.reader(handle)) - 1


def _source_tree(root: Path) -> None:
    _write(root / "LICENSE", "Fixture MIT License\n")
    csvs = {
        "People.csv": "playerID,nameFirst,nameLast\ndavisto02,Tommy,Davis\n",
        "Batting.csv": "playerID,yearID,HR\ndavisto02,1962,27\n",
        "Pitching.csv": "playerID,yearID,W\nohtash01,2022,15\n",
        "Fielding.csv": "playerID,yearID,POS\ndavisto02,1962,OF\n",
    }
    lahman_files = []
    for filename, content in csvs.items():
        path = root / "data" / filename
        _write(path, content)
        table = filename.removesuffix(".csv").lower()
        lahman_files.append(
            {
                "path": f"data/{filename}",
                "table": table,
                "rows": 1,
                "year_coverage": (
                    None
                    if filename == "People.csv"
                    else {
                        "min": 1962 if filename != "Pitching.csv" else 2022,
                        "max": 1962 if filename != "Pitching.csv" else 2022,
                    }
                ),
                "sha256": _sha(path),
                "source_url": f"https://example.invalid/{filename}",
            }
        )
    data_manifest = {
        "dataset": {
            "name": "fixture Lahman",
            "source_url": "https://example.invalid/lahman",
            "upstream": "Lahman Baseball Database",
            "release_id": "lahman-fixture-v1",
            "upstream_release": "fixture-2025",
            "license": "CC BY-SA 3.0",
        },
        "coverage": {"structured_stat_years": {"min": 1962, "max": 2022}},
        "files": lahman_files,
    }
    _write(root / "data/manifest.json", _json_bytes(data_manifest))

    projection = root / "data/secondary_sources/retrosheet/pitcher_strikeout_side_events.csv"
    _write(projection, "pitcher_id,game_date,strikeouts\ndavisto02,1962-04-10,3\n")
    retrosheet_manifest = {
        "dataset": {
            "name": "Retrosheet CSV daily logs and local derived projections",
            "source_url": "https://www.retrosheet.org/events/",
            "attribution": "Copyright Retrosheet; used with required attribution.",
            "license_notes": "Free to use with attribution; no accuracy guarantee.",
        },
        "coverage": {"year_coverage": {"min": 1962, "max": 1962}},
        "download": {"downloaded_at": "2026-07-03T16:12:21-04:00"},
        "files": [
            {
                "archive": "pitching.zip",
                "path": "data/secondary_sources/retrosheet/pitching.zip",
                "table": "unsupported_raw_archive",
                "rows": 99,
                "sha256": "0" * 64,
            },
            {
                "path": "data/secondary_sources/retrosheet/pitcher_strikeout_side_events.csv",
                "source_url": "https://www.retrosheet.org/events/",
                "table": "retrosheet_pitcher_strikeout_side_events",
                "kind": "event_derived_evidence",
                "provenance": {
                    "event_archives_accessed_at": "2026-07-03T13:52:15-04:00",
                    "projection_generated_at": "2026-07-03T13:52:15-04:00",
                    "generation_tool": (
                        "python -m baseball_rag.db.secondary_sources.retrosheet_events"
                    ),
                    "derivation": "Derived from fixture Retrosheet event archives.",
                },
                "rows": 1,
                "year_coverage": {"min": 1962, "max": 1962},
                "sha256": _sha(projection),
            },
        ],
    }
    _write(
        root / "data/secondary_sources/retrosheet/manifest.json",
        _json_bytes(retrosheet_manifest),
    )

    catalog_dir = root / "src/baseball_rag/query/catalog"
    assets = catalog_dir / "assets"
    _write(assets / "team_reference.csv", "yearID,teamID,name\n1962,LAN,Los Angeles Dodgers\n")
    _write(
        assets / "retrosheet_team_reference.csv",
        "yearID,retrosheetTeamID,name\n1962,LAN,Los Angeles Dodgers\n",
    )
    _write(
        assets / "team_reference.manifest.json",
        _json_bytes(
            {
                "columns": ["yearID", "teamID", "name"],
                "reference_version": "season-aware-v1",
                "rows": 1,
                "sha256": _sha(assets / "team_reference.csv"),
                "source": {"name": "Lahman Teams", "url": "https://example.invalid/teams"},
            }
        ),
    )
    _write(
        assets / "retrosheet_team_reference.manifest.json",
        _json_bytes(
            {
                "columns": ["yearID", "retrosheetTeamID", "name"],
                "reference_version": "retrosheet-season-aware-v1",
                "rows": 1,
                "sha256": _sha(assets / "retrosheet_team_reference.csv"),
                "sources": [
                    {"name": "Retrosheet teams", "url": "https://example.invalid/retro-teams"}
                ],
            }
        ),
    )
    registry = {"registry_revision": "lahman-sources-v1", "sources": []}
    inventory = {"inventory_revision": "raw-fields-fixture-v1", "fields": []}
    promoted_names = [
        "promoted_common.json",
        "promoted_batting.json",
        "promoted_people.json",
        "promoted_pitching.json",
        "promoted_fielding.json",
    ]
    catalog = {
        "catalog_revision": "published-query-catalog-fixture-v1",
        "raw_inventory_revision": inventory["inventory_revision"],
        "promoted": promoted_names,
    }
    _write(catalog_dir / "published_sources.json", _json_bytes(registry))
    _write(catalog_dir / "raw_fields.json", _json_bytes(inventory))
    _write(catalog_dir / "published_catalog.json", _json_bytes(catalog))
    for name in promoted_names:
        _write(catalog_dir / name, _json_bytes({"definitions": [], "schema_version": 1}))

    semantic_data = {
        "release_id": data_manifest["dataset"]["release_id"],
        "files": sorted(
            [
                {
                    "path": item["path"],
                    "table": item["table"],
                    "rows": item["rows"],
                    "year_coverage": item["year_coverage"],
                    "sha256": item["sha256"],
                }
                for item in lahman_files
            ],
            key=lambda item: item["table"],
        ),
    }
    compatibility = {
        "catalog_revision": catalog["catalog_revision"],
        "catalog_sha256": _sha(catalog_dir / "published_catalog.json"),
        "data_manifest_semantic_sha256": hashlib.sha256(
            json.dumps(semantic_data, separators=(",", ":"), sort_keys=True).encode()
        ).hexdigest(),
        "promoted_catalog_sha256": {name: _sha(catalog_dir / name) for name in promoted_names},
        "raw_inventory_revision": inventory["inventory_revision"],
        "raw_inventory_sha256": _sha(catalog_dir / "raw_fields.json"),
        "source_registry_revision": registry["registry_revision"],
        "source_registry_sha256": _sha(catalog_dir / "published_sources.json"),
        "team_reference_revision": "season-aware-v1",
        "team_reference_manifest_sha256": _sha(assets / "team_reference.manifest.json"),
    }
    _write(catalog_dir / "compatibility.json", _json_bytes(compatibility))

    catalog_proof = hashlib.sha256()
    for path in (*sorted(catalog_dir.glob("*.json")), *sorted(assets.glob("*"))):
        catalog_proof.update(path.name.encode())
        catalog_proof.update(b"\0")
        catalog_proof.update(path.read_bytes())
        catalog_proof.update(b"\0")

    coverage = {
        "schema_version": "query-coverage-report-v1",
        "status": "passing",
        "failures": [],
        "summary": {"covered": 0, "total": 0, "uncovered": 0},
        "proof_identity": {
            "report_schema_version": "query-coverage-report-v1",
            "catalog_revision": catalog["catalog_revision"],
            "catalog_sha256": catalog_proof.hexdigest(),
            "data_release": data_manifest["dataset"]["release_id"],
            "data_manifest_semantic_sha256": compatibility["data_manifest_semantic_sha256"],
            "compiler_contract": "query-plan-v1",
            "compiler_sha256": "1" * 64,
            "source_fingerprints": {},
        },
        "gates": [
            {
                "identity": identity,
                "status": "passing",
                "covered": 0,
                "total": 0,
                "failures": [],
                "obligations": [],
            }
            for identity in (
                "catalog_schema_identity",
                "raw_reachability",
                "promoted_exactness",
                "plan_compiler_safety",
                "outcome_evidence_integrity",
                "no_llm_no_mac",
            )
        ],
    }
    coverage["proof_id"] = hashlib.sha256(
        json.dumps(coverage, separators=(",", ":"), sort_keys=True).encode()
    ).hexdigest()
    _write(root / "src/baseball_rag/query/coverage/coverage-report.json", _json_bytes(coverage))

    legal_dir = root / "release/legal"
    for name, owner in (
        ("ground-ball.json", "Ground Ball contributors"),
        ("lahman-neuml.json", "Lahman Baseball Database and NeuML"),
        ("retrosheet.json", "Retrosheet"),
    ):
        _write(
            legal_dir / name,
            _json_bytes(
                {
                    "schema_version": "ground-ball-legal-record-v1",
                    "owner": owner,
                    "license": "fixture-license",
                    "source": "https://example.invalid/source",
                    "attribution": f"Attribution for {owner}",
                    "notice": f"Notice for {owner}",
                    "disclaimer": "Provided without warranty.",
                }
            ),
        )


def test_assembly_is_reproducible_and_manifest_is_the_bundle_identity(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_tree(source)

    first = assemble_release_bundle(source, tmp_path / "one", source_commit=SOURCE_COMMIT)
    second = assemble_release_bundle(source, tmp_path / "two", source_commit=SOURCE_COMMIT)

    first_bytes = first.manifest_path.read_bytes()
    assert first.digest == hashlib.sha256(first_bytes).hexdigest()
    assert second.digest == first.digest
    assert (tmp_path / "one/release-manifest.json").read_bytes() == (
        tmp_path / "two/release-manifest.json"
    ).read_bytes()
    assert check_release_bundle(tmp_path / "one", expected_source_commit=SOURCE_COMMIT) == first

    manifest = json.loads(first_bytes)
    assert len(manifest["payload"]) == 25
    assert (tmp_path / "one/legal/ground-ball-license.txt").read_text() == ("Fixture MIT License\n")
    assert "release-manifest.json" not in {item["path"] for item in manifest["payload"]}
    projection_manifest = json.loads(
        (tmp_path / "one/data/secondary_sources/retrosheet/manifest.json").read_text()
    )
    assert [item["path"] for item in projection_manifest["files"]] == [
        "data/secondary_sources/retrosheet/pitcher_strikeout_side_events.csv"
    ]
    assert "archive" not in projection_manifest["files"][0]
    assert projection_manifest["projection_identity"] == ("retrosheet-pitcher-strikeout-side-v1")
    assert projection_manifest["upstream_release"] == (
        "Retrosheet event archives through 1962; accessed 2026-07-03T13:52:15-04:00"
    )
    source_manifest_bytes = (
        source / "data/secondary_sources/retrosheet/manifest.json"
    ).read_bytes()
    assert projection_manifest["provenance"]["source_manifest_bytes_sha256"] == (
        hashlib.sha256(source_manifest_bytes).hexdigest()
    )
    notices = {item["path"]: item["notice"] for item in manifest["payload"]}
    assert notices["legal/lahman-neuml.json"] == "legal/lahman-neuml.json"
    assert notices["legal/retrosheet.json"] == "legal/retrosheet.json"


@pytest.mark.parametrize("mutation", ["extra", "missing", "tampered"])
def test_checker_fails_closed_on_payload_drift(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "source"
    _source_tree(source)
    assemble_release_bundle(source, tmp_path / "original", source_commit=SOURCE_COMMIT)
    shutil.copytree(tmp_path / "original", tmp_path / mutation)

    if mutation == "extra":
        _write(tmp_path / mutation / "cache.duckdb", "not allowed")
    elif mutation == "missing":
        (tmp_path / mutation / "data/People.csv").unlink()
    else:
        _write(tmp_path / mutation / "data/People.csv", "playerID\nchanged\n")

    with pytest.raises(ReleaseBundleError):
        check_release_bundle(tmp_path / mutation, expected_source_commit=SOURCE_COMMIT)


def test_assembly_rejects_false_source_identity_and_malformed_proof(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_tree(source)

    with pytest.raises(ReleaseBundleError, match="full lowercase Git commit hash"):
        assemble_release_bundle(source, tmp_path / "bad-commit", source_commit="not-a-commit")

    coverage_path = source / "src/baseball_rag/query/coverage/coverage-report.json"
    coverage = json.loads(coverage_path.read_text())
    coverage["gates"] = "not-a-list"
    coverage["proof_id"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in coverage.items() if key != "proof_id"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    _write(coverage_path, _json_bytes(coverage))

    with pytest.raises(ReleaseBundleError, match="Coverage Report gates"):
        assemble_release_bundle(source, tmp_path / "bad-proof", source_commit=SOURCE_COMMIT)


def test_assembly_rejects_malformed_coverage_obligation(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _source_tree(source)
    coverage_path = source / "src/baseball_rag/query/coverage/coverage-report.json"
    coverage = json.loads(coverage_path.read_text())
    coverage["gates"][0].update({"covered": 1, "total": 1, "obligations": [None]})
    coverage["summary"].update({"covered": 1, "total": 1})
    coverage["proof_id"] = hashlib.sha256(
        json.dumps(
            {key: value for key, value in coverage.items() if key != "proof_id"},
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    _write(coverage_path, _json_bytes(coverage))

    with pytest.raises(ReleaseBundleError, match="malformed obligation"):
        assemble_release_bundle(source, tmp_path / "bad-obligation", source_commit=SOURCE_COMMIT)
