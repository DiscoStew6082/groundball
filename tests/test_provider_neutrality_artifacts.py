import importlib.util
import io
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


def test_nested_archive_member_fails_closed_without_exposing_payload(
    tmp_path: Path,
) -> None:
    nested = io.BytesIO()
    with zipfile.ZipFile(nested, "w") as archive:
        archive.writestr("config.txt", "https://" + "private.invalid/secret\n")
    wheel = tmp_path / "package.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("payload.zip", nested.getvalue())

    assert scan(tmp_path) == (
        Finding("package.whl!payload.zip", 1, "unscanned-content", "<redacted>"),
    )


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
