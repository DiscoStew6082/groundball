"""Strict process-local provider runtime-cache contracts."""

from __future__ import annotations

import hashlib
import json
import os
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
    manifest = json.loads((BUNDLE / "release-manifest.json").read_text(encoding="utf-8"))
    return str(manifest["source_commit"])


def _prepare_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Path, str]:
    import baseball_rag.provider_runtime_cache as runtime_cache

    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    monkeypatch.delenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", raising=False)
    _published_provider_runtime.cache_clear()
    runtime = published_data_runtime()
    configuration = load_runtime_configuration(PROVIDER_CONFIG)
    cache_root = tmp_path / "groundball-provider-cache-v1"
    monkeypatch.setattr(runtime_cache, "_CACHE_ROOT", cache_root)
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(PROVIDER_CONFIG))
    reference = runtime_cache.prepare_provider_runtime_cache(
        runtime,
        source_commit=_source_commit(),
        release_bundle_digest=hashlib.sha256(
            (BUNDLE / "release-manifest.json").read_bytes()
        ).hexdigest(),
        runtime_configuration_digest=configuration.digest,
    )
    _published_provider_runtime.cache_clear()
    return cache_root, reference


def _rewrite_metadata(cache_root: Path, reference: str, mutate) -> str:
    cache_dir = cache_root / reference
    metadata_path = cache_dir / "metadata.json"
    os.chmod(cache_dir, 0o700)
    os.chmod(metadata_path, 0o600)
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    mutate(metadata)
    content = canonical_json_bytes(metadata)
    metadata_path.write_bytes(content)
    os.chmod(metadata_path, 0o400)
    os.chmod(cache_dir, 0o500)
    changed_reference = hashlib.sha256(content).hexdigest()
    cache_dir.rename(cache_root / changed_reference)
    os.environ["GROUNDBALL_PROVIDER_RUNTIME_CACHE"] = changed_reference
    _published_provider_runtime.cache_clear()
    return changed_reference


def test_verified_runtime_cache_returns_the_exact_normal_40_40_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as runtime_cache
    from baseball_rag.provider_runtime_cache import prepare_provider_runtime_cache

    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    monkeypatch.delenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", raising=False)
    _runtime_for.cache_clear()
    normal = _execute(ExecutionRequest("query", "40-40", None))
    runtime = published_data_runtime()

    configuration = load_runtime_configuration(PROVIDER_CONFIG)
    monkeypatch.setattr(runtime_cache, "_CACHE_ROOT", tmp_path / "groundball-provider-cache-v1")
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(PROVIDER_CONFIG))
    reference = prepare_provider_runtime_cache(
        runtime,
        source_commit=_source_commit(),
        release_bundle_digest=hashlib.sha256(
            (BUNDLE / "release-manifest.json").read_bytes()
        ).hexdigest(),
        runtime_configuration_digest=configuration.digest,
    )
    _published_provider_runtime.cache_clear()

    cached = _execute(ExecutionRequest("query", "40-40", None))
    metadata = json.loads(
        (tmp_path / "groundball-provider-cache-v1" / reference / "metadata.json").read_text(
            encoding="utf-8"
        )
    )

    assert cached == normal
    assert set(metadata["data_manifest"]) == {"dataset", "files"}
    assert set(metadata["data_manifest"]["dataset"]) == {"release_id"}
    assert "downloaded_at" not in json.dumps(metadata)


def test_protected_worker_missing_cache_fails_instead_of_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROUNDBALL_RUNTIME_CONFIG", str(PROVIDER_CONFIG))
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", raising=False)
    _runtime_for.cache_clear()

    outcome = _execute(ExecutionRequest("query", "40-40", None))
    subprocess_outcome = SubprocessExecutionRunner().run(
        ExecutionRequest("query", "40-40", None), timeout_seconds=10
    )

    assert outcome == {"kind": "failed"}
    assert subprocess_outcome.kind == "failed"
    assert subprocess_outcome.detail == "Public Query Run execution failed."
    assert "cache" not in repr(subprocess_outcome).lower()


def test_cache_rejects_a_missing_required_relation_even_with_rehashed_metadata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from baseball_rag.provider_runtime_cache import ProviderRuntimeCacheError

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    _rewrite_metadata(cache_root, reference, lambda value: value["required_relations"].pop())

    with pytest.raises(ProviderRuntimeCacheError, match="relation"):
        published_data_runtime()


def test_cached_structured_recipe_and_retrosheet_payloads_match_normal_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    structured = {
        "source": "Batting",
        "grain": "player-season",
        "selections": ["player.name", "season", "batting.HR", "pitching.W"],
        "predicate": {
            "kind": "compare",
            "value": "player.name",
            "operator": "equals",
            "literal": "Shohei Ohtani",
        },
        "ranking": {
            "value": "pitching.W",
            "direction": "highest",
            "count": 1,
            "tie_policy": "include_ties",
            "within": [],
        },
    }
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    monkeypatch.delenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", raising=False)
    _published_provider_runtime.cache_clear()
    normal_structured = _execute(ExecutionRequest("query", None, structured))
    normal_retrosheet = _execute(
        ExecutionRequest(
            "retrosheet",
            "how many times did Nolan Ryan strike out the side in his career",
            None,
        )
    )
    _prepare_cache(monkeypatch, tmp_path)

    cached_structured = _execute(ExecutionRequest("query", None, structured))
    cached_retrosheet = _execute(
        ExecutionRequest(
            "retrosheet",
            "how many times did Nolan Ryan strike out the side in his career",
            None,
        )
    )

    assert cached_structured == normal_structured
    assert cached_retrosheet == normal_retrosheet


def test_cached_child_never_rechecks_bundle_rebuilds_csv_or_fingerprints(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_cache(monkeypatch, tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("expensive verified parent path reached cached child")

    monkeypatch.setattr("baseball_rag.query.runtime.check_release_bundle", forbidden)
    monkeypatch.setattr("baseball_rag.query.runtime._runtime_for", forbidden)
    monkeypatch.setattr("baseball_rag.query.runtime._verify_packaged_asset", forbidden)
    monkeypatch.setattr("baseball_rag.query.runtime._source_fingerprint", forbidden)
    _published_provider_runtime.cache_clear()

    outcome = _execute(ExecutionRequest("query", "40-40", None))

    assert outcome["kind"] == "completed"


def test_cached_database_connection_is_read_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prepare_cache(monkeypatch, tmp_path)
    runtime = published_data_runtime()

    with pytest.raises(duckdb.Error):
        runtime.connection.execute("CREATE TABLE forbidden_write(value INTEGER)")


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.__setitem__("unknown", True), "shape"),
        (lambda value: value.__setitem__("database_sha256", "bad"), "digest"),
        (lambda value: value.__setitem__("database_size_bytes", "1"), "values"),
        (
            lambda value: value.__setitem__(
                "database_size_bytes", value["database_size_bytes"] + 1
            ),
            "invalid",
        ),
        (lambda value: value.__setitem__("source_commit", "9" * 40), "identity"),
        (lambda value: value.__setitem__("release_bundle_digest", "8" * 64), "identity"),
        (lambda value: value.__setitem__("runtime_configuration_digest", "7" * 64), "identity"),
        (
            lambda value: value["required_relations"].append("unexpected_relation"),
            "relation",
        ),
    ],
    ids=[
        "unknown-sidecar-field",
        "malformed-digest",
        "malformed-size",
        "mismatched-size",
        "stale-source",
        "foreign-bundle",
        "wrong-runtime-config",
        "extra-relation",
    ],
)
def test_cache_rejects_strict_metadata_mutations(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutation, match: str
) -> None:
    from baseball_rag.provider_runtime_cache import ProviderRuntimeCacheError

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    _rewrite_metadata(cache_root, reference, mutation)

    with pytest.raises(ProviderRuntimeCacheError, match=match):
        published_data_runtime()


@pytest.mark.parametrize("partial", [False, True], ids=["missing", "partial"])
def test_cache_rejects_missing_or_partial_sidecar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, partial: bool
) -> None:
    from baseball_rag.provider_runtime_cache import ProviderRuntimeCacheError

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    cache_dir = cache_root / reference
    metadata = cache_dir / "metadata.json"
    os.chmod(cache_dir, 0o700)
    if partial:
        os.chmod(metadata, 0o600)
        metadata.write_bytes(b'{"schema_version":')
        os.chmod(metadata, 0o400)
    else:
        metadata.unlink()
    os.chmod(cache_dir, 0o500)
    _published_provider_runtime.cache_clear()

    with pytest.raises(ProviderRuntimeCacheError, match="invalid"):
        published_data_runtime()


@pytest.mark.parametrize(
    ("target", "mode"),
    [("runtime.duckdb", 0o600), ("metadata.json", 0o440)],
    ids=["writable-database", "bad-sidecar-mode"],
)
def test_cache_rejects_nonminimal_final_file_modes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str, mode: int
) -> None:
    from baseball_rag.provider_runtime_cache import ProviderRuntimeCacheError

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    cache_dir = cache_root / reference
    os.chmod(cache_dir, 0o700)
    os.chmod(cache_dir / target, mode)
    os.chmod(cache_dir, 0o500)
    _published_provider_runtime.cache_clear()

    with pytest.raises(ProviderRuntimeCacheError, match="file"):
        published_data_runtime()


def test_cache_rejects_symlink_and_wrong_owner_seam(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as runtime_cache

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    cache_dir = cache_root / reference
    database = cache_dir / "runtime.duckdb"
    os.chmod(cache_dir, 0o700)
    database.unlink()
    database.symlink_to(BUNDLE / "release-manifest.json")
    os.chmod(cache_dir, 0o500)
    _published_provider_runtime.cache_clear()
    with pytest.raises(runtime_cache.ProviderRuntimeCacheError, match="file"):
        published_data_runtime()

    monkeypatch.setattr(runtime_cache, "_effective_uid", lambda: os.geteuid() + 1)
    _published_provider_runtime.cache_clear()
    with pytest.raises(runtime_cache.ProviderRuntimeCacheError, match="location"):
        published_data_runtime()


def test_cache_rejects_changed_database_bytes_and_user_controlled_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from baseball_rag.provider_runtime_cache import ProviderRuntimeCacheError

    cache_root, reference = _prepare_cache(monkeypatch, tmp_path)
    cache_dir = cache_root / reference
    database = cache_dir / "runtime.duckdb"
    os.chmod(cache_dir, 0o700)
    os.chmod(database, 0o600)
    with database.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        final = stream.read(1)
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes([final[0] ^ 1]))
    os.chmod(database, 0o400)
    os.chmod(cache_dir, 0o500)
    _published_provider_runtime.cache_clear()
    with pytest.raises(ProviderRuntimeCacheError, match="invalid"):
        published_data_runtime()

    monkeypatch.setenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", "/tmp/user-selected.duckdb")
    _published_provider_runtime.cache_clear()
    with pytest.raises(ProviderRuntimeCacheError, match="digest"):
        published_data_runtime()


def test_local_ci_ignores_cache_reference_and_keeps_full_bundle_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import baseball_rag.query.runtime as query_runtime

    observed: list[Path | str] = []
    original_check = query_runtime.check_release_bundle

    def recording_check(path):
        observed.append(path)
        return original_check(path)

    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.setenv(
        "GROUNDBALL_RUNTIME_CONFIG", str(ROOT / "release/config/local-ci-runtime.json")
    )
    monkeypatch.setenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", "f" * 64)
    monkeypatch.setattr(query_runtime, "check_release_bundle", recording_check)
    _published_provider_runtime.cache_clear()

    runtime = published_data_runtime()

    assert runtime.connection is not None
    assert observed == [str(BUNDLE)]


def test_failed_cache_build_publishes_nothing_and_removes_partial_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import baseball_rag.provider_runtime_cache as runtime_cache

    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", str(BUNDLE))
    monkeypatch.setenv("GROUNDBALL_SOURCE_COMMIT", _source_commit())
    monkeypatch.delenv("GROUNDBALL_RUNTIME_CONFIG", raising=False)
    monkeypatch.setenv("GROUNDBALL_PROVIDER_RUNTIME_CACHE", "f" * 64)
    _published_provider_runtime.cache_clear()
    runtime = published_data_runtime()
    configuration = load_runtime_configuration(PROVIDER_CONFIG)
    cache_root = tmp_path / "failed-cache"
    monkeypatch.setattr(runtime_cache, "_CACHE_ROOT", cache_root)
    monkeypatch.setattr(
        runtime_cache,
        "_copy_database",
        lambda *_args: (_ for _ in ()).throw(OSError("sensitive partial failure")),
    )

    with pytest.raises(OSError, match="partial failure"):
        runtime_cache.prepare_provider_runtime_cache(
            runtime,
            source_commit=_source_commit(),
            release_bundle_digest=hashlib.sha256(
                (BUNDLE / "release-manifest.json").read_bytes()
            ).hexdigest(),
            runtime_configuration_digest=configuration.digest,
        )

    assert "GROUNDBALL_PROVIDER_RUNTIME_CACHE" not in os.environ
    assert list(cache_root.iterdir()) == []
