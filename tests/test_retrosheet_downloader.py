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


def test_retrosheet_manifest_reads_zip_members_and_preserves_derived_entries(tmp_path):
    archives = {
        "batting.zip": _zip_bytes(
            "batting.csv",
            "gid,stattype,gametype,date,b_sb\nOAK196906100,value,regular,19690610,1\n",
        ),
        "pitching.zip": _zip_bytes(
            "pitching.csv",
            "gid,stattype,gametype,date,p_ipouts\nOAK196906100,value,regular,19690610,27\n",
        ),
        "fielding.zip": _zip_bytes(
            "fielding.csv",
            "gid,stattype,gametype,date,d_po\nOAK196906100,value,regular,19690610,3\n",
        ),
        "biodata.zip": _zip_bytes(
            "biofile0.csv",
            "id,name_first,name_last\ncampb101,Bert,Campaneris\n",
        ),
    }
    for archive_name, content in archives.items():
        (tmp_path / archive_name).write_bytes(content)
    (tmp_path / "batting.csv").write_text(
        "gid,stattype,gametype,date,b_sb\n"
        "OAK190006100,value,regular,19000610,0\n"
        "OAK190006110,value,regular,19000611,0\n",
        encoding="utf-8",
    )
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": (
                            "data/secondary_sources/retrosheet/pitcher_strikeout_side_events.csv"
                        ),
                        "table": "retrosheet_pitcher_strikeout_side_events",
                        "rows": 1,
                        "year_coverage": {"min": 1969, "max": 1969},
                        "sha256": "abc",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    manifest_path = retrosheet.write_manifest(
        tmp_path,
        downloaded_at="2026-07-03T15:00:00-04:00",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tables = {item["table"]: item for item in manifest["files"]}
    assert tables["retrosheet_batting"]["path"].endswith("batting.zip")
    assert tables["retrosheet_batting"]["rows"] == 1
    assert tables["retrosheet_batting"]["year_coverage"] == {"min": 1969, "max": 1969}
    assert "retrosheet_pitcher_strikeout_side_events" in tables


def test_retrosheet_manifest_can_fall_back_to_loose_csvs(tmp_path):
    (tmp_path / "batting.csv").write_text(
        "gid,stattype,gametype,date,b_sb\nOAK196906100,value,regular,19690610,1\n",
        encoding="utf-8",
    )
    (tmp_path / "pitching.csv").write_text(
        "gid,stattype,gametype,date,p_ipouts\nOAK196906100,value,regular,19690610,27\n",
        encoding="utf-8",
    )
    (tmp_path / "fielding.csv").write_text(
        "gid,stattype,gametype,date,d_po\nOAK196906100,value,regular,19690610,3\n",
        encoding="utf-8",
    )
    (tmp_path / "biofile0.csv").write_text(
        "id,name_first,name_last\ncampb101,Bert,Campaneris\n",
        encoding="utf-8",
    )

    manifest_path = retrosheet.write_manifest(
        tmp_path,
        downloaded_at="2026-07-03T15:00:00-04:00",
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    batting = next(item for item in manifest["files"] if item["table"] == "retrosheet_batting")
    assert batting["path"].endswith("batting.csv")
    assert batting["archive_sha256"] == ""
    assert batting["rows"] == 1
