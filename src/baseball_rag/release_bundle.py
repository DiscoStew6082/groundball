"""Assemble and verify the immutable provider-neutral Release Bundle."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

MANIFEST_FILENAME = "release-manifest.json"
MANIFEST_SCHEMA = "ground-ball-release-manifest-v1"
PROJECTION_MANIFEST_SCHEMA = "ground-ball-retrosheet-projection-manifest-v1"
LEGAL_SCHEMA = "ground-ball-legal-record-v1"
REQUIRED_COVERAGE_GATE_IDS = frozenset(
    {
        "catalog_schema_identity",
        "raw_reachability",
        "promoted_exactness",
        "plan_compiler_safety",
        "outcome_evidence_integrity",
        "no_llm_no_mac",
    }
)
_FULL_SHA256 = re.compile(r"[0-9a-f]{64}")
_FULL_COMMIT = re.compile(r"[0-9a-f]{40}")

_LAHMAN_CSVS = (
    "data/Batting.csv",
    "data/Fielding.csv",
    "data/People.csv",
    "data/Pitching.csv",
)
_PROJECTION_PATH = "data/secondary_sources/retrosheet/pitcher_strikeout_side_events.csv"
_PROJECTION_MANIFEST_PATH = "data/secondary_sources/retrosheet/manifest.json"
_CATALOG_ROOT = "src/baseball_rag/query/catalog"
_PROMOTED = (
    "promoted_batting.json",
    "promoted_common.json",
    "promoted_fielding.json",
    "promoted_people.json",
    "promoted_pitching.json",
)
_CATALOG_ROOT_FILES = (
    "compatibility.json",
    *_PROMOTED,
    "published_catalog.json",
    "published_sources.json",
    "raw_fields.json",
)
_CATALOG_ASSETS = (
    "retrosheet_team_reference.csv",
    "retrosheet_team_reference.manifest.json",
    "team_reference.csv",
    "team_reference.manifest.json",
)
_COVERAGE_PATH = "src/baseball_rag/query/coverage/coverage-report.json"
_LEGAL_SOURCE_PATHS = (
    "release/legal/ground-ball.json",
    "release/legal/lahman-neuml.json",
    "release/legal/retrosheet.json",
)
_SPECIAL_SOURCE_BUNDLE_PATHS = (("LICENSE", "legal/ground-ball-license.txt"),)
_LEGAL_BUNDLE_PATHS = (
    "legal/ground-ball.json",
    "legal/lahman-neuml.json",
    "legal/retrosheet.json",
)

_DIRECT_PATHS = (
    *_LAHMAN_CSVS,
    "data/manifest.json",
    _PROJECTION_PATH,
    *(f"{_CATALOG_ROOT}/{name}" for name in _CATALOG_ROOT_FILES),
    *(f"{_CATALOG_ROOT}/assets/{name}" for name in _CATALOG_ASSETS),
    _COVERAGE_PATH,
)
_PAYLOAD_PATHS = tuple(
    sorted(
        (
            *_DIRECT_PATHS,
            _PROJECTION_MANIFEST_PATH,
            *_LEGAL_BUNDLE_PATHS,
            *(bundle for _source, bundle in _SPECIAL_SOURCE_BUNDLE_PATHS),
        )
    )
)


class ReleaseBundleError(ValueError):
    """The candidate payload cannot be identified as a valid Release Bundle."""


@dataclass(frozen=True)
class ReleaseBundleIdentity:
    """The immutable identity and canonical manifest location for a checked bundle."""

    digest: str
    manifest_path: Path


def assemble_release_bundle(
    source_root: Path | str,
    bundle_root: Path | str,
    *,
    source_commit: str,
) -> ReleaseBundleIdentity:
    """Assemble one exact payload and return its canonical manifest identity.

    ``source_root`` is a repository-shaped input tree. ``bundle_root`` must not
    already exist, so a failed assembly cannot overwrite a previously checked
    immutable bundle.
    """
    source = Path(source_root)
    destination = Path(bundle_root)
    _validate_source_commit(source_commit)
    if destination.exists() or destination.is_symlink():
        raise ReleaseBundleError(f"Bundle destination already exists: {destination}")
    if not source.is_dir() or source.is_symlink():
        raise ReleaseBundleError("Release source root is missing or is a symlink.")

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        for relative in _DIRECT_PATHS:
            source_path = source / relative
            _require_regular_file(source, source_path, relative)
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
        for source_relative, bundle_relative in zip(
            _LEGAL_SOURCE_PATHS, _LEGAL_BUNDLE_PATHS, strict=True
        ):
            source_path = source / source_relative
            _require_regular_file(source, source_path, source_relative)
            target = temporary / bundle_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)
        for source_relative, bundle_relative in _SPECIAL_SOURCE_BUNDLE_PATHS:
            source_path = source / source_relative
            _require_regular_file(source, source_path, source_relative)
            target = temporary / bundle_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_path, target)

        source_projection_manifest_path = source / _PROJECTION_MANIFEST_PATH
        source_projection_manifest_bytes = _read_bytes(
            source_projection_manifest_path, _PROJECTION_MANIFEST_PATH
        )
        projection_manifest = _projection_only_manifest(
            _decode_object(source_projection_manifest_bytes, _PROJECTION_MANIFEST_PATH),
            source_manifest_bytes_sha256=hashlib.sha256(
                source_projection_manifest_bytes
            ).hexdigest(),
        )
        _write_canonical_json(temporary / _PROJECTION_MANIFEST_PATH, projection_manifest)
        manifest = _expected_manifest(temporary, source_commit)
        _write_canonical_json(temporary / MANIFEST_FILENAME, manifest)
        checked = check_release_bundle(temporary, expected_source_commit=source_commit)
        os.replace(temporary, destination)
        return ReleaseBundleIdentity(checked.digest, destination / MANIFEST_FILENAME)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def check_release_bundle(
    bundle_root: Path | str,
    *,
    expected_source_commit: str | None = None,
) -> ReleaseBundleIdentity:
    """Fail closed unless ``bundle_root`` is the exact canonical Release Bundle."""
    root = Path(bundle_root)
    if not root.is_dir() or root.is_symlink():
        raise ReleaseBundleError("Release Bundle root is missing or is a symlink.")
    if expected_source_commit is not None:
        _validate_source_commit(expected_source_commit)
    observed_paths = _bundle_file_paths(root)
    expected_paths = set(_PAYLOAD_PATHS) | {MANIFEST_FILENAME}
    missing = sorted(expected_paths - observed_paths)
    extra = sorted(observed_paths - expected_paths)
    if missing or extra:
        raise ReleaseBundleError(
            f"Release Bundle payload mismatch; missing={missing!r}, extra={extra!r}."
        )

    manifest_path = root / MANIFEST_FILENAME
    manifest_bytes = _read_bytes(manifest_path, MANIFEST_FILENAME)
    manifest = _decode_object(manifest_bytes, MANIFEST_FILENAME)
    if manifest_bytes != _canonical_json_bytes(manifest):
        raise ReleaseBundleError("Release Manifest is not canonical JSON.")
    source_commit = manifest.get("source_commit")
    if not isinstance(source_commit, str):
        raise ReleaseBundleError("Release Manifest source commit is malformed.")
    _validate_source_commit(source_commit)
    if expected_source_commit is not None and source_commit != expected_source_commit:
        raise ReleaseBundleError("Release Manifest source commit does not match expectation.")

    expected_manifest = _expected_manifest(root, source_commit)
    if manifest != expected_manifest:
        raise ReleaseBundleError("Release Manifest is stale or does not match its payload.")
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return ReleaseBundleIdentity(digest=digest, manifest_path=manifest_path)


def _expected_manifest(root: Path, source_commit: str) -> dict[str, object]:
    context = _validate_governed_payload(root)
    entries = [_payload_entry(root, path, context) for path in _PAYLOAD_PATHS]
    legal_records = context["legal_records"]
    return {
        "schema_version": MANIFEST_SCHEMA,
        "source_commit": source_commit,
        "payload": entries,
        "identities": {
            "data_release": context["data_release"],
            "source_registry_revision": context["registry_revision"],
            "catalog_revision": context["catalog_revision"],
            "raw_inventory_revision": context["inventory_revision"],
            "compatibility_sha256": _sha256(root / f"{_CATALOG_ROOT}/compatibility.json"),
            "coverage_report": {
                "proof_id": context["coverage"]["proof_id"],
                "proof_identity": context["coverage"]["proof_identity"],
            },
            "team_references": {
                "lahman": context["team_manifest"]["reference_version"],
                "retrosheet": context["retrosheet_team_manifest"]["reference_version"],
            },
            "retrosheet_projection": context["projection_identity"],
        },
        "coverage": {
            "lahman": context["data_manifest"].get("coverage"),
            "retrosheet_projection": context["projection_entry"].get("year_coverage"),
            "coverage_report_schema": context["coverage"]["schema_version"],
        },
        "upstream": {
            "lahman": context["data_manifest"]["dataset"],
            "retrosheet": {
                "dataset": context["projection_manifest"]["dataset"],
                "upstream_release": context["projection_manifest"]["upstream_release"],
                "provenance": context["projection_manifest"]["provenance"],
            },
            "team_references": {
                "lahman": context["team_manifest"].get("source"),
                "retrosheet": context["retrosheet_team_manifest"].get("sources"),
            },
        },
        "license_notice_ownership": [
            {
                "path": path,
                "owner": record["owner"],
                "license": record["license"],
            }
            for path, record in zip(_LEGAL_BUNDLE_PATHS, legal_records, strict=True)
        ],
    }


def _validate_governed_payload(root: Path) -> dict[str, Any]:
    for relative in _PAYLOAD_PATHS:
        _require_regular_file(root, root / relative, relative)

    data_manifest = _read_object(root / "data/manifest.json", "data/manifest.json")
    dataset = _require_object(data_manifest.get("dataset"), "data manifest dataset")
    data_release = _require_string(dataset.get("release_id"), "data release identity")
    files = _require_object_list(data_manifest.get("files"), "data manifest files")
    expected_lahman = set(_LAHMAN_CSVS)
    by_path = {_require_string(item.get("path"), "data manifest file path"): item for item in files}
    if set(by_path) != expected_lahman or len(by_path) != len(files):
        raise ReleaseBundleError("Lahman source manifest does not describe exactly four tables.")
    for relative in _LAHMAN_CSVS:
        _validate_declared_csv(root, relative, by_path[relative])

    projection_manifest = _read_object(root / _PROJECTION_MANIFEST_PATH, _PROJECTION_MANIFEST_PATH)
    if projection_manifest.get("schema_version") != PROJECTION_MANIFEST_SCHEMA:
        raise ReleaseBundleError("Retrosheet projection manifest schema is invalid.")
    if "download" in projection_manifest:
        raise ReleaseBundleError("Projection manifest contains acquisition metadata.")
    projection_identity = _require_string(
        projection_manifest.get("projection_identity"), "Retrosheet projection identity"
    )
    _require_string(projection_manifest.get("upstream_release"), "Retrosheet upstream release")
    projection_provenance = _require_object(
        projection_manifest.get("provenance"), "Retrosheet projection provenance"
    )
    for field in (
        "event_archives_accessed_at",
        "projection_generated_at",
        "generation_tool",
        "source_manifest_bytes_sha256",
        "derivation",
    ):
        _require_string(projection_provenance.get(field), f"projection provenance {field}")
    if not _FULL_SHA256.fullmatch(str(projection_provenance["source_manifest_bytes_sha256"])):
        raise ReleaseBundleError("Projection provenance source manifest digest is malformed.")
    projection_files = _require_object_list(
        projection_manifest.get("files"), "projection manifest files"
    )
    if len(projection_files) != 1 or projection_files[0].get("path") != _PROJECTION_PATH:
        raise ReleaseBundleError("Projection manifest describes unsupported Retrosheet members.")
    projection_entry = projection_files[0]
    if "archive" in projection_entry:
        raise ReleaseBundleError("Projection manifest references a raw archive.")
    _validate_declared_csv(root, _PROJECTION_PATH, projection_entry)

    catalog_dir = root / _CATALOG_ROOT
    catalog = _read_object(catalog_dir / "published_catalog.json", "published catalog")
    registry = _read_object(catalog_dir / "published_sources.json", "source registry")
    inventory = _read_object(catalog_dir / "raw_fields.json", "raw inventory")
    compatibility = _read_object(catalog_dir / "compatibility.json", "compatibility")
    catalog_revision = _require_string(catalog.get("catalog_revision"), "catalog revision")
    registry_revision = _require_string(registry.get("registry_revision"), "registry revision")
    inventory_revision = _require_string(inventory.get("inventory_revision"), "inventory revision")
    promoted = catalog.get("promoted")
    if not isinstance(promoted, list) or sorted(promoted) != sorted(_PROMOTED):
        raise ReleaseBundleError("Published Query Catalog promoted set is not exact.")
    bindings: tuple[tuple[str, object, str], ...] = (
        ("catalog_revision", catalog_revision, "catalog revision"),
        ("catalog_sha256", _sha256(catalog_dir / "published_catalog.json"), "catalog digest"),
        ("data_manifest_semantic_sha256", _semantic_manifest_sha256(data_manifest), "data release"),
        ("raw_inventory_revision", inventory_revision, "raw inventory revision"),
        ("raw_inventory_sha256", _sha256(catalog_dir / "raw_fields.json"), "raw inventory digest"),
        ("source_registry_revision", registry_revision, "source registry revision"),
        (
            "source_registry_sha256",
            _sha256(catalog_dir / "published_sources.json"),
            "source registry digest",
        ),
    )
    if catalog.get("raw_inventory_revision") != inventory_revision:
        raise ReleaseBundleError("Published Query Catalog references a stale raw inventory.")
    for key, expected, label in bindings:
        if compatibility.get(key) != expected:
            raise ReleaseBundleError(f"Compatibility binding has stale {label}.")
    promoted_hashes = compatibility.get("promoted_catalog_sha256")
    if not isinstance(promoted_hashes, dict) or set(promoted_hashes) != set(_PROMOTED):
        raise ReleaseBundleError("Compatibility binding has a mismatched promoted set.")
    for filename in _PROMOTED:
        if promoted_hashes.get(filename) != _sha256(catalog_dir / filename):
            raise ReleaseBundleError(f"Compatibility binding is stale for {filename}.")

    assets = catalog_dir / "assets"
    team_manifest = _read_object(assets / "team_reference.manifest.json", "team manifest")
    retrosheet_team_manifest = _read_object(
        assets / "retrosheet_team_reference.manifest.json", "Retrosheet team manifest"
    )
    _validate_declared_csv(
        root,
        f"{_CATALOG_ROOT}/assets/team_reference.csv",
        team_manifest,
        declared_path_required=False,
    )
    _validate_declared_csv(
        root,
        f"{_CATALOG_ROOT}/assets/retrosheet_team_reference.csv",
        retrosheet_team_manifest,
        declared_path_required=False,
    )
    if compatibility.get("team_reference_revision") != team_manifest.get("reference_version"):
        raise ReleaseBundleError("Compatibility binding has a stale team reference revision.")
    if compatibility.get("team_reference_manifest_sha256") != _sha256(
        assets / "team_reference.manifest.json"
    ):
        raise ReleaseBundleError("Compatibility binding has a stale team reference manifest.")

    coverage = _read_object(root / _COVERAGE_PATH, "Coverage Report")
    proof_identity = _require_object(coverage.get("proof_identity"), "Coverage Report identity")
    proof_payload = {key: value for key, value in coverage.items() if key != "proof_id"}
    expected_proof_id = hashlib.sha256(
        _canonical_json_bytes(proof_payload).removesuffix(b"\n")
    ).hexdigest()
    summary = _require_object(coverage.get("summary"), "Coverage Report summary")
    gates = _require_object_list(coverage.get("gates"), "Coverage Report gates")
    gate_ids = {
        _require_string(gate.get("identity"), "Coverage Report gate identity") for gate in gates
    }
    if gate_ids != REQUIRED_COVERAGE_GATE_IDS or len(gates) != len(REQUIRED_COVERAGE_GATE_IDS):
        raise ReleaseBundleError("Coverage Report gate set is incomplete or duplicated.")
    gate_total = 0
    for gate in gates:
        obligations = gate.get("obligations")
        total = gate.get("total")
        if (
            gate.get("status") != "passing"
            or gate.get("failures")
            or not isinstance(total, int)
            or gate.get("covered") != total
            or not isinstance(obligations, list)
            or len(obligations) != total
        ):
            raise ReleaseBundleError("Coverage Report contains a malformed or failing gate.")
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("identity"), str)
            or not item["identity"]
            or item.get("status") != "passing"
            for item in obligations
        ):
            raise ReleaseBundleError("Coverage Report contains a malformed obligation.")
        gate_total += total
    if (
        coverage.get("schema_version") != proof_identity.get("report_schema_version")
        or coverage.get("proof_id") != expected_proof_id
        or coverage.get("status") != "passing"
        or coverage.get("failures")
        or summary.get("uncovered") != 0
        or summary.get("covered") != summary.get("total")
        or summary.get("total") != gate_total
    ):
        raise ReleaseBundleError("Coverage Report is malformed, stale, or not passing.")
    if (
        proof_identity.get("catalog_revision") != catalog_revision
        or proof_identity.get("catalog_sha256") != _catalog_proof_digest(catalog_dir)
        or proof_identity.get("data_release") != data_release
        or proof_identity.get("data_manifest_semantic_sha256")
        != compatibility.get("data_manifest_semantic_sha256")
        or proof_identity.get("compiler_contract") != "query-plan-v1"
        or not _FULL_SHA256.fullmatch(str(proof_identity.get("compiler_sha256", "")))
    ):
        raise ReleaseBundleError("Coverage Report does not match the bundled release inputs.")
    expected_fingerprint_sources = {
        _require_string(item.get("identity"), "Published source identity")
        for item in _require_object_list(registry.get("sources"), "Published source declarations")
    }
    source_fingerprints = _require_object(
        proof_identity.get("source_fingerprints"), "Coverage Report source fingerprints"
    )
    if set(source_fingerprints) != expected_fingerprint_sources or any(
        not _FULL_SHA256.fullmatch(str(value)) for value in source_fingerprints.values()
    ):
        raise ReleaseBundleError("Coverage Report source fingerprints are incomplete or malformed.")

    legal_records = [_read_object(root / relative, relative) for relative in _LEGAL_BUNDLE_PATHS]
    for record in legal_records:
        if record.get("schema_version") != LEGAL_SCHEMA:
            raise ReleaseBundleError("Legal record schema is invalid.")
        for field in ("owner", "license", "source", "attribution", "notice", "disclaimer"):
            _require_string(record.get(field), f"legal record {field}")

    return {
        "bundle_root": root,
        "data_manifest": data_manifest,
        "data_release": data_release,
        "projection_manifest": projection_manifest,
        "projection_entry": projection_entry,
        "projection_identity": projection_identity,
        "catalog_revision": catalog_revision,
        "registry_revision": registry_revision,
        "inventory_revision": inventory_revision,
        "team_manifest": team_manifest,
        "retrosheet_team_manifest": retrosheet_team_manifest,
        "coverage": coverage,
        "legal_records": legal_records,
        "lahman_by_path": by_path,
    }


def _payload_entry(root: Path, relative: str, context: Mapping[str, Any]) -> dict[str, object]:
    path = root / relative
    entry: dict[str, object] = {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "notice": _notice_for(relative),
        "rows": None,
        "schema": None,
        "year_coverage": None,
    }
    if path.suffix.lower() == ".csv":
        columns, rows = _csv_shape(path, relative)
        entry["rows"] = rows
        entry["schema"] = {"columns": columns}
        coverage = _year_coverage_for(relative, context)
        entry["year_coverage"] = coverage
    elif path.suffix.lower() == ".json":
        value = _read_object(path, relative)
        entry["schema"] = _json_identity(value, relative)
    elif path.suffix.lower() == ".txt":
        entry["schema"] = "text/plain; charset=utf-8"
    return entry


def _projection_only_manifest(
    source_manifest: dict[str, object], *, source_manifest_bytes_sha256: str
) -> dict[str, object]:
    dataset = _require_object(source_manifest.get("dataset"), "Retrosheet dataset")
    files = _require_object_list(source_manifest.get("files"), "Retrosheet source files")
    matches = [item for item in files if item.get("path") == _PROJECTION_PATH]
    if len(matches) != 1:
        raise ReleaseBundleError("Retrosheet source manifest lacks the exact projection entry.")
    source_entry = matches[0]
    source_provenance = _require_object(
        source_entry.get("provenance"), "Retrosheet projection provenance"
    )
    event_archives_accessed_at = _require_string(
        source_provenance.get("event_archives_accessed_at"),
        "Retrosheet event archive access time",
    )
    projection_generated_at = _require_string(
        source_provenance.get("projection_generated_at"),
        "Retrosheet projection generation time",
    )
    generation_tool = _require_string(
        source_provenance.get("generation_tool"), "Retrosheet projection generator"
    )
    derivation = _require_string(
        source_provenance.get("derivation"), "Retrosheet projection derivation"
    )
    year_coverage = _require_object(
        source_entry.get("year_coverage"), "Retrosheet projection year coverage"
    )
    max_year = year_coverage.get("max")
    if not isinstance(max_year, int):
        raise ReleaseBundleError("Retrosheet projection maximum year is malformed.")
    allowed_entry_keys = ("path", "source_url", "table", "kind", "rows", "year_coverage", "sha256")
    entry = {key: source_entry[key] for key in allowed_entry_keys if key in source_entry}
    allowed_dataset_keys = ("name", "source_url", "attribution", "license_notes")
    projected_dataset = {key: dataset[key] for key in allowed_dataset_keys if key in dataset}
    return {
        "schema_version": PROJECTION_MANIFEST_SCHEMA,
        "projection_identity": "retrosheet-pitcher-strikeout-side-v1",
        "dataset": projected_dataset,
        "upstream_release": (
            f"Retrosheet event archives through {max_year}; accessed {event_archives_accessed_at}"
        ),
        "provenance": {
            "event_archives_accessed_at": event_archives_accessed_at,
            "projection_generated_at": projection_generated_at,
            "generation_tool": generation_tool,
            "source_manifest_bytes_sha256": source_manifest_bytes_sha256,
            "derivation": derivation,
        },
        "coverage": {"year_coverage": entry.get("year_coverage")},
        "files": [entry],
    }


def _validate_declared_csv(
    root: Path,
    relative: str,
    declaration: Mapping[str, object],
    *,
    declared_path_required: bool = True,
) -> None:
    path = root / relative
    if declared_path_required and declaration.get("path") != relative:
        raise ReleaseBundleError(f"Manifest path does not match {relative}.")
    columns, rows = _csv_shape(path, relative)
    if declaration.get("rows") != rows or declaration.get("sha256") != _sha256(path):
        raise ReleaseBundleError(f"Manifest size or digest is stale for {relative}.")
    declared_columns = declaration.get("columns")
    if declared_columns is not None and declared_columns != columns:
        raise ReleaseBundleError(f"Manifest schema is stale for {relative}.")


def _csv_shape(path: Path, label: str) -> tuple[list[str], int]:
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, strict=True)
            header = next(reader)
            if not header or any(not name for name in header) or len(set(header)) != len(header):
                raise ReleaseBundleError(f"CSV schema is malformed for {label}.")
            rows = 0
            for row in reader:
                if len(row) != len(header):
                    raise ReleaseBundleError(f"CSV row shape is malformed for {label}.")
                rows += 1
    except (OSError, UnicodeError, csv.Error, StopIteration) as exc:
        raise ReleaseBundleError(f"CSV payload is malformed for {label}.") from exc
    return header, rows


def _semantic_manifest_sha256(manifest: Mapping[str, object]) -> str:
    dataset = _require_object(manifest.get("dataset"), "data manifest dataset")
    files = _require_object_list(manifest.get("files"), "data manifest files")
    semantic_files = [
        {
            "path": item.get("path"),
            "table": item.get("table"),
            "rows": item.get("rows"),
            "year_coverage": item.get("year_coverage"),
            "sha256": item.get("sha256"),
        }
        for item in files
    ]
    payload = {
        "release_id": dataset.get("release_id"),
        "files": sorted(semantic_files, key=lambda item: str(item["table"])),
    }
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _catalog_proof_digest(catalog_dir: Path) -> str:
    paths = tuple(sorted(catalog_dir.glob("*.json"))) + tuple(
        sorted((catalog_dir / "assets").glob("*"))
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _year_coverage_for(relative: str, context: Mapping[str, Any]) -> object | None:
    if relative in _LAHMAN_CSVS:
        return context["lahman_by_path"][relative].get("year_coverage")
    if relative == _PROJECTION_PATH:
        return context["projection_entry"].get("year_coverage")
    if relative.endswith("team_reference.csv"):
        return _csv_year_coverage(root=context["bundle_root"], relative=relative)
    return None


def _csv_year_coverage(*, root: Path, relative: str) -> dict[str, int]:
    try:
        with (root / relative).open(newline="", encoding="utf-8") as source:
            years = [int(row["yearID"]) for row in csv.DictReader(source)]
    except (OSError, UnicodeError, KeyError, TypeError, ValueError) as exc:
        raise ReleaseBundleError(f"CSV year coverage is malformed for {relative}.") from exc
    if not years:
        raise ReleaseBundleError(f"CSV year coverage is empty for {relative}.")
    return {"min": min(years), "max": max(years)}


def _notice_for(relative: str) -> str:
    if relative in _LEGAL_BUNDLE_PATHS:
        return relative
    if relative.startswith("data/secondary_sources/retrosheet/") or "retrosheet_" in relative:
        return "legal/retrosheet.json"
    if (
        relative.startswith("data/")
        or relative.endswith("team_reference.csv")
        or relative.endswith("team_reference.manifest.json")
    ):
        return "legal/lahman-neuml.json"
    return "legal/ground-ball.json"


def _json_identity(value: Mapping[str, object], label: str) -> str | int:
    for key in (
        "schema_version",
        "catalog_revision",
        "registry_revision",
        "inventory_revision",
        "reference_version",
    ):
        identity = value.get(key)
        if isinstance(identity, (str, int)) and not isinstance(identity, bool):
            return identity
    if label == "data/manifest.json":
        return "lahman-source-manifest-v1"
    if label.endswith("compatibility.json"):
        return "published-catalog-compatibility-v1"
    if label.startswith("legal/"):
        return LEGAL_SCHEMA
    raise ReleaseBundleError(f"JSON payload has no schema or revision identity: {label}.")


def _bundle_file_paths(root: Path) -> set[str]:
    observed: set[str] = set()
    for directory, directory_names, filenames in os.walk(root, followlinks=False):
        directory_path = Path(directory)
        for name in directory_names:
            candidate = directory_path / name
            if candidate.is_symlink():
                raise ReleaseBundleError(f"Release Bundle contains a symlink: {candidate}")
        for name in filenames:
            candidate = directory_path / name
            relative = candidate.relative_to(root).as_posix()
            _require_regular_file(root, candidate, relative)
            observed.add(relative)
    return observed


def _require_regular_file(root: Path, path: Path, label: str) -> None:
    try:
        relative_parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ReleaseBundleError(f"Payload path escapes its root: {label}.") from exc
    current = root
    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseBundleError(f"Payload member is a symlink: {label}.")
    if not path.is_file():
        raise ReleaseBundleError(f"Required payload member is missing: {label}.")


def _read_object(path: Path, label: str) -> dict[str, object]:
    return _decode_object(_read_bytes(path, label), label)


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise ReleaseBundleError(f"Payload member is unreadable: {label}.") from exc


def _decode_object(content: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(content.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReleaseBundleError(f"JSON payload is malformed: {label}.") from exc
    if not isinstance(value, dict):
        raise ReleaseBundleError(f"JSON payload must be an object: {label}.")
    return value


def _require_object(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ReleaseBundleError(f"{label} must be an object.")
    return value


def _require_object_list(value: object, label: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ReleaseBundleError(f"{label} must be a list of objects.")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ReleaseBundleError(f"{label} must be a non-empty string.")
    return value


def _validate_source_commit(source_commit: str) -> None:
    if not isinstance(source_commit, str) or not _FULL_COMMIT.fullmatch(source_commit):
        raise ReleaseBundleError("Source commit must be a full lowercase Git commit hash.")


def _canonical_json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def _write_canonical_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_json_bytes(value))


def _sha256(path: Path) -> str:
    return hashlib.sha256(_read_bytes(path, path.as_posix())).hexdigest()


def _validate_relative_path(path: str) -> None:
    pure = PurePosixPath(path)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != path:
        raise ReleaseBundleError(f"Payload path is not canonical: {path}.")


for _path in _PAYLOAD_PATHS:
    _validate_relative_path(_path)


def main(argv: list[str] | None = None) -> int:
    """Assemble or check one Release Bundle from the command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    assemble = commands.add_parser("assemble")
    assemble.add_argument("source_root", type=Path)
    assemble.add_argument("bundle_root", type=Path)
    assemble.add_argument("--source-commit", required=True)
    check = commands.add_parser("check")
    check.add_argument("bundle_root", type=Path)
    check.add_argument("--expected-source-commit")
    args = parser.parse_args(argv)
    if args.command == "assemble":
        identity = assemble_release_bundle(
            args.source_root,
            args.bundle_root,
            source_commit=args.source_commit,
        )
    else:
        identity = check_release_bundle(
            args.bundle_root,
            expected_source_commit=args.expected_source_commit,
        )
    print(identity.digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
