"""Build-time immutable DuckDB cache for protected-provider query workers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

import duckdb
from duckdb import DuckDBPyConnection

from baseball_rag.public_release_config import canonical_json_bytes
from baseball_rag.query.data_identity import semantic_manifest_sha256

CACHE_SCHEMA_VERSION = "ground-ball-provider-runtime-cache-v2"
CACHE_POINTER_SCHEMA_VERSION = "ground-ball-provider-runtime-cache-pointer-v1"
CACHE_REFERENCE_ENV = "GROUNDBALL_PROVIDER_RUNTIME_CACHE"
_CACHE_ROOT = Path("/app/provider-runtime-cache")
_IMAGE_BUNDLE_ROOT = Path("/app/release-bundle")
_IMAGE_RUNTIME_CONFIG = Path("/app/release-config/protected-preview-runtime.json")
_POINTER_NAME = "pointer.json"
_DATABASE_NAME = "runtime.duckdb"
_METADATA_NAME = "metadata.json"
_REQUIRED_OWNER_UID = 0
_SHA256_LENGTH = 64
_MAX_METADATA_BYTES = 1_048_576
_MAX_POINTER_BYTES = 16_384
_LOCK_WAIT_SECONDS = 30.0


class ProviderRuntimeCacheError(RuntimeError):
    """The protected-provider runtime cache is absent, foreign, or mutable."""


def _require_root_build_privilege() -> None:
    """Deny every retained builder mutation unless the effective UID is literal root."""
    if _effective_uid() != 0:
        raise ProviderRuntimeCacheError("Provider runtime cache construction requires root.")


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
    reference: str
    database_sha256: str
    image_build_preparation_seconds: float


def clear_provider_runtime_cache_reference() -> None:
    """Remove only the validated inherited digest reference, never image files."""
    os.environ.pop(CACHE_REFERENCE_ENV, None)


def provider_image_boundary_detected() -> bool:
    """Classify any fixed image path or declaration as provider mode, even if corrupt."""
    if os.environ.get("GROUNDBALL_RELEASE_BUNDLE") == str(_IMAGE_BUNDLE_ROOT):
        return True
    if os.environ.get("GROUNDBALL_RUNTIME_CONFIG") == str(_IMAGE_RUNTIME_CONFIG):
        return True
    return any(_path_entry_exists(path) for path in _fixed_image_boundary_paths())


def require_provider_image_boundary() -> None:
    """Require the exact nonsymlink image paths and a canonical prepared-cache pointer."""
    if not provider_image_boundary_detected():
        raise ProviderRuntimeCacheError("Provider image boundary is absent.")
    if os.environ.get("GROUNDBALL_RELEASE_BUNDLE") != str(_IMAGE_BUNDLE_ROOT) or os.environ.get(
        "GROUNDBALL_RUNTIME_CONFIG"
    ) != str(_IMAGE_RUNTIME_CONFIG):
        raise ProviderRuntimeCacheError("Provider image runtime paths are invalid.")
    _require_nonsymlink_directory(_IMAGE_BUNDLE_ROOT, "Release Bundle")
    _require_nonsymlink_file(_IMAGE_RUNTIME_CONFIG, "runtime configuration")
    _require_parent_boundary(_CACHE_ROOT.parent)
    _require_directory(_CACHE_ROOT, 0o555)
    pointer_bytes, _ = _read_verified_file(_CACHE_ROOT / _POINTER_NAME, 0o444, _MAX_POINTER_BYTES)
    pointer = _decode_object(pointer_bytes, "pointer")
    _validate_pointer(pointer, pointer_bytes)
    reference = pointer["cache_metadata_sha256"]
    if set(_entry_names(_CACHE_ROOT)) != {_POINTER_NAME, reference}:
        raise ProviderRuntimeCacheError("Provider runtime cache root inventory is invalid.")
    _require_directory(_CACHE_ROOT / reference, 0o555)


def build_provider_runtime_cache(
    runtime: RuntimeForCache,
    *,
    source_commit: str,
    release_bundle_digest: str,
    runtime_configuration_digest: str,
    image_build_preparation_seconds: float,
) -> str:
    """Build one root-owned fixed image cache, or validate an identical prior build."""
    _require_root_build_privilege()
    clear_provider_runtime_cache_reference()
    _require_commit(source_commit)
    _require_digest(release_bundle_digest)
    _require_digest(runtime_configuration_digest)
    if not _nonnegative_finite(image_build_preparation_seconds):
        raise ProviderRuntimeCacheError("Provider runtime cache preparation timing is invalid.")

    root = _CACHE_ROOT
    parent = root.parent
    _require_parent_boundary(parent)
    lock = parent / f".{root.name}.lock"
    acquired = _acquire_build_lock(lock, root)
    if not acquired:
        validated = _validate_root(
            expected_source_commit=source_commit,
            expected_release_bundle_digest=release_bundle_digest,
            expected_runtime_configuration_digest=runtime_configuration_digest,
            open_database=False,
        )
        validated.connection.close()
        return validated.reference

    temporary: Path | None = None
    published = False
    try:
        if root.exists() or root.is_symlink():
            validated = _validate_root(
                expected_source_commit=source_commit,
                expected_release_bundle_digest=release_bundle_digest,
                expected_runtime_configuration_digest=runtime_configuration_digest,
                open_database=False,
            )
            validated.connection.close()
            return validated.reference
        temporary = Path(tempfile.mkdtemp(prefix=f".{root.name}.building-", dir=parent))
        reference = _materialize_cache(
            temporary,
            runtime,
            source_commit=source_commit,
            release_bundle_digest=release_bundle_digest,
            runtime_configuration_digest=runtime_configuration_digest,
            image_build_preparation_seconds=float(image_build_preparation_seconds),
        )
        os.rename(temporary, root)
        temporary = None
        published = True
        validated = _validate_root(
            expected_source_commit=source_commit,
            expected_release_bundle_digest=release_bundle_digest,
            expected_runtime_configuration_digest=runtime_configuration_digest,
            open_database=False,
        )
        if validated.reference != reference:
            validated.connection.close()
            raise ProviderRuntimeCacheError("Provider runtime cache publication is invalid.")
        validated.connection.close()
        return reference
    except Exception:
        clear_provider_runtime_cache_reference()
        if temporary is not None:
            _remove_build_tree(temporary)
        if published:
            _remove_build_tree(root)
        raise
    finally:
        try:
            lock.rmdir()
        except OSError:
            pass


def activate_provider_runtime_cache(
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
) -> ValidatedProviderRuntimeCache:
    """Validate the fixed pointer and immutable object, then publish only its digest."""
    validated = _validate_root(
        expected_source_commit=expected_source_commit,
        expected_release_bundle_digest=expected_release_bundle_digest,
        expected_runtime_configuration_digest=expected_runtime_configuration_digest,
        open_database=True,
    )
    inherited = os.environ.get(CACHE_REFERENCE_ENV)
    if inherited is not None and inherited != validated.reference:
        validated.connection.close()
        raise ProviderRuntimeCacheError("Provider runtime cache reference is foreign.")
    os.environ[CACHE_REFERENCE_ENV] = validated.reference
    return validated


def load_provider_runtime_cache(
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
) -> ValidatedProviderRuntimeCache:
    """Activate only the fixed root-owned image pointer; no caller path is accepted."""
    return activate_provider_runtime_cache(
        expected_source_commit=expected_source_commit,
        expected_release_bundle_digest=expected_release_bundle_digest,
        expected_runtime_configuration_digest=expected_runtime_configuration_digest,
    )


def inspect_provider_runtime_cache(
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
) -> dict[str, object]:
    """Return strict cache evidence without publishing or retaining a database connection."""
    validated = _validate_root(
        expected_source_commit=expected_source_commit,
        expected_release_bundle_digest=expected_release_bundle_digest,
        expected_runtime_configuration_digest=expected_runtime_configuration_digest,
        open_database=False,
    )
    validated.connection.close()
    return {
        "cache_reference": validated.reference,
        "database_sha256": validated.database_sha256,
        "image_build_preparation_seconds": validated.image_build_preparation_seconds,
    }


def require_provider_runtime_cache_for_worker() -> None:
    """Eagerly load the exact provider runtime before interpreting worker input."""
    runtime_config_path = os.environ.get("GROUNDBALL_RUNTIME_CONFIG")
    if provider_image_boundary_detected():
        require_provider_image_boundary()
        runtime_config_path = str(_IMAGE_RUNTIME_CONFIG)
    elif runtime_config_path is None:
        return
    from baseball_rag.public_release_config import load_runtime_configuration

    configuration = load_runtime_configuration(runtime_config_path)
    if not configuration.provider_deployment:
        if provider_image_boundary_detected():
            raise ProviderRuntimeCacheError("Provider image runtime configuration is invalid.")
        return
    from baseball_rag.query.runtime import published_data_runtime

    published_data_runtime()


def build_image_provider_runtime_cache() -> dict[str, object]:
    """Fully verify the fixed image Bundle/runtime and build the protected cache as root."""
    _require_root_build_privilege()
    from baseball_rag.public_release_config import load_runtime_configuration
    from baseball_rag.query.coverage import load_passing_coverage_report
    from baseball_rag.query.runtime import _published_provider_runtime, _runtime_for
    from baseball_rag.release_bundle import check_release_bundle

    bundle_root = Path(os.environ.get("GROUNDBALL_RELEASE_BUNDLE", str(_IMAGE_BUNDLE_ROOT)))
    if bundle_root != _IMAGE_BUNDLE_ROOT:
        raise ProviderRuntimeCacheError("Provider image Release Bundle path is invalid.")
    config_path = _IMAGE_RUNTIME_CONFIG
    configuration = load_runtime_configuration(config_path)
    if not configuration.provider_deployment:
        raise ProviderRuntimeCacheError("Provider image runtime configuration is invalid.")
    try:
        manifest = json.loads((bundle_root / "release-manifest.json").read_bytes())
        source_commit = manifest["source_commit"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ProviderRuntimeCacheError(
            "Provider image Release Bundle identity is invalid."
        ) from exc
    _require_commit(source_commit)

    started = time.monotonic()
    identity = check_release_bundle(bundle_root, expected_source_commit=source_commit)
    previous_config = os.environ.get("GROUNDBALL_RUNTIME_CONFIG")
    previous_source = os.environ.get("GROUNDBALL_SOURCE_COMMIT")
    os.environ["GROUNDBALL_RELEASE_BUNDLE"] = str(bundle_root)
    os.environ["GROUNDBALL_SOURCE_COMMIT"] = source_commit
    clear_provider_runtime_cache_reference()
    _published_provider_runtime.cache_clear()
    _runtime_for.cache_clear()
    try:
        runtime = _runtime_for(str(bundle_root / "data"))
        preparation_seconds = time.monotonic() - started
        reference = build_provider_runtime_cache(
            runtime,
            source_commit=source_commit,
            release_bundle_digest=identity.digest,
            runtime_configuration_digest=configuration.digest,
            image_build_preparation_seconds=preparation_seconds,
        )
        os.environ["GROUNDBALL_RUNTIME_CONFIG"] = str(config_path)
        _published_provider_runtime.cache_clear()
        coverage = load_passing_coverage_report()
    finally:
        if previous_config is None:
            os.environ.pop("GROUNDBALL_RUNTIME_CONFIG", None)
        else:
            os.environ["GROUNDBALL_RUNTIME_CONFIG"] = previous_config
        if previous_source is None:
            os.environ.pop("GROUNDBALL_SOURCE_COMMIT", None)
        else:
            os.environ["GROUNDBALL_SOURCE_COMMIT"] = previous_source
        clear_provider_runtime_cache_reference()
        _published_provider_runtime.cache_clear()
    return {
        "cache_reference": reference,
        "coverage_proof_id": coverage["proof_id"],
        "image_build_preparation_seconds": round(preparation_seconds, 6),
        "release_bundle_digest": identity.digest,
        "runtime_configuration_digest": configuration.digest,
        "source_commit": source_commit,
    }


def _materialize_cache(
    root: Path,
    runtime: RuntimeForCache,
    *,
    source_commit: str,
    release_bundle_digest: str,
    runtime_configuration_digest: str,
    image_build_preparation_seconds: float,
) -> str:
    _require_root_build_privilege()
    database_path = root / _DATABASE_NAME
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
    cache_dir = root / reference
    cache_dir.mkdir(mode=0o700)
    os.rename(database_path, cache_dir / _DATABASE_NAME)
    _write_new_file(cache_dir / _METADATA_NAME, metadata_bytes)
    pointer = {
        "cache_metadata_sha256": reference,
        "image_build_preparation_seconds": image_build_preparation_seconds,
        "release_bundle_digest": release_bundle_digest,
        "runtime_configuration_digest": runtime_configuration_digest,
        "schema_version": CACHE_POINTER_SCHEMA_VERSION,
        "source_commit": source_commit,
    }
    pointer_bytes = canonical_json_bytes(pointer)
    _validate_pointer(pointer, pointer_bytes)
    _write_new_file(root / _POINTER_NAME, pointer_bytes)
    for path in (cache_dir / _DATABASE_NAME, cache_dir / _METADATA_NAME, root / _POINTER_NAME):
        os.chmod(path, 0o444)
    os.chmod(cache_dir, 0o555)
    os.chmod(root, 0o555)
    return reference


def _validate_root(
    *,
    expected_source_commit: str,
    expected_release_bundle_digest: str,
    expected_runtime_configuration_digest: str,
    open_database: bool,
) -> ValidatedProviderRuntimeCache:
    _require_commit(expected_source_commit)
    _require_digest(expected_release_bundle_digest)
    _require_digest(expected_runtime_configuration_digest)
    root = _CACHE_ROOT
    _require_parent_boundary(root.parent)
    _require_directory(root, 0o555)
    pointer_path = root / _POINTER_NAME
    pointer_bytes, _ = _read_verified_file(pointer_path, 0o444, _MAX_POINTER_BYTES)
    pointer = _decode_object(pointer_bytes, "pointer")
    _validate_pointer(pointer, pointer_bytes)
    reference = pointer["cache_metadata_sha256"]
    if set(_entry_names(root)) != {_POINTER_NAME, reference}:
        raise ProviderRuntimeCacheError("Provider runtime cache root inventory is invalid.")
    if (
        pointer["source_commit"] != expected_source_commit
        or pointer["release_bundle_digest"] != expected_release_bundle_digest
        or pointer["runtime_configuration_digest"] != expected_runtime_configuration_digest
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache pointer identity does not match.")

    cache_dir = root / reference
    _require_directory(cache_dir, 0o555)
    if set(_entry_names(cache_dir)) != {_DATABASE_NAME, _METADATA_NAME}:
        raise ProviderRuntimeCacheError("Provider runtime cache object inventory is invalid.")
    metadata_bytes, _ = _read_verified_file(cache_dir / _METADATA_NAME, 0o444, _MAX_METADATA_BYTES)
    if hashlib.sha256(metadata_bytes).hexdigest() != reference:
        raise ProviderRuntimeCacheError("Provider runtime cache metadata hash is invalid.")
    metadata = _decode_object(metadata_bytes, "metadata")
    _validate_metadata(metadata, metadata_bytes)
    if (
        metadata["source_commit"] != expected_source_commit
        or metadata["release_bundle_digest"] != expected_release_bundle_digest
        or metadata["runtime_configuration_digest"] != expected_runtime_configuration_digest
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache identity does not match.")

    database_path = cache_dir / _DATABASE_NAME
    descriptor = _open_verified_file(database_path, 0o444)
    connection: DuckDBPyConnection | None = None
    try:
        before = os.fstat(descriptor)
        if before.st_size != metadata["database_size_bytes"]:
            raise ProviderRuntimeCacheError("Provider runtime cache database size is invalid.")
        if _descriptor_sha256(descriptor) != metadata["database_sha256"]:
            raise ProviderRuntimeCacheError("Provider runtime cache database hash is invalid.")
        _require_unchanged(before, os.fstat(descriptor))
        _require_same_path_object(database_path, before, 0o444)
        if open_database:
            try:
                connection = duckdb.connect(database=str(database_path), read_only=True)
            except Exception as exc:
                raise ProviderRuntimeCacheError(
                    "Provider runtime cache database is invalid."
                ) from exc
            if _relations(connection) != tuple(metadata["required_relations"]):
                raise ProviderRuntimeCacheError(
                    "Provider runtime cache relation inventory is invalid."
                )
            _require_unchanged(before, os.fstat(descriptor))
            _require_same_path_object(database_path, before, 0o444)
    except Exception:
        if connection is not None:
            connection.close()
        raise
    finally:
        os.close(descriptor)
    if connection is None:
        connection = duckdb.connect(database=":memory:")
    return ValidatedProviderRuntimeCache(
        connection=connection,
        data_dir=Path(os.environ.get("GROUNDBALL_RELEASE_BUNDLE", str(_IMAGE_BUNDLE_ROOT)))
        / "data",
        manifest=metadata["data_manifest"],
        data_release=metadata["data_release"],
        source_fingerprints=metadata["source_fingerprints"],
        relations=tuple(metadata["required_relations"]),
        reference=reference,
        database_sha256=metadata["database_sha256"],
        image_build_preparation_seconds=float(pointer["image_build_preparation_seconds"]),
    )


def _validate_pointer(pointer: dict[str, Any], content: bytes) -> None:
    if (
        set(pointer)
        != {
            "cache_metadata_sha256",
            "image_build_preparation_seconds",
            "release_bundle_digest",
            "runtime_configuration_digest",
            "schema_version",
            "source_commit",
        }
        or pointer.get("schema_version") != CACHE_POINTER_SCHEMA_VERSION
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache pointer shape is invalid.")
    for key in (
        "cache_metadata_sha256",
        "release_bundle_digest",
        "runtime_configuration_digest",
    ):
        _require_digest(pointer.get(key))
    _require_commit(pointer.get("source_commit"))
    if not _nonnegative_finite(pointer.get("image_build_preparation_seconds")):
        raise ProviderRuntimeCacheError("Provider runtime cache pointer values are invalid.")
    if content != canonical_json_bytes(pointer):
        raise ProviderRuntimeCacheError("Provider runtime cache pointer is noncanonical.")


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


def _copy_database(connection: DuckDBPyConnection, destination: Path) -> None:
    _require_root_build_privilege()
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


def _acquire_build_lock(lock: Path, root: Path) -> bool:
    _require_root_build_privilege()
    deadline = time.monotonic() + _LOCK_WAIT_SECONDS
    while True:
        try:
            lock.mkdir(mode=0o700)
            return True
        except FileExistsError:
            if root.exists() and not root.is_symlink():
                return False
            if time.monotonic() >= deadline:
                raise ProviderRuntimeCacheError("Provider runtime cache build is already active.")
            time.sleep(0.01)
        except OSError as exc:
            raise ProviderRuntimeCacheError("Provider runtime cache lock is unavailable.") from exc


def _remove_build_tree(path: Path) -> None:
    _require_root_build_privilege()
    try:
        for member in path.rglob("*"):
            if not member.is_symlink():
                try:
                    os.chmod(member, 0o700 if member.is_dir() else 0o600)
                except OSError:
                    pass
        os.chmod(path, 0o700)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


def _fixed_image_boundary_paths() -> tuple[Path, ...]:
    return (_CACHE_ROOT, _IMAGE_BUNDLE_ROOT, _IMAGE_RUNTIME_CONFIG)


def _path_entry_exists(path: Path) -> bool:
    try:
        path.lstat()
    except OSError:
        return False
    return True


def _require_nonsymlink_directory(path: Path, label: str) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ProviderRuntimeCacheError(f"Provider image {label} is invalid.") from exc
    if not stat.S_ISDIR(details.st_mode):
        raise ProviderRuntimeCacheError(f"Provider image {label} is invalid.")


def _require_nonsymlink_file(path: Path, label: str) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ProviderRuntimeCacheError(f"Provider image {label} is invalid.") from exc
    if not stat.S_ISREG(details.st_mode):
        raise ProviderRuntimeCacheError(f"Provider image {label} is invalid.")


def _require_parent_boundary(path: Path) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache parent is invalid.") from exc
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != _REQUIRED_OWNER_UID
        or stat.S_IMODE(details.st_mode) & 0o022
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache parent is invalid.")


def _require_directory(path: Path, mode: int) -> None:
    try:
        details = path.lstat()
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache directory is invalid.") from exc
    if (
        not stat.S_ISDIR(details.st_mode)
        or details.st_uid != _REQUIRED_OWNER_UID
        or stat.S_IMODE(details.st_mode) != mode
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache directory is invalid.")


def _entry_names(path: Path) -> tuple[str, ...]:
    try:
        return tuple(entry.name for entry in os.scandir(path))
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache inventory is invalid.") from exc


def _open_verified_file(path: Path, mode: int) -> int:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache file is invalid.") from exc
    try:
        _require_file_stat(os.fstat(descriptor), mode)
        _require_same_path_object(path, os.fstat(descriptor), mode)
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _read_verified_file(path: Path, mode: int, maximum: int) -> tuple[bytes, os.stat_result]:
    descriptor = _open_verified_file(path, mode)
    try:
        before = os.fstat(descriptor)
        if before.st_size > maximum:
            raise ProviderRuntimeCacheError("Provider runtime cache file is too large.")
        content = _descriptor_bytes(descriptor)
        _require_unchanged(before, os.fstat(descriptor))
        _require_same_path_object(path, before, mode)
        return content, before
    finally:
        os.close(descriptor)


def _require_file_stat(details: os.stat_result, mode: int) -> None:
    if (
        not stat.S_ISREG(details.st_mode)
        or details.st_uid != _REQUIRED_OWNER_UID
        or stat.S_IMODE(details.st_mode) != mode
        or details.st_nlink != 1
    ):
        raise ProviderRuntimeCacheError("Provider runtime cache file is invalid.")


def _require_same_path_object(path: Path, expected: os.stat_result, mode: int) -> None:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise ProviderRuntimeCacheError("Provider runtime cache file changed.") from exc
    _require_file_stat(observed, mode)
    _require_unchanged(expected, observed)


def _require_unchanged(before: os.stat_result, after: os.stat_result) -> None:
    fields = (
        "st_dev",
        "st_ino",
        "st_uid",
        "st_gid",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise ProviderRuntimeCacheError("Provider runtime cache file changed during validation.")


def _descriptor_bytes(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while chunk := os.read(descriptor, 1024 * 1024):
        chunks.append(chunk)
    return b"".join(chunks)


def _descriptor_sha256(descriptor: int) -> str:
    digest = hashlib.sha256()
    os.lseek(descriptor, 0, os.SEEK_SET)
    while chunk := os.read(descriptor, 1024 * 1024):
        digest.update(chunk)
    return digest.hexdigest()


def _decode_object(content: bytes, label: str) -> dict[str, Any]:
    def reject_duplicate(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProviderRuntimeCacheError(
                    f"Provider runtime cache {label} contains duplicate fields."
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(content, object_pairs_hook=reject_duplicate)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderRuntimeCacheError(f"Provider runtime cache {label} is invalid.") from exc
    if not isinstance(decoded, dict):
        raise ProviderRuntimeCacheError(f"Provider runtime cache {label} is invalid.")
    return decoded


def _write_new_file(path: Path, content: bytes) -> None:
    _require_root_build_privilege()
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
    _require_root_build_privilege()
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


def _nonnegative_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and float(value) >= 0
    )


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


def main() -> int:
    print(canonical_json_bytes(build_image_provider_runtime_cache()).decode("utf-8"), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
