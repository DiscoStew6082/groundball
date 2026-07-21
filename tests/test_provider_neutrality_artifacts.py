import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

_MODULE_PATH = Path("scripts/check_provider_neutrality.py")
_SPEC = importlib.util.spec_from_file_location("provider_neutrality_artifacts", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("scanner module could not be loaded")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
CHUNK_BYTES = _MODULE.CHUNK_BYTES
Finding = _MODULE.Finding
main = _MODULE.main
scan = _MODULE.scan


def test_large_text_is_stream_scanned_across_chunk_boundaries(tmp_path: Path) -> None:
    prefix = b"x" * (CHUNK_BYTES - 4)
    (tmp_path / "large.txt").write_bytes(
        prefix + b"https://" + b"concrete-host.invalid/container\n" + b"x" * CHUNK_BYTES
    )

    assert [(item.path, item.rule_id) for item in scan(tmp_path)] == [
        ("large.txt", "nonpublic-url")
    ]


def test_url_free_generic_deployment_manifest_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "deployment.yaml").write_text(
        "services:\n  app:\n    image: ground-ball:latest\n    ports:\n      - 8000\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == (Finding("deployment.yaml", 1, "deployment-manifest", "<redacted>"),)


def test_deployment_named_document_without_service_image_port_shape_is_allowed(
    tmp_path: Path,
) -> None:
    (tmp_path / "deployment.yaml").write_text(
        "title: Deployment guide\nsteps:\n  - build an image\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == ()


def test_generic_hosted_container_manifest_is_rejected_without_provider_policy(
    tmp_path: Path,
) -> None:
    (tmp_path / "deployment.json").write_text(
        '{"container":{"health":"https://' + "concrete-host.invalid/health" + '"}}\n',
        encoding="utf-8",
    )

    assert scan(tmp_path) == (Finding("deployment.json", 1, "nonpublic-url", "<redacted>"),)


def test_top_level_wheel_and_tar_members_are_scanned(tmp_path: Path) -> None:
    wheel = tmp_path / "package.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("package/config.txt", "https://" + "private.invalid/config\n")
    tar_path = tmp_path / "package.tar.xz"
    payload = b"https://" + b"private.invalid/archive\n"
    with tarfile.open(tar_path, "w:xz") as archive:
        member = tarfile.TarInfo("package/config.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))

    assert [(item.path, item.rule_id) for item in scan(tmp_path)] == [
        ("package.tar.xz!package/config.txt", "nonpublic-url"),
        ("package.whl!package/config.txt", "nonpublic-url"),
    ]


def _nested_wheel(path: Path, name: str, payload: bytes) -> None:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr(name, payload)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("payload.zip", nested.getvalue())


def test_safe_nested_archive_scans_clean(tmp_path: Path) -> None:
    _nested_wheel(tmp_path / "package.whl", "README.txt", b"safe release payload\n")

    assert scan(tmp_path) == ()


def test_nested_archive_private_url_is_detected_without_exposing_payload(
    tmp_path: Path,
) -> None:
    _nested_wheel(
        tmp_path / "package.whl",
        "config.txt",
        b"https://" + b"private.invalid/secret\n",
    )

    assert scan(tmp_path) == (
        Finding(
            "package.whl!payload.zip!config.txt",
            1,
            "nonpublic-url",
            "<redacted>",
        ),
    )


@pytest.mark.parametrize(
    ("suffix", "mode"), [(".tar", "w"), (".tar.gz", "w:gz"), (".tgz", "w:gz"), (".tar.xz", "w:xz")]
)
def test_supported_nested_tar_archives_scan_clean(tmp_path: Path, suffix: str, mode: str) -> None:
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode=mode) as archive:
        member = tarfile.TarInfo("README.txt")
        member.size = len(b"safe release payload\n")
        archive.addfile(member, io.BytesIO(b"safe release payload\n"))
    with zipfile.ZipFile(tmp_path / "package.whl", "w") as archive:
        archive.writestr("payload" + suffix, nested.getvalue())

    assert scan(tmp_path) == ()


def test_nested_archive_forbidden_literal_is_detected_and_redacted(tmp_path: Path) -> None:
    forbidden = "credential-" + "literal"
    _nested_wheel(tmp_path / "package.whl", "config.txt", (forbidden + "\n").encode())
    policy = tmp_path / "policy.json"
    policy.write_bytes(
        (
            json.dumps(
                {
                    "exact_rules": [{"rule_id": "private.credential", "value": forbidden}],
                    "glob_rules": [],
                    "schema_version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
    )

    assert scan(tmp_path, deny_policy=policy) == (
        Finding(
            "package.whl!payload.zip!config.txt",
            1,
            "private.credential",
            "<redacted>",
        ),
    )


def test_nested_archives_fail_closed_on_unsafe_corrupt_unsupported_and_depth(
    tmp_path: Path,
) -> None:
    unsafe = io.BytesIO()
    with zipfile.ZipFile(unsafe, "w") as archive:
        archive.writestr("../escape.txt", "clean\n")
    deep = io.BytesIO()
    with zipfile.ZipFile(deep, "w") as archive:
        archive.writestr("deeper.zip", unsafe.getvalue())
    encrypted = bytearray(deep.getvalue())
    encrypted[encrypted.index(b"PK\x01\x02") + 8] |= 1
    wheel = tmp_path / "package.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("unsafe.zip", unsafe.getvalue())
        archive.writestr("corrupt.zip", b"not a zip")
        archive.writestr("unsupported.tar.bz2", b"not inspected")
        archive.writestr("deep.zip", deep.getvalue())
        archive.writestr("encrypted.zip", encrypted)

    assert [(item.path, item.rule_id) for item in scan(tmp_path)] == [
        ("package.whl!corrupt.zip", "unscanned-content"),
        ("package.whl!deep.zip!deeper.zip", "unscanned-content"),
        ("package.whl!encrypted.zip!deeper.zip", "unscanned-content"),
        ("package.whl!unsafe.zip!<unsafe-member>", "unscanned-content"),
        ("package.whl!unsupported.tar.bz2", "unscanned-content"),
    ]


def test_nested_archive_size_limit_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _nested_wheel(tmp_path / "package.whl", "README.txt", b"safe\n")
    monkeypatch.setattr(_MODULE, "MAX_NESTED_ARCHIVE_BYTES", 1)

    assert scan(tmp_path) == (
        Finding("package.whl!payload.zip", 1, "unscanned-content", "<redacted>"),
    )


@pytest.mark.release_proof
def test_uv_build_wheel_and_sdist_scan_clean_under_generic_policy() -> None:
    dist = Path("dist")
    shutil.rmtree(dist, ignore_errors=True)
    try:
        subprocess.run(["uv", "build"], check=True)
        names = sorted(path.name for path in dist.iterdir())
        assert any(name.endswith(".whl") for name in names)
        assert any(name.endswith(".tar.gz") for name in names)
        assert main(["--root", ".", "--artifact", "dist"]) == 0
    finally:
        shutil.rmtree(dist, ignore_errors=True)


def test_artifact_count_and_path_bounds(tmp_path: Path) -> None:
    large = tmp_path / "large.txt"
    large.write_text("clean\n", encoding="utf-8")
    with pytest.raises(ValueError, match="at most 16"):
        scan(tmp_path, artifacts=tuple(tmp_path / f"a-{index}" for index in range(17)))
    missing = tmp_path / "missing"
    with pytest.raises(ValueError, match="invalid artifact"):
        scan(tmp_path, artifacts=(missing,))
    missing.symlink_to(large)
    with pytest.raises(ValueError, match="invalid artifact"):
        scan(tmp_path, artifacts=(missing,))
