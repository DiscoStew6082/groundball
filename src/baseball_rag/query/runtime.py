"""Internal runtime Adapter for the immutable published Lahman source view."""

from __future__ import annotations

import hashlib
import json
import os
from _thread import RLock
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import duckdb
from duckdb import DuckDBPyConnection

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.db.packaged_data import verify_manifest_file
from baseball_rag.query.asset_paths import contained_asset_path
from baseball_rag.query.data_identity import semantic_manifest_sha256
from baseball_rag.query.fingerprint import RowFingerprint
from baseball_rag.query.registry import (
    _source_bindings,
    _SourceBinding,
    catalog_directory,
    discover_fields,
)
from baseball_rag.release_context import (
    ReleaseContext,
    configured_release_context,
    install_release_context,
    installed_release_context,
    release_context_lock,
)


class PublishedDataUnavailableError(ValueError):
    """Installed sources do not match the published catalog/data pairing."""


@dataclass(frozen=True)
class PublishedDataRuntime:
    connection: DuckDBPyConnection
    connection_lock: RLock
    data_dir: Path
    manifest: dict[str, Any]
    data_release: str
    source_fingerprints: Mapping[str, str]
    release_context: ReleaseContext | None = None


_installed_runtime_lock = RLock()
_installed_runtime: PublishedDataRuntime | None = None


def install_published_data_runtime(
    runtime: PublishedDataRuntime, *, context: ReleaseContext | None = None
) -> None:
    """Install one validated runtime for this process without replacing it."""
    with release_context_lock:
        _install_runtime_locked(runtime, context=context)


def _install_runtime_locked(
    runtime: PublishedDataRuntime, *, context: ReleaseContext | None = None
) -> None:
    """Install one validated runtime for this process without replacing it."""
    if not isinstance(runtime, PublishedDataRuntime):
        raise TypeError("runtime must be a PublishedDataRuntime.")
    selected = context or runtime.release_context or configured_release_context()
    if selected is not None:
        _validate_runtime_context(runtime, selected)
        install_release_context(selected)
    global _installed_runtime
    with _installed_runtime_lock:
        if _installed_runtime is None:
            _installed_runtime = runtime
        elif _installed_runtime is not runtime:
            raise PublishedDataUnavailableError(
                "A different PublishedDataRuntime is already installed."
            )


def _validate_runtime_context(runtime: PublishedDataRuntime, context: ReleaseContext) -> None:
    if (
        runtime.release_context is not context
        or runtime.data_dir != context.data_dir
        or runtime.data_release != context.data_release
        or semantic_manifest_sha256(runtime.manifest) != context.data_manifest_semantic_sha256
        or dict(runtime.source_fingerprints) != dict(context.source_fingerprints)
    ):
        raise PublishedDataUnavailableError("Runtime does not match the verified ReleaseContext.")


def published_data_runtime(context: ReleaseContext | None = None) -> PublishedDataRuntime:
    """Use an explicitly selected release or the narrow legacy local configuration."""
    with release_context_lock:
        return _published_runtime_locked(context)


def _published_runtime_locked(context: ReleaseContext | None) -> PublishedDataRuntime:
    """Use an explicitly selected release or the narrow legacy local configuration."""
    if context is not None:
        install_release_context(context)
    else:
        context = configured_release_context()
    with _installed_runtime_lock:
        installed = _installed_runtime
    if installed is not None:
        if context is not None:
            _validate_runtime_context(installed, context)
        return installed
    configured = (
        context.data_dir
        if context is not None
        else Path(os.environ.get("GROUNDBALL_DATA_DIR", DATA_DIR)).resolve()
    )
    loaded = _runtime_for(str(configured), context)
    with _installed_runtime_lock:
        selected = _installed_runtime if _installed_runtime is not None else loaded
    if context is not None:
        _validate_runtime_context(selected, context)
    return selected


def create_published_data_runtime(context: ReleaseContext) -> PublishedDataRuntime:
    """Build a verified release runtime for an explicit composition root or offline builder.

    The caller owns the connection until installation. Catalog and data always
    come from the same context; this factory never reads a data-path environment variable.
    """
    return _load_runtime(str(context.data_dir), context)


def _runtime_for(
    data_dir_value: str, context: ReleaseContext | None = None
) -> PublishedDataRuntime:
    """Resolve the immutable context before consulting the internal runtime cache."""
    with release_context_lock:
        if context is not None:
            install_release_context(context)
        else:
            context = configured_release_context()
        if context is not None and Path(data_dir_value) != context.data_dir:
            raise PublishedDataUnavailableError(
                "Runtime data is outside the verified ReleaseContext."
            )
        return _cached_runtime(data_dir_value, context)


@lru_cache(maxsize=None)
def _cached_runtime(data_dir_value: str, context: ReleaseContext | None) -> PublishedDataRuntime:
    return _load_runtime(data_dir_value, context)


def _load_runtime(
    data_dir_value: str, context: ReleaseContext | None = None
) -> PublishedDataRuntime:
    with release_context_lock:
        return _load_runtime_locked(data_dir_value, context)


def _load_runtime_locked(
    data_dir_value: str, context: ReleaseContext | None = None
) -> PublishedDataRuntime:
    if context is not None:
        install_release_context(context)
    else:
        context = configured_release_context()
    data_dir = Path(data_dir_value)
    if context is not None and data_dir != context.data_dir:
        raise PublishedDataUnavailableError("Runtime data is outside the verified ReleaseContext.")
    manifest_path = _safe_asset(data_dir, "manifest.json")
    compatibility = _read_json(catalog_directory() / "compatibility.json")
    catalog = _read_json(catalog_directory() / "published_catalog.json")
    inventory_path = catalog_directory() / "raw_fields.json"
    inventory = _read_json(inventory_path)
    registry_path = catalog_directory() / "published_sources.json"
    registry = _read_json(registry_path)
    team_manifest_path = catalog_directory() / "assets/team_reference.manifest.json"
    team_manifest = _read_json(team_manifest_path)
    try:
        manifest_content = manifest_path.read_bytes()
        manifest = json.loads(manifest_content)
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishedDataUnavailableError(
            "Installed data manifest is missing or unreadable."
        ) from exc
    manifest_digest = semantic_manifest_sha256(manifest)
    if manifest_digest != compatibility["data_manifest_semantic_sha256"]:
        raise PublishedDataUnavailableError("Installed data manifest is not catalog-compatible.")
    if catalog["catalog_revision"] != compatibility["catalog_revision"]:
        raise PublishedDataUnavailableError("Published catalog revision is not compatible.")
    if (
        hashlib.sha256((catalog_directory() / "published_catalog.json").read_bytes()).hexdigest()
        != compatibility["catalog_sha256"]
    ):
        raise PublishedDataUnavailableError("Published catalog content is not compatible.")
    promoted_hashes = compatibility.get("promoted_catalog_sha256")
    if not isinstance(promoted_hashes, dict):
        raise PublishedDataUnavailableError("Promoted catalog compatibility is missing.")
    expected_promoted = {str(item) for item in catalog.get("promoted", [])}
    if set(promoted_hashes) != expected_promoted:
        raise PublishedDataUnavailableError("Promoted catalog file set is not compatible.")
    for filename, expected_digest in promoted_hashes.items():
        promoted_path = _safe_asset(catalog_directory(), filename)
        try:
            observed_digest = hashlib.sha256(promoted_path.read_bytes()).hexdigest()
        except OSError as exc:
            raise PublishedDataUnavailableError(
                f"Required promoted catalog asset {filename!r} is missing."
            ) from exc
        if observed_digest != expected_digest:
            raise PublishedDataUnavailableError(
                f"Promoted catalog asset {filename!r} is not compatible."
            )
    if inventory["inventory_revision"] != compatibility["raw_inventory_revision"]:
        raise PublishedDataUnavailableError("Raw-field inventory revision is not compatible.")
    if (
        hashlib.sha256(inventory_path.read_bytes()).hexdigest()
        != compatibility["raw_inventory_sha256"]
    ):
        raise PublishedDataUnavailableError("Raw-field inventory content is not compatible.")
    if catalog["raw_inventory_revision"] != inventory["inventory_revision"]:
        raise PublishedDataUnavailableError("Published catalog references a stale raw inventory.")
    if registry["registry_revision"] != compatibility["source_registry_revision"]:
        raise PublishedDataUnavailableError("Published source registry revision is not compatible.")
    if (
        hashlib.sha256(registry_path.read_bytes()).hexdigest()
        != compatibility["source_registry_sha256"]
    ):
        raise PublishedDataUnavailableError("Published source registry content is not compatible.")
    if team_manifest["reference_version"] != compatibility["team_reference_revision"]:
        raise PublishedDataUnavailableError("Team-reference revision is not catalog-compatible.")
    if (
        hashlib.sha256(team_manifest_path.read_bytes()).hexdigest()
        != compatibility["team_reference_manifest_sha256"]
    ):
        raise PublishedDataUnavailableError("Team-reference manifest is not compatible.")

    # Validate every catalog-selected path before opening any selected asset or
    # loading relations. No checksum failure may be used as a traversal guard.
    sources = _source_bindings()
    asset_paths = tuple(_asset_path(source.kind, source.asset, data_dir) for source in sources)
    for source in sources:
        if source.reference_manifest is not None:
            _safe_asset(catalog_directory(), source.reference_manifest)
    public_execution = context is not None or os.environ.get("GROUNDBALL_PUBLIC_WORKER") == "1"
    config: dict[str, Any] = (
        {"memory_limit": "256MB", "threads": 4, "temp_directory": ""} if public_execution else {}
    )
    connection = duckdb.connect(database=":memory:", config=config)
    source_fingerprints: dict[str, str] = {}
    try:
        for source, asset_path in zip(sources, asset_paths, strict=True):
            if asset_path is None or not asset_path.exists():
                raise PublishedDataUnavailableError(
                    f"Published source {source.identity!r} is missing."
                )
            if source.kind == "synthesized_team_reference":
                _verify_reference(source.reference_manifest, source.reference_version, asset_path)
            else:
                _verify_packaged_asset(source, asset_path, manifest)
            connection.execute(
                f"CREATE TABLE {_quote(source.relation)} AS SELECT * FROM read_csv_auto(?)",
                [str(asset_path)],
            )
            _verify_schema(connection, source.identity, source.relation)
            _verify_rows(connection, source, manifest)
            _verify_key(connection, source.relation, source.primary_key)
            source_fingerprints[source.identity] = _source_fingerprint(
                connection, source.identity, source.relation
            )
        if context is not None:
            _load_release_retrosheet(connection, data_dir)
    except Exception:
        connection.close()
        raise

    if installed_release_context() is not context:
        connection.close()
        raise PublishedDataUnavailableError("Release context changed during runtime construction.")
    data_release = str(manifest.get("dataset", {}).get("release_id") or "unavailable")
    return PublishedDataRuntime(
        connection=connection,
        connection_lock=RLock(),
        data_dir=data_dir,
        manifest=manifest,
        data_release=data_release,
        source_fingerprints=MappingProxyType(source_fingerprints),
        release_context=context,
    )


def _asset_path(kind: str, asset: str | None, data_dir: Path) -> Path | None:
    if asset is None:
        return None
    root = catalog_directory() if kind == "synthesized_team_reference" else data_dir
    return _safe_asset(root, asset)


def _safe_asset(root: Path, name: object) -> Path:
    try:
        return contained_asset_path(root, name)
    except ValueError as exc:
        raise PublishedDataUnavailableError(str(exc)) from exc


def _verify_reference(
    manifest_name: str | None,
    expected_version: str | None,
    asset_path: Path,
) -> None:
    if manifest_name is None:
        raise PublishedDataUnavailableError("Team reference has no manifest binding.")
    manifest = _read_json(_safe_asset(catalog_directory(), manifest_name))
    if manifest["reference_version"] != expected_version:
        raise PublishedDataUnavailableError("Team-reference revision is not compatible.")
    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    if digest != manifest["sha256"]:
        raise PublishedDataUnavailableError("Team-reference checksum does not match its manifest.")


def _verify_packaged_asset(
    source: _SourceBinding,
    asset_path: Path,
    manifest: dict[str, Any],
) -> None:
    matches = [
        item for item in manifest.get("files", []) if item.get("table") == source.manifest_table
    ]
    if len(matches) != 1:
        raise PublishedDataUnavailableError(f"Source {source.identity!r} has no manifest binding.")
    digest = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    if digest != matches[0]["sha256"]:
        raise PublishedDataUnavailableError(f"Source {source.identity!r} failed its checksum.")


def _verify_schema(connection: DuckDBPyConnection, identity: str, relation: str) -> None:
    observed = tuple(
        (str(row[0]), str(row[1]))
        for row in connection.execute(f"DESCRIBE {_quote(relation)}").fetchall()
    )
    expected = tuple(
        (field.column, field.duckdb_type)
        for field in sorted(discover_fields(source=identity), key=lambda item: item.ordinal)
    )
    if observed != expected:
        raise PublishedDataUnavailableError(f"Published source {identity!r} has schema drift.")


def _verify_rows(
    connection: DuckDBPyConnection,
    source: _SourceBinding,
    manifest: dict[str, Any],
) -> None:
    if source.reference_manifest is not None:
        expected = int(
            _read_json(_safe_asset(catalog_directory(), source.reference_manifest))["rows"]
        )
    else:
        matches = [
            item for item in manifest.get("files", []) if item.get("table") == source.manifest_table
        ]
        if len(matches) != 1:
            raise PublishedDataUnavailableError(f"Source {source.identity!r} has no manifest row.")
        expected = int(matches[0]["rows"])
    row = connection.execute(f"SELECT count(*) FROM {_quote(source.relation)}").fetchone()
    if row is None:
        raise PublishedDataUnavailableError(f"Source {source.identity!r} could not be counted.")
    observed = int(row[0])
    if observed != expected:
        raise PublishedDataUnavailableError(
            f"Published source {source.identity!r} has row-count drift."
        )


def _verify_key(
    connection: DuckDBPyConnection,
    relation: str,
    primary_key: tuple[str, ...],
) -> None:
    columns = ", ".join(_quote(column) for column in primary_key)
    nulls = " OR ".join(f"{_quote(column)} IS NULL" for column in primary_key)
    duplicate = connection.execute(
        f"SELECT 1 FROM {_quote(relation)} GROUP BY {columns} HAVING count(*) > 1 LIMIT 1"
    ).fetchone()
    missing = connection.execute(
        f"SELECT 1 FROM {_quote(relation)} WHERE {nulls} LIMIT 1"
    ).fetchone()
    if duplicate is not None or missing is not None:
        raise PublishedDataUnavailableError(
            f"Published source {relation!r} has an invalid row key."
        )


def _source_fingerprint(
    connection: DuckDBPyConnection,
    identity: str,
    relation: str,
) -> str:
    columns = tuple(
        field.column
        for field in sorted(discover_fields(source=identity), key=lambda item: item.ordinal)
    )
    projection = ", ".join(_quote(column) for column in columns)
    cursor = connection.execute(f"SELECT {projection} FROM {_quote(relation)}")
    fingerprint = RowFingerprint()
    while batch := cursor.fetchmany(10_000):
        for row in batch:
            fingerprint.add(row)
    return fingerprint.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        safe_path = _safe_asset(
            catalog_directory(), path.relative_to(catalog_directory()).as_posix()
        )
        return json.loads(safe_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishedDataUnavailableError(
            f"Required catalog asset {path.name!r} is missing or unreadable."
        ) from exc


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _load_release_retrosheet(connection: DuckDBPyConnection, data_dir: Path) -> None:
    """Load only the compact Retrosheet projection admitted to the Release Bundle."""
    projection = _safe_asset(
        data_dir, "secondary_sources/retrosheet/pitcher_strikeout_side_events.csv"
    )
    projection_manifest = _safe_asset(data_dir, "secondary_sources/retrosheet/manifest.json")
    verify_manifest_file(projection_manifest, projection)

    reference = _safe_asset(catalog_directory(), "assets/retrosheet_team_reference.csv")
    reference_manifest = _safe_asset(
        catalog_directory(), "assets/retrosheet_team_reference.manifest.json"
    )
    reference_metadata = _read_json(reference_manifest)
    if hashlib.sha256(reference.read_bytes()).hexdigest() != reference_metadata.get("sha256"):
        raise PublishedDataUnavailableError(
            "Retrosheet team-reference checksum does not match its manifest."
        )
    connection.execute(
        "CREATE TABLE retrosheet_team_reference AS SELECT * FROM read_csv_auto(?)",
        [str(reference)],
    )
    connection.execute(
        "CREATE TABLE retrosheet_pitcher_strikeout_side_events AS SELECT * FROM read_csv_auto(?)",
        [str(projection)],
    )
