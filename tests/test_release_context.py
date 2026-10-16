"""One explicit release identity, independent of module import order or environment."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from baseball_rag import release_context as contexts
from baseball_rag.release_bundle import ReleaseBundleError, check_release_bundle

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_context(monkeypatch):
    monkeypatch.setattr(contexts, "_installed_context", None)
    monkeypatch.delenv("GROUNDBALL_RELEASE_BUNDLE", raising=False)


def context():
    import json

    bundle = ROOT / "release/bundle"
    identity = check_release_bundle(bundle)
    source = json.loads(identity.manifest_path.read_text())["source_commit"]
    return contexts.ReleaseContext(
        bundle, expected_source_commit=source, expected_digest=identity.digest
    )


def test_context_is_verified_frozen_and_snapshot_bound():
    release = context()
    assert release.catalog_dir.parents[3] == release.bundle_root
    assert release.data_dir == release.bundle_root / "data"
    assert release.coverage_report_path.is_file()
    assert release.bundle_root != ROOT / "release/bundle"
    with pytest.raises(FrozenInstanceError):
        release.source_commit = "b" * 40
    with pytest.raises(ReleaseBundleError, match="digest"):
        contexts.ReleaseContext(
            ROOT / "release/bundle",
            expected_source_commit=release.source_commit,
            expected_digest="0" * 64,
        )


def test_registry_import_and_prior_local_cache_do_not_capture_release(monkeypatch, tmp_path):
    from baseball_rag.query import registry
    from baseball_rag.query.coverage import load_coverage_report

    (tmp_path / "published_catalog.json").write_text(
        '{"catalog_revision":"local-only-before-activation"}'
    )
    monkeypatch.setattr(registry, "CATALOG_DIR", tmp_path)
    assert registry.catalog_revision() == "local-only-before-activation"
    release = context()
    contexts.install_release_context(release)
    assert registry.catalog_directory() == release.catalog_dir
    assert registry.catalog_revision() != "local-only-before-activation"
    assert load_coverage_report()["proof_id"] == release.coverage_proof_id
    monkeypatch.setenv("GROUNDBALL_RELEASE_BUNDLE", "/untrusted/replacement")
    assert contexts.configured_release_context() is release
    assert registry.catalog_directory() == release.catalog_dir


def test_process_context_cannot_be_replaced():
    release = context()
    contexts.install_release_context(release)
    contexts.install_release_context(release)
    # A distinct object, even with identical pins, is not another activation.
    other = context()
    with pytest.raises(ReleaseBundleError, match="already installed"):
        contexts.install_release_context(other)


def test_imports_do_not_read_configured_bundle(tmp_path):
    import os
    import subprocess
    import sys

    selected = dict(os.environ)
    selected["GROUNDBALL_RELEASE_BUNDLE"] = str(tmp_path / "not-a-bundle")
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import baseball_rag.public_app; "
            "import baseball_rag.query.registry; import baseball_rag.query.coverage; "
            "import baseball_rag.release_runtime",
        ],
        env=selected,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_rejects_catalog_data_or_fingerprint_mismatch(monkeypatch):
    from dataclasses import replace

    from baseball_rag.query import runtime as runtimes

    monkeypatch.setattr(runtimes, "_installed_runtime", None)
    release = context()
    runtime = runtimes.create_published_data_runtime(release)
    try:
        for foreign in (
            replace(runtime, data_dir=ROOT / "release/bundle/data"),
            replace(runtime, source_fingerprints={}),
            replace(runtime, release_context=None),
        ):
            with pytest.raises(runtimes.PublishedDataUnavailableError, match="ReleaseContext"):
                runtimes.install_published_data_runtime(foreign, context=release)
        runtimes.install_published_data_runtime(runtime, context=release)
        assert runtimes.published_data_runtime(release) is runtime
    finally:
        runtime.connection.close()


def test_activation_during_local_construction_never_returns_mixed_snapshot(monkeypatch):
    from baseball_rag.query import runtime as runtimes

    release = context()
    original = runtimes._safe_asset
    selected = False

    def activate_at_manifest(root, name):
        nonlocal selected
        if not selected and name == "manifest.json":
            selected = True
            contexts.install_release_context(release)
        return original(root, name)

    monkeypatch.setattr(runtimes, "_safe_asset", activate_at_manifest)
    with pytest.raises(runtimes.PublishedDataUnavailableError, match="changed during"):
        runtimes._load_runtime(str(ROOT / "release/bundle/data"))


def test_warm_local_runtime_cache_cannot_bypass_release_selection(monkeypatch):
    from baseball_rag.query import runtime as runtimes

    monkeypatch.setattr(runtimes, "_installed_runtime", None)
    local_data = ROOT / "release/bundle/data"
    runtimes._runtime_for(str(local_data))
    contexts.install_release_context(context())
    with pytest.raises(runtimes.PublishedDataUnavailableError, match="outside"):
        runtimes._runtime_for(str(local_data))


def test_context_factory_normalizes_path_type_and_serializes_first_construction():
    from concurrent.futures import ThreadPoolExecutor

    bundle = ROOT / "release/bundle"
    release = context()
    pins = {
        "expected_source_commit": release.source_commit,
        "expected_digest": release.release_bundle_digest,
    }
    with ThreadPoolExecutor(max_workers=4) as pool:
        selected = list(
            pool.map(
                lambda path: contexts.verified_release_context(path, **pins),
                [bundle, str(bundle), bundle, str(bundle)],
            )
        )
    assert all(value is selected[0] for value in selected)
