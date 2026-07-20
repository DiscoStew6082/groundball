"""Strict immutable DuckDB cache for protected-provider query workers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import duckdb
from duckdb import DuckDBPyConnection

from baseball_rag.public_release_config import canonical_json_bytes
from baseball_rag.query.data_identity import semantic_manifest_sha256

CACHE_SCHEMA_VERSION = "ground-ball-provider-runtime-cache-v1"
CACHE_REFERENCE_ENV = "GROUNDBALL_PROVIDER_RUNTIME_CACHE"
_CACHE_ROOT = Path("/tmp/groundball-provider-runtime-cache-v1")
_DATABASE_NAME = "runtime.duckdb"
_METADATA_NAME = "metadata.json"
_SHA256_LENGTH = 64
_MAX_METADATA_BYTES = 1_048_576


class ProviderRuntimeCacheError(RuntimeError):
    """The protected-provider runtime cache is absent, foreign, or mutable."""


class RuntimeForCache(Protocol):
    @property
    def connection(self) -> DuckDBPyConnection: ...

    @property
    def manifest(self) -> dict[str, Any]: ...

    @property
    def data_release(self) -> str: ...

    @property
    def source_fingerprints(self) -> Mapping[str, str]: ...


@dataclass(frozen=True)
class ValidatedProviderRuntimeCache:
    connection: DuckDBPyConnection
    data_dir: Path
    manifest: dict[str, Any]
    data_release: str
    source_fingerprints: Mapping[str, str]
    relations: tuple[str, ...]


def clear_provider_runtime_cache_reference() -> None:
    """Remove only the parent-published process reference, never cache files."""
    os.environ.pop(CACHE_REFERENCE_ENV, None)


def prepare_provider_runtime_cache(
    runtime: RuntimeForCache,
    *,
    source_commit: str,
    release_bundle_digest: str,
    runtime_configuration_digest: str,
) -> str:
    """Atomically materialize, validate, then publish one exact cache reference."""
    clear_provider_runtime_cache_reference()
    _require_commit(source_commit)
    _require_digest(release_bundle_digest)
    _require_digest(runtime_configuration_digest)
    cache_root = _prepare_cache_root()
    temporary = Path(tempfile.mkdtemp(prefix=".building-", dir=cache_root))
    try:
        database_path = temporary / _DATABASE_NAME
        _copy_database(runtime.connection, database_path)
        _sync_file(database_path)
        database_size = database_path.stat().st_size
        database_sha256 = _file_sha256(database_path)
        relations = _relations(runtime.connection)
        runtime_manifest = _semantic_runtime_manifest(runtime.manifest)
        metadata = {
            "data_manifest": runtime_manifest,
            "data_manifest_semantic_sha256": semantic_manifest_sha256(runtime_manifest),
            "data_release": runtime.data_release,
            "database_sha256": database_sha256,
            "database_size_bytes": database_size,
            "release_bundle_digest": release_bundle_digest,
            "required_relations": list(relations),
            "runtime_configuration_digest": runtime_configuration_digest,
            "schema_version": CACHE_SCHEMA_VERSION,
            "source_commit": source_commit,
            "source_fingerprints": dict(sorted(runtime.source_fingerprints.items())),
        }
        metadata_bytes = canonical_json_bytes(metadata)
        _validate_metadata(metadata, metadata_bytes)
        reference = hashlib.sha256(metadata_bytes).hexdigest()
        metadata_path = temporary / _METADATA_NAME
        _write_new_file(metadata_path, metadata_bytes)
        os.chmod(database_path, 0o400)
        os.chmod(metadata_path, 0o400)
        os.chmod(temporary, 0o500)
        final = cache_root / reference
        try:
            os.rename(temporary, final)
        except FileExistsError:
            os.chmod(temporary, 0o700)
            shutil.rmtree(temporary)
        validated = _validate_reference(
            reference,
            expected_source_commit=source_commit,
            expected_release_bundle_digest=release_bundle_digest,
            expected_runtime_configuration_digest=runtime_configuration_digest,
        )
        validated.connection.close()
        os.environ[CACHE_REFERENCE_ENV] = reference
        return reference
    except Exception:
        clear_provider_runtime_cache_reference()
        if temporary.exists():
            try:
                os.chmod(temporary, 0o700)
            except OSError:
                pass
            shutil.rmtree(temporary, ignore_errors=True)
        raise


def require_provider_runtime_cache_for_worker() -> None:
    """Fail closed before protected-provider worker execution can use the full loader."""
    runtime_config_path = os.environ.get("GROUNDBALL_RUNTIME_CONFIG")
    if runtime_config_path is None:
        return
    from baseball_rag.public_release_config import load_runtime_configuration

    configuration = load_runtime_configuration(runtime_config_path)
    if not configuration.provider_deployment:
        return
    reference = os.environ.get(CACHE_REFERENCE_ENV)
    if reference is None:
        raise ProviderRuntimeCacheError("Provider runtime cache is unavailable.")
    _require_digest(reference)


def load_provider_runtime_cache(
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
) -> ValidatedProviderRuntimeCache:
    """Validate the parent reference and open its exact database read-only."""
    reference = os.environ.get(CACHE_REFERENCE_ENV)
    if reference is None:
        raise ProviderRuntimeCacheError("Provider runtime cache is unavailable.")
    return _validate_reference(
        reference,
        expected_source_commit=expected_source_commit,
        expected_release_bundle_digest=expected_release_bundle_digest,
        expected_runtime_configuration_digest=expected_runtime_configuration_digest,
    )


def _validate_reference(
    reference: str,
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
) -> ValidatedProviderRuntimeCache:
    _require_digest(reference)
    _require_commit(expected_source_commit)
    _require_digest(expected_release_bundle_digest)
    _require_digest(expected_runtime_configuration_digest)
    root = _CACHE_ROOT
    _require_directory(root, 0o700)
    cache_dir = root / reference
    _require_directory(cache_dir, 0o500)
    database_path = cache_dir / _DATABASE_NAME
    metadata_path = cache_dir / _METADATA_NAME
    _require_file(database_path, 0o400)
    _require_file(metadata_path, 0o400)
    try:
        metadata_bytes = metadata_path.read_bytes()
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache is invalid.") from exc
    if len(metadata_bytes) > _MAX_METADATA_BYTES:
        raise ProviderRuntimeCacheError("Provider runtime cache is invalid.")
    if hashlib.sha256(metadata_bytes).hexdigest() != reference:
        raise ProviderRuntimeCacheError("Provider runtime cache is invalid.")
    metadata = _decode_metadata(metadata_bytes)
    _validate_metadata(metadata, metadata_bytes)
    if (
        metadata["source_commit"] != expected_source_commit
        or metadata["release_bundle_digest"] != expected_release_bundle_digest
        or metadata["runtime_configuration_digest"] != expected_runtime_configuration_digest
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache identity does not match.")
    observed_size = database_path.stat().st_size
    if observed_size != metadata["database_size_bytes"]:
        raise ProviderRuntimeCacheError("Provider runtime cache is invalid.")
    if _file_sha256(database_path) != metadata["database_sha256"]:
        raise ProviderRuntimeCacheError("Provider runtime cache is invalid.")
    before = database_path.stat()
    try:
        connection = duckdb.connect(database=str(database_path), read_only=True)
    except Exception as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache is invalid.") from exc
    try:
        observed_relations = _relations(connection)
        if observed_relations != tuple(metadata["required_relations"]):
            raise ProviderRuntimeCacheError("Provider runtime cache relation inventory is invalid.")
        after = database_path.stat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        ):
            raise ProviderRuntimeCacheError("Provider runtime cache changed while opening.")
    except Exception:
        connection.close()
        raise
    return ValidatedProviderRuntimeCache(
        connection=connection,
        data_dir=Path(os.environ["GROUNDBALL_RELEASE_BUNDLE"]) / "data",
        manifest=metadata["data_manifest"],
        data_release=metadata["data_release"],
        source_fingerprints=metadata["source_fingerprints"],
        relations=tuple(metadata["required_relations"]),
    )


def _prepare_cache_root() -> Path:
    root = _CACHE_ROOT
    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=True)
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache location is unavailable.") from exc
    _require_directory(root, 0o700)
    return root


def _copy_database(connection: DuckDBPyConnection, destination: Path) -> None:
    quoted = str(destination).replace("'", "''")
    try:
        connection.execute(f"ATTACH '{quoted}' AS provider_runtime_cache")
        connection.execute("COPY FROM DATABASE memory TO provider_runtime_cache")
        connection.execute("DETACH provider_runtime_cache")
    except Exception:
        try:
            connection.execute("DETACH provider_runtime_cache")
        except Exception:
            pass
        raise


def _decode_metadata(content: bytes) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProviderRuntimeCacheError("Provider runtime cache metadata is invalid.")
            result[key] = value
        return result

    try:
        decoded = json.loads(content, object_pairs_hook=reject_duplicate)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache metadata is invalid.") from exc
    if not isinstance(decoded, dict):
        raise ProviderRuntimeCacheError("Provider runtime cache metadata is invalid.")
    return decoded


def _validate_metadata(metadata: dict[str, Any], content: bytes) -> None:
    required = {
        "data_manifest",
        "data_manifest_semantic_sha256",
        "data_release",
        "database_sha256",
        "database_size_bytes",
        "release_bundle_digest",
        "required_relations",
        "runtime_configuration_digest",
        "schema_version",
        "source_commit",
        "source_fingerprints",
    }
    if set(metadata) != required or metadata.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise ProviderRuntimeCacheError("Provider runtime cache metadata shape is invalid.")
    for key in (
        "data_manifest_semantic_sha256",
        "database_sha256",
        "release_bundle_digest",
        "runtime_configuration_digest",
    ):
        _require_digest(metadata.get(key))
    _require_commit(metadata.get("source_commit"))
    size = metadata.get("database_size_bytes")
    relations = metadata.get("required_relations")
    fingerprints = metadata.get("source_fingerprints")
    manifest = metadata.get("data_manifest")
    data_release = metadata.get("data_release")
    if (
        type(size) is not int
        or size <= 0
        or not isinstance(relations, list)
        or not isinstance(fingerprints, dict)
        or not all(_is_digest(value) for value in fingerprints.values())
        or not isinstance(manifest, dict)
        or not isinstance(data_release, str)
        or not data_release
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache metadata values are invalid.")
    if relations != list(_expected_relations()):
        raise ProviderRuntimeCacheError("Provider runtime cache relation inventory is invalid.")
    if set(fingerprints) != _expected_fingerprint_sources():
        raise ProviderRuntimeCacheError("Provider runtime cache fingerprints are invalid.")
    try:
        semantic_digest = semantic_manifest_sha256(manifest)
    except (TypeError, ValueError) as exc:
        raise ProviderRuntimeCacheError(
            "Provider runtime cache metadata values are invalid."
        ) from exc
    if semantic_digest != metadata["data_manifest_semantic_sha256"]:
        raise ProviderRuntimeCacheError("Provider runtime cache metadata values are invalid.")
    if str(manifest.get("dataset", {}).get("release_id") or "unavailable") != data_release:
        raise ProviderRuntimeCacheError("Provider runtime cache metadata values are invalid.")
    if content != canonical_json_bytes(metadata):
        raise ProviderRuntimeCacheError("Provider runtime cache metadata is noncanonical.")


def _semantic_runtime_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    dataset = manifest.get("dataset")
    files = manifest.get("files")
    if not isinstance(dataset, dict) or not isinstance(files, list):
        raise ProviderRuntimeCacheError("Provider runtime data manifest is invalid.")
    semantic_files: list[dict[str, Any]] = []
    for item in files:
        if not isinstance(item, dict):
            raise ProviderRuntimeCacheError("Provider runtime data manifest is invalid.")
        semantic_files.append(
            {
                "path": item.get("path"),
                "rows": item.get("rows"),
                "sha256": item.get("sha256"),
                "table": item.get("table"),
                "year_coverage": item.get("year_coverage"),
            }
        )
    return {
        "dataset": {"release_id": dataset.get("release_id")},
        "files": sorted(semantic_files, key=lambda item: str(item["table"])),
    }


def _expected_relations() -> tuple[str, ...]:
    from baseball_rag.query.registry import _source_bindings
    from baseball_rag.retrosheet_event_capabilities import published_retrosheet_event_capabilities

    return tuple(
        sorted(
            {
                *(source.relation for source in _source_bindings()),
                "retrosheet_team_reference",
                *(
                    capability.local_table
                    for capability in published_retrosheet_event_capabilities()
                ),
            }
        )
    )


def _expected_fingerprint_sources() -> set[str]:
    from baseball_rag.query.registry import _source_bindings

    return {source.identity for source in _source_bindings()}


def _relations(connection: DuckDBPyConnection) -> tuple[str, ...]:
    return tuple(
        str(row[0])
        for row in connection.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
    )


def _require_directory(path: Path, mode: int) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache location is invalid.") from exc
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != _effective_uid()
        or stat.S_IMODE(details.st_mode) != mode
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache location is invalid.")


def _require_file(path: Path, mode: int) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache file is invalid.") from exc
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != _effective_uid()
        or stat.S_IMODE(details.st_mode) != mode
        or details.st_nlink != 1
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache file is invalid.")


def _write_new_file(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise


def _sync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache file is unreadable.") from exc
    return digest.hexdigest()


def _effective_uid() -> int:
    return os.geteuid()


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def _require_digest(value: object) -> None:
    if not _is_digest(value):
        raise ProviderRuntimeCacheError("Provider runtime cache digest is invalid.")


def _require_commit(value: object) -> None:
    if not (
        isinstance(value, str)
        and len(value) == 40
        and all(character in "0123456789abcdef" for character in value)
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache source identity is invalid.")
