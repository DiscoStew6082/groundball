import importlib.util
import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

_MODULE_PATH = Path("scripts/check_provider_neutrality.py")
_SPEC = importlib.util.spec_from_file_location("provider_neutrality_final_bypasses", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError("scanner module could not be loaded")
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MODULE
_SPEC.loader.exec_module(_MODULE)
Finding = _MODULE.Finding
scan = _MODULE.scan
_HTTP = "http" + "://"
_HTTPS = "https" + "://"


def _manifest_bytes(size: int | None = None) -> bytes:
    payload = b"services:\n  app:\n    image: ground-ball:latest\n    ports:\n      - 8000\n"
    if size is None:
        return payload
    assert len(payload) < size
    return payload + b"#" * (size - len(payload))


def test_deployment_manifest_paths_are_rejected_at_every_archive_depth(
    tmp_path: Path,
) -> None:
    (tmp_path / "deployment.yaml").write_bytes(_manifest_bytes(70_069))
    nested = io.BytesIO()
    with tarfile.open(fileobj=nested, mode="w:gz") as archive:
        payload = _manifest_bytes()
        member = tarfile.TarInfo("deployment.yaml")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    with zipfile.ZipFile(tmp_path / "package.whl", "w") as archive:
        archive.writestr("deployment.yaml", _manifest_bytes())
        archive.writestr("payload.tar.gz", nested.getvalue())

    assert scan(tmp_path) == (
        Finding("deployment.yaml", 1, "deployment-manifest", "<redacted>"),
        Finding("package.whl!deployment.yaml", 1, "deployment-manifest", "<redacted>"),
        Finding(
            "package.whl!payload.tar.gz!deployment.yaml",
            1,
            "deployment-manifest",
            "<redacted>",
        ),
    )


@pytest.mark.parametrize(
    "name",
    [
        "deployment.yaml.txt",
        "deployment.yml.bak",
        "deployment-json.yaml",
        "deploy.yaml",
    ],
)
def test_deployment_manifest_path_near_misses_are_not_classified(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_bytes(_manifest_bytes())

    assert scan(tmp_path) == ()


@pytest.mark.parametrize(
    "url",
    [
        _HTTP + "0.0.0.0:80/",
        _HTTP + "0.0.0.0/private",
        _HTTP + "0.0.0.0:81/private",
        _HTTPS + "0.0.0.0:443/private",
        _HTTPS + "0.0.0.0:80",
        _HTTP + "0.0.0.0",
        _HTTP + "user@0.0.0.0:80",
        _HTTP + "user:pass@0.0.0.0:80",
        _HTTP + "0.0.0.0:80?private=1",
        _HTTP + "0.0.0.0:80#private",
        _HTTP + "0.0.0.0:80.evil.invalid",
        _HTTP + "0.0.0.0.evil.invalid:80",
        _HTTP + "[::1]:80",
        _HTTP + "10.0.0.1:80",
        _HTTP + "192.168.1.1:80",
        _HTTP + "private.invalid:80",
    ],
)
def test_only_exact_uvicorn_bind_url_receives_local_allowance(tmp_path: Path, url: str) -> None:
    (tmp_path / "container.log").write_text(url + "\n", encoding="utf-8")

    assert scan(tmp_path) == (Finding("container.log", 1, "nonpublic-url", "<redacted>"),)


def test_exact_uvicorn_bind_and_bounded_local_urls_are_allowed(tmp_path: Path) -> None:
    (tmp_path / "container.log").write_text(
        "INFO: Uvicorn running on http://0.0.0.0:80 (Press CTRL+C to quit)\n"
        "https://example.com/public\n"
        "http://localhost:8000/local\n"
        "http://127.0.0.1:8000/local\n",
        encoding="utf-8",
    )

    assert scan(tmp_path) == ()
