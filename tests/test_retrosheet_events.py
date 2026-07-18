"""Tests for Retrosheet event-derived evidence generation."""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

from baseball_rag.db.secondary_sources import retrosheet_events


def _zip_bytes(member_name: str, content: str) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, content: bytes, *, status_code: int = 200) -> None:
        self.status_code = status_code
        self.content = content

    def iter_content(self, chunk_size: int) -> list[bytes]:
        return [self.content]


def test_download_pitcher_strikeout_side_events_derives_reusable_evidence(tmp_path):
    event_zip = _zip_bytes(
        "1975OAK.EVF",
        "\n".join(
            [
                "id,OAK197505120",
                "info,visteam,NYA",
                "info,hometeam,OAK",
                "info,site,OAK01",
                'start,fingr001,"Rollie Fingers",0,9,1',
                'start,batt001,"Batter One",1,1,3',
                "play,5,1,batt001,??,,K",
                "play,5,1,batt002,??,,K/C",
                "play,5,1,batt003,??,,K",
                "play,6,1,batt004,??,,S7",
                "play,6,1,batt005,??,,K",
                "play,6,1,batt006,??,,43",
                "play,6,1,batt007,??,,K",
            ]
        )
        + "\n",
    )

    def fake_get(url: str, timeout: int) -> _FakeResponse:
        assert url.endswith("/1975eve.zip")
        return _FakeResponse(event_zip)

    output_path = retrosheet_events.download_pitcher_strikeout_side_events(
        tmp_path,
        start_year=1975,
        end_year=1975,
        http_get=fake_get,
        downloaded_at="2026-07-03T03:00:00-04:00",
    )

    rows = output_path.read_text(encoding="utf-8").splitlines()
    assert rows == [
        "retroID,year,game_id,inning,batting_home,started_half_inning,"
        "strikeout_outs,total_outs_recorded,event_sequence,game_date,home_team_id,"
        "away_team_id,pitcher_team_id,opponent_team_id,site",
        "fingr001,1975,OAK197505120,5,1,true,3,3,K|K/C|K,1975-05-12,OAK,NYA,NYA,OAK,OAK01",
    ]
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["download"]["download_tool"] == (
        "python -m baseball_rag.db.secondary_sources.retrosheet_events"
    )
    assert manifest["files"][0]["table"] == "retrosheet_pitcher_strikeout_side_events"
    assert manifest["files"][0]["rows"] == 1


def test_event_out_counts_ignore_error_negated_runner_outs():
    assert retrosheet_events._event_out_counts("CS2(2E4).1-3") == (0, 0)
    assert retrosheet_events._event_out_counts("PO1(E3).1-2") == (0, 0)
    assert retrosheet_events._event_out_counts("K+CS2(2E4)") == (1, 1)
    assert retrosheet_events._event_out_counts("K+CS2(26)") == (2, 1)
