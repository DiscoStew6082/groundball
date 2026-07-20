"""Fixed root-owned provider runtime-cache and worker activation contracts."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pytest

from baseball_rag.public_execution import ExecutionRequest, SubprocessExecutionRunner, _execute
from baseball_rag.public_release_config import canonical_json_bytes, load_runtime_configuration
from baseball_rag.query.runtime import (
    _published_provider_runtime,
    _runtime_for,
    published_data_runtime,
)

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "release/bundle"
PROVIDER_CONFIG = ROOT / "release/config/protected-preview-runtime.json"


def _source_commit() -> str:
    return str(
        json.loads((BUNDLE / "release-manifest.json").read_text(encoding="utf-8"))["source_commit"]
    )


def _bundle_digest() -> str:
    return hashlib.sha256((BUNDLE / "release-manifest.json").read_bytes()).hexdigest()


def _prepare_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, str]:
    import baseball_rag.provider_runtime_cache as cache
    import baseball_rag.query.runtime as query_runtime

    monkeypatch.setattr(query_runtime, "_PROVIDER_BUNDLE_ROOT", BUNDLE)
    monkeypatch.setattr(query_runtime, "_PROVIDER_RUNTIME_CONFIG_PATH", PROVIDER_CONFIG)
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    monkeypatch.delenv(cache.CACHE_REFERENCE_ENV, raising=False)
    _published_provider_runtime.cache_clear()
    _runtime_for.cache_clear()
    runtime = published_data_runtime()

    cache_root = tmp_path / "provider-runtime-cache"
    monkeypatch.setattr(cache, "_CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache, "_IMAGE_BUNDLE_ROOT", BUNDLE)
    monkeypatch.setattr(cache, "_IMAGE_RUNTIME_CONFIG", PROVIDER_CONFIG)
    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid())
    monkeypatch.setattr(cache, "_effective_uid", lambda: 0)
    reference = cache.build_provider_runtime_cache(
        runtime,
        source_commit=_source_commit(),
        release_bundle_digest=_bundle_digest(),
        runtime_configuration_digest=load_runtime_configuration(PROVIDER_CONFIG).digest,
        image_build_preparation_seconds=1.25,
    )
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(PROVIDER_CONFIG))
    _published_provider_runtime.cache_clear()
    return cache_root, reference


def _make_mutable(cache_root: Path, reference: str) -> Path:
    cache_dir = cache_root / reference
    os.chmod(cache_root, 0o755)
    os.chmod(cache_dir, 0o755)
    return cache_dir


def _seal(cache_root: Path, reference: str) -> None:
    os.chmod(cache_root / reference, 0o555)
    os.chmod(cache_root, 0o555)
    _published_provider_runtime.cache_clear()


def _tree_snapshot(root: Path) -> dict[str, tuple[str, bytes]]:
    snapshot: dict[str, tuple[str, bytes]] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_dir():
            snapshot[relative] = ("directory", b"")
        elif path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path).encode())
        else:
            snapshot[relative] = ("file", path.read_bytes())
    return snapshot


class _UnreadableRuntime:
    def __getattribute__(self, name: str) -> object:
        raise AssertionError(f"runtime input was read through {name}")


@pytest.mark.parametrize(
    "entry_point",
    [
        "build_image_provider_runtime_cache",
        "build_provider_runtime_cache",
        "_materialize_cache",
        "_copy_database",
        "_acquire_build_lock",
        "_remove_build_tree",
        "_write_new_file",
        "_sync_file",
    ],
)
def test_every_retained_builder_mutation_entry_point_denies_uid_10001_before_side_effects(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, entry_point: str
) -> None:
    import baseball_rag.provider_runtime_cache as cache

    sandbox = tmp_path / "builder-probe"
    sandbox.mkdir()
    removable = sandbox / "removable"
    removable.mkdir()
    (removable / "marker").write_bytes(b"preserve")
    sync_target = sandbox / "sync-target"
    sync_target.write_bytes(b"unchanged")
    before = _tree_snapshot(sandbox)
    monkeypatch.setattr(cache, "_effective_uid", lambda: 10001)
    monkeypatch.setenv(cache.CACHE_REFERENCE_ENV, "f" * 64)

    runtime = _UnreadableRuntime()
    calls = {
        "build_image_provider_runtime_cache": lambda: cache.build_image_provider_runtime_cache(),
        "build_provider_runtime_cache": lambda: cache.build_provider_runtime_cache(
            runtime,
            source_commit="1" * 40,
            release_bundle_digest="2" * 64,
            runtime_configuration_digest="3" * 64,
            image_build_preparation_seconds=0.0,
        ),
        "_materialize_cache": lambda: cache._materialize_cache(
            sandbox / "materialized",
            runtime,
            source_commit="1" * 40,
            release_bundle_digest="2" * 64,
            runtime_configuration_digest="3" * 64,
            image_build_preparation_seconds=0.0,
        ),
        "_copy_database": lambda: cache._copy_database(runtime, sandbox / "copied.duckdb"),
        "_acquire_build_lock": lambda: cache._acquire_build_lock(
            sandbox / "build.lock", sandbox / "cache-root"
        ),
        "_remove_build_tree": lambda: cache._remove_build_tree(removable),
        "_write_new_file": lambda: cache._write_new_file(sandbox / "created", b"forbidden"),
        "_sync_file": lambda: cache._sync_file(sync_target),
    }

    original_read_bytes = Path.read_bytes
    if entry_point == "build_image_provider_runtime_cache":
        monkeypatch.setattr(
            Path,
            "read_bytes",
            lambda _path: (_ for _ in ()).throw(AssertionError("source path was read")),
        )
    try:
        with pytest.raises(cache.ProviderRuntimeCacheError, match="requires root"):
            calls[entry_point]()
    finally:
        monkeypatch.setattr(Path, "read_bytes", original_read_bytes)

    assert _tree_snapshot(sandbox) == before
    assert os.environ[cache.CACHE_REFERENCE_ENV] == "f" * 64
    assert not list(tmp_path.rglob("*.duckdb"))


def test_root_guard_is_first_statement_of_every_retained_mutation_entry_point() -> None:
    source_path = ROOT / "src/baseball_rag/provider_runtime_cache.py"
    module = ast.parse(source_path.read_text(encoding="utf-8"))
    functions = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
    guarded = {
        "build_image_provider_runtime_cache",
        "build_provider_runtime_cache",
        "_materialize_cache",
        "_copy_database",
        "_acquire_build_lock",
        "_remove_build_tree",
        "_write_new_file",
        "_sync_file",
    }

    for name in guarded:
        body = functions[name].body
        first = body[1] if ast.get_docstring(functions[name], clean=False) is not None else body[0]
        assert isinstance(first, ast.Expr), name
        assert isinstance(first.value, ast.Call), name
        assert isinstance(first.value.func, ast.Name), name
        assert first.value.func.id == "_require_root_build_privilege", name

    guard = functions["_require_root_build_privilege"]
    assert "_effective_uid() != 0" in ast.unparse(guard)


def test_builder_publishes_exact_pointer_and_one_root_owned_read_only_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    pointer = json.loads((cache_root / "pointer.json").read_text(encoding="utf-8"))

    assert {item.name for item in cache_root.iterdir()} == {"pointer.json", reference}
    assert {item.name for item in (cache_root / reference).iterdir()} == {
        "metadata.json",
        "runtime.duckdb",
    }
    assert pointer["cache_metadata_sha256"] == reference
    assert pointer["image_build_preparation_seconds"] == 1.25
    assert os.environ.get("GROUNDBALL_PROVIDER_RUNTIME_CACHE") is None
    assert cache_root.stat().st_mode & 0o777 == 0o555
    assert (cache_root / reference).stat().st_mode & 0o777 == 0o555
    for path in (
        cache_root / "pointer.json",
        cache_root / reference / "metadata.json",
        cache_root / reference / "runtime.duckdb",
    ):
        assert path.stat().st_uid == os.geteuid()
        assert path.stat().st_mode & 0o777 == 0o444
        assert path.stat().st_nlink == 1


def test_fixed_cache_activates_once_and_returns_exact_40_40_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _, reference = _prepare_cache(monkeypatch, tmp_path)

    first = published_data_runtime()
    second = published_data_runtime()
    rows = first.connection.execute(
        'SELECT trim(concat_ws(\' \', p."nameFirst", p."nameLast")), b."yearID", '
        'sum(b."HR"), sum(b."SB") FROM batting b JOIN people p USING ("playerID") '
        'GROUP BY b."playerID", p."nameFirst", p."nameLast", b."yearID" '
        'HAVING sum(b."HR") >= 40 AND sum(b."SB") >= 40 '
        'ORDER BY b."yearID", trim(concat_ws(\' \', p."nameFirst", p."nameLast"))'
    ).fetchall()

    assert rows == [
        ("Jose Canseco", 1988, 42, 40),
        ("Barry Bonds", 1996, 42, 40),
        ("Alex Rodriguez", 1998, 42, 46),
        ("Alfonso Soriano", 2006, 46, 41),
        ("Ronald Acuña", 2023, 41, 73),
        ("Shohei Ohtani", 2024, 54, 59),
    ]
    assert first is second
    assert os.environ["GROUNDBALL_PROVIDER_RUNTIME_CACHE"] == reference
    with pytest.raises(duckdb.Error):
        first.connection.execute("CREATE TABLE forbidden(value INTEGER)")


def test_provider_missing_cache_fails_for_supported_and_unsupported_input(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as cache
    import baseball_rag.query.runtime as query_runtime

    monkeypatch.setattr(query_runtime, "_PROVIDER_BUNDLE_ROOT", BUNDLE)
    monkeypatch.setattr(query_runtime, "_PROVIDER_RUNTIME_CONFIG_PATH", PROVIDER_CONFIG)
    monkeypatch.setattr(cache, "_CACHE_ROOT", tmp_path / "absent")
    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid())
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(PROVIDER_CONFIG))
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv(cache.CACHE_REFERENCE_ENV, raising=False)
    _published_provider_runtime.cache_clear()

    assert _execute(ExecutionRequest("query", "40-40", None)) == {"kind": "failed"}
    assert _execute(ExecutionRequest("unsupported", "anything", None)) == {"kind": "failed"}
    child = SubprocessExecutionRunner().run(
        ExecutionRequest("query", "40-40", None), timeout_seconds=10
    )
    assert child.kind == "failed"
    assert child.detail == "Public Query Run execution failed."


@pytest.mark.parametrize(
    ("target", "mutation"),
    [
        ("root", lambda root, _cache: (root / "foreign").write_text("x")),
        ("object", lambda _root, cache: (cache / "foreign").write_text("x")),
        ("pointer", lambda root, _cache: (root / "pointer.json").unlink()),
        ("database-mode", lambda _root, cache: os.chmod(cache / "runtime.duckdb", 0o644)),
        ("metadata-mode", lambda _root, cache: os.chmod(cache / "metadata.json", 0o440)),
        ("database-link", lambda _root, cache: os.link(cache / "runtime.duckdb", cache / "link")),
    ],
)
def test_activation_rejects_extra_missing_mode_and_link_drift(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str, mutation
) -> None:
    from baseball_rag.provider_runtime_cache import ProviderRuntimeCacheError

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    cache_dir = _make_mutable(cache_root, reference)
    mutation(cache_root, cache_dir)
    _seal(cache_root, reference)

    with pytest.raises(ProviderRuntimeCacheError):
        published_data_runtime()


def test_activation_rejects_rehashed_unexpected_relation_and_wrong_owner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as cache

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    cache_dir = _make_mutable(cache_root, reference)
    metadata_path = cache_dir / "metadata.json"
    pointer_path = cache_root / "pointer.json"
    os.chmod(metadata_path, 0o644)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["required_relations"].append("unexpected_relation")
    metadata_bytes = canonical_json_bytes(metadata)
    metadata_path.write_bytes(metadata_bytes)
    os.chmod(metadata_path, 0o444)
    changed_reference = hashlib.sha256(metadata_bytes).hexdigest()
    cache_dir.rename(cache_root / changed_reference)
    os.chmod(pointer_path, 0o644)
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["cache_metadata_sha256"] = changed_reference
    pointer_path.write_bytes(canonical_json_bytes(pointer))
    os.chmod(pointer_path, 0o444)
    _seal(cache_root, changed_reference)

    with pytest.raises(cache.ProviderRuntimeCacheError, match="relation"):
        published_data_runtime()

    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid() + 1)
    _published_provider_runtime.cache_clear()
    with pytest.raises(cache.ProviderRuntimeCacheError, match="parent"):
        published_data_runtime()


@pytest.mark.parametrize("kind", ["pointer", "metadata", "database", "symlink", "foreign-env"])
def test_activation_rejects_tampered_or_foreign_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, kind: str
) -> None:
    from baseball_rag.provider_runtime_cache import ProviderRuntimeCacheError

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    cache_dir = _make_mutable(cache_root, reference)
    if kind == "pointer":
        pointer = cache_root / "pointer.json"
        os.chmod(pointer, 0o644)
        pointer.write_text("{}\n", encoding="utf-8")
        os.chmod(pointer, 0o444)
    elif kind == "metadata":
        metadata = cache_dir / "metadata.json"
        os.chmod(metadata, 0o644)
        metadata.write_bytes(metadata.read_bytes() + b" ")
        os.chmod(metadata, 0o444)
    elif kind == "database":
        database = cache_dir / "runtime.duckdb"
        os.chmod(database, 0o644)
        with database.open("r+b") as stream:
            stream.seek(-1, os.SEEK_END)
            last = stream.read(1)
            stream.seek(-1, os.SEEK_END)
            stream.write(bytes([last[0] ^ 1]))
        os.chmod(database, 0o444)
    elif kind == "symlink":
        database = cache_dir / "runtime.duckdb"
        database.unlink()
        database.symlink_to(BUNDLE / "release-manifest.json")
    else:
        monkeypatch.setenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", "f" * 64)
    _seal(cache_root, reference)

    with pytest.raises(ProviderRuntimeCacheError):
        published_data_runtime()


def test_concurrent_initial_builds_publish_one_complete_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as cache

    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    _runtime_for.cache_clear()
    runtime = published_data_runtime()
    cache_root = tmp_path / "concurrent-cache"
    monkeypatch.setattr(cache, "_CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid())
    monkeypatch.setattr(cache, "_effective_uid", lambda: 0)
    kwargs = {
        "source_commit": _source_commit(),
        "release_bundle_digest": _bundle_digest(),
        "runtime_configuration_digest": load_runtime_configuration(PROVIDER_CONFIG).digest,
        "image_build_preparation_seconds": 1.0,
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        observed = list(
            executor.map(
                lambda _index: cache.build_provider_runtime_cache(runtime, **kwargs),
                range(4),
            )
        )

    assert len(set(observed)) == 1
    assert {item.name for item in cache_root.iterdir()} == {"pointer.json", observed[0]}
    assert not list(tmp_path.glob(".concurrent-cache.building-*"))


def test_builder_is_idempotent_and_concurrent_callers_observe_one_object(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as cache

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    runtime = _runtime_for(str(BUNDLE / "data"))
    kwargs = {
        "source_commit": _source_commit(),
        "release_bundle_digest": _bundle_digest(),
        "runtime_configuration_digest": load_runtime_configuration(PROVIDER_CONFIG).digest,
        "image_build_preparation_seconds": 1.25,
    }

    with ThreadPoolExecutor(max_workers=4) as executor:
        observed = list(
            executor.map(
                lambda _index: cache.build_provider_runtime_cache(runtime, **kwargs), range(4)
            )
        )

    assert observed == [reference] * 4
    assert {item.name for item in cache_root.iterdir()} == {"pointer.json", reference}


def test_failed_postpublication_validation_removes_new_root_atomically(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as cache

    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    runtime = published_data_runtime()
    cache_root = tmp_path / "invalid-published-cache"
    monkeypatch.setattr(cache, "_CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid())
    monkeypatch.setattr(cache, "_effective_uid", lambda: 0)
    monkeypatch.setattr(
        cache,
        "_validate_root",
        lambda **_kwargs: (_ for _ in ()).throw(cache.ProviderRuntimeCacheError("invalid")),
    )

    with pytest.raises(cache.ProviderRuntimeCacheError, match="invalid"):
        cache.build_provider_runtime_cache(
            runtime,
            source_commit=_source_commit(),
            release_bundle_digest=_bundle_digest(),
            runtime_configuration_digest=load_runtime_configuration(PROVIDER_CONFIG).digest,
            image_build_preparation_seconds=0.0,
        )

    assert not cache_root.exists()
    assert not list(tmp_path.glob(".invalid-published-cache.building-*"))


def test_failed_build_removes_partial_tree_and_publishes_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as cache

    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    runtime = published_data_runtime()
    cache_root = tmp_path / "failed-cache"
    monkeypatch.setattr(cache, "_CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid())
    monkeypatch.setattr(cache, "_effective_uid", lambda: 0)
    monkeypatch.setattr(
        cache, "_copy_database", lambda *_args: (_ for _ in ()).throw(OSError("partial"))
    )
    monkeypatch.setenv(cache.CACHE_REFERENCE_ENV, "f" * 64)

    with pytest.raises(OSError, match="partial"):
        cache.build_provider_runtime_cache(
            runtime,
            source_commit=_source_commit(),
            release_bundle_digest=_bundle_digest(),
            runtime_configuration_digest=load_runtime_configuration(PROVIDER_CONFIG).digest,
            image_build_preparation_seconds=0.0,
        )

    assert cache.CACHE_REFERENCE_ENV not in os.environ
    assert not cache_root.exists()
    assert not list(tmp_path.glob(".failed-cache.building-*"))


@pytest.mark.parametrize("configured", [None, "", "/tmp/foreign-runtime.json"])
def test_fixed_image_boundary_rejects_missing_empty_and_foreign_runtime_config_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    configured: str | None,
) -> None:
    import baseball_rag.provider_runtime_cache as cache
    import baseball_rag.query.runtime as query_runtime

    monkeypatch.setattr(cache, "_CACHE_ROOT", tmp_path / "absent-provider-cache")
    monkeypatch.setattr(cache, "_IMAGE_BUNDLE_ROOT", BUNDLE)
    monkeypatch.setattr(cache, "_IMAGE_RUNTIME_CONFIG", PROVIDER_CONFIG)
    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid())
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    if configured is None:
        monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    else:
        monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", configured)
    monkeypatch.setattr(
        query_runtime,
        "_runtime_for",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("fixed provider image must not reconstruct the full runtime")
        ),
    )
    _published_provider_runtime.cache_clear()

    assert cache.provider_image_boundary_detected() is True
    with pytest.raises(cache.ProviderRuntimeCacheError):
        cache.require_provider_image_boundary()
    with pytest.raises(cache.ProviderRuntimeCacheError):
        published_data_runtime()
    assert _execute(ExecutionRequest("query", "40-40", None)) == {"kind": "failed"}
    assert _execute(ExecutionRequest("unsupported", "anything", None)) == {"kind": "failed"}


def test_corrupt_fixed_image_cache_is_provider_mode_and_never_reconstructed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import baseball_rag.provider_runtime_cache as cache
    import baseball_rag.query.runtime as query_runtime

    corrupt = tmp_path / "provider-runtime-cache"
    corrupt.mkdir()
    (corrupt / "pointer.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(cache, "_CACHE_ROOT", corrupt)
    monkeypatch.setattr(cache, "_IMAGE_BUNDLE_ROOT", BUNDLE)
    monkeypatch.setattr(cache, "_IMAGE_RUNTIME_CONFIG", PROVIDER_CONFIG)
    monkeypatch.setattr(cache, "_REQUIRED_OWNER_UID", os.geteuid())
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(PROVIDER_CONFIG))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.setattr(
        query_runtime,
        "_runtime_for",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("corrupt provider cache must not reconstruct the full runtime")
        ),
    )
    _published_provider_runtime.cache_clear()

    assert cache.provider_image_boundary_detected() is True
    with pytest.raises(cache.ProviderRuntimeCacheError):
        cache.require_provider_image_boundary()
    with pytest.raises(cache.ProviderRuntimeCacheError):
        published_data_runtime()


@pytest.mark.parametrize("kind", ["cache-root", "pointer", "release-root", "runtime-config"])
def test_fixed_image_boundary_rejects_symlinks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
) -> None:
    import baseball_rag.provider_runtime_cache as cache

    cache_root, _ = _prepare_cache(monkeypatch, tmp_path)
    image_bundle = BUNDLE
    image_config = PROVIDER_CONFIG
    if kind == "cache-root":
        real_root = tmp_path / "real-cache"
        cache_root.rename(real_root)
        cache_root.symlink_to(real_root, target_is_directory=True)
    elif kind == "pointer":
        pointer = cache_root / "pointer.json"
        os.chmod(cache_root, 0o755)
        pointer.unlink()
        pointer.symlink_to(PROVIDER_CONFIG)
        os.chmod(cache_root, 0o555)
    elif kind == "release-root":
        image_bundle = tmp_path / "release-bundle-link"
        image_bundle.symlink_to(BUNDLE, target_is_directory=True)
    else:
        image_config = tmp_path / "runtime-link.json"
        image_config.symlink_to(PROVIDER_CONFIG)
    monkeypatch.setattr(cache, "_CACHE_ROOT", cache_root)
    monkeypatch.setattr(cache, "_IMAGE_BUNDLE_ROOT", image_bundle)
    monkeypatch.setattr(cache, "_IMAGE_RUNTIME_CONFIG", image_config)
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(image_bundle))
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(image_config))

    assert cache.provider_image_boundary_detected() is True
    with pytest.raises(cache.ProviderRuntimeCacheError):
        cache.require_provider_image_boundary()


def test_provider_runtime_rejects_arbitrary_bundle_and_configuration_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from baseball_rag.query.runtime import PublishedDataUnavailableError

    foreign_config = tmp_path / "runtime.json"
    foreign_config.write_bytes(PROVIDER_CONFIG.read_bytes())
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(foreign_config))
    _published_provider_runtime.cache_clear()

    with pytest.raises(PublishedDataUnavailableError, match="fixed image paths"):
        published_data_runtime()
    assert _execute(ExecutionRequest("unsupported", "anything", None)) == {"kind": "failed"}


def test_local_ci_ignores_fixed_provider_cache_and_keeps_full_bundle_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import baseball_rag.query.runtime as query_runtime

    observed: list[Path | str] = []
    original = query_runtime.check_release_bundle

    def recording(path, **kwargs):
        observed.append(path)
        return original(path, **kwargs)

    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.setenv(
        "GROUNDBALL_RUNTIME_CONFIG", str(ROOT / "release/config/local-ci-runtime.json")
    )
    monkeypatch.setenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", "f" * 64)
    monkeypatch.setattr(query_runtime, "check_release_bundle", recording)
    _published_provider_runtime.cache_clear()

    assert published_data_runtime().connection is not None
    assert observed == [str(BUNDLE)]
