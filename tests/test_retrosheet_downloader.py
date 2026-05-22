"""Tests for the Retrosheet secondary-source data worker."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

from baseball_rag.db.secondary_sources import retrosheet


def _zip_bytes(member_name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.status_code = 200
        self.content = content

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.content]


def test_download_retrosheet_sources_fetches_required_archives_and_writes_manifest(tmp_path):
    archives = {
        "batting.zip": _zip_bytes(
            "batting.csv",
            "gid,stattype,gametype,b_pa\n"
            "NYA192704180,value,regular,4\n"
            "NYA192710050,value,playoff,4\n",
        ),
        "pitching.zip": _zip_bytes(
            "pitching.csv",
            "gid,stattype,gametype,p_ipouts\nNYA192704180,value,regular,27\n",
        ),
        "fielding.zip": _zip_bytes(
            "fielding.csv",
            "gid,stattype,gametype,d_po\nNYA192704180,value,regular,3\n",
        ),
        "biodata.zip": _zip_bytes(
            "biofile0.csv",
            "id,name_first,name_last\nruthb101,Babe,Ruth\n",
        ),
    }
    requested_urls: list[str] = []

    def fake_get(url: str, timeout: int) -> _FakeResponse:
        requested_urls.append(url)
        return _FakeResponse(archives[url.rsplit("/", 1)[-1]])

    manifest_path = retrosheet.download_all(
        tmp_path,
        http_get=fake_get,
        downloaded_at="2026-05-14T10:11:12-04:00",
    )

    assert [url.rsplit("/", 1)[-1] for url in requested_urls] == [
        "batting.zip",
        "pitching.zip",
        "fielding.zip",
        "biodata.zip",
    ]
    assert (tmp_path / "batting.csv").exists()
    assert (tmp_path / "pitching.csv").exists()
    assert (tmp_path / "fielding.csv").exists()
    assert (tmp_path / "biofile0.csv").exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["download"]["downloaded_at"] == "2026-05-14T10:11:12-04:00"
    assert "Retrosheet" in manifest["dataset"]["attribution"]
    assert manifest["files"][0]["source_url"].endswith("/batting.zip")
    assert manifest["files"][0]["rows"] == 2
    assert manifest["files"][0]["year_coverage"] == {"min": 1927, "max": 1927}
    assert len(manifest["files"][0]["sha256"]) == 64
