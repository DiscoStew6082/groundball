"""Derive compact pitcher event evidence from Retrosheet play-by-play files."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol
from zoneinfo import ZoneInfo

import requests

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.db.secondary_sources.retrosheet import RETROSHEET_ATTRIBUTION

RETROSHEET_EVENT_BASE_URL = "https://www.retrosheet.org/events"
RETROSHEET_EVENT_DATA_DIR = DATA_DIR / "secondary_sources" / "retrosheet"
PITCHER_STRIKEOUT_SIDE_EVENTS_CSV = "pitcher_strikeout_side_events.csv"


class _HttpResponse(Protocol):
    status_code: int

    def iter_content(self, chunk_size: int) -> Iterable[bytes]: ...


HttpGet = Callable[[str, int], _HttpResponse]


@dataclass(frozen=True)
class PitcherHalfInning:
    """Derived pitcher half-inning evidence from Retrosheet play rows."""

    retro_id: str
    year: int
    game_id: str
    inning: int
    batting_home: int
    started_half_inning: bool
    strikeout_outs: int
    total_outs_recorded: int
    event_sequence: tuple[str, ...]

    @property
    def is_strikeout_side(self) -> bool:
        return (
            self.total_outs_recorded >= 3
            and self.strikeout_outs >= 3
            and self.total_outs_recorded == self.strikeout_outs
        )


def download_pitcher_strikeout_side_events(
    target_dir: Path | None = None,
    *,
    start_year: int,
    end_year: int,
    http_get: HttpGet | None = None,
    downloaded_at: str | None = None,
) -> Path:
    """Download Retrosheet event files and write strikeout-side evidence rows."""
    target_dir = Path(target_dir or RETROSHEET_EVENT_DATA_DIR)
    target_dir.mkdir(parents=True, exist_ok=True)
    get = http_get or _requests_get
    rows = list(
        derive_pitcher_strikeout_side_events(
            range(start_year, end_year + 1),
            http_get=get,
        )
    )
    output_path = target_dir / PITCHER_STRIKEOUT_SIDE_EVENTS_CSV
    _write_pitcher_strikeout_side_events(output_path, rows)
    _write_event_manifest(
        target_dir,
        output_path=output_path,
        rows=rows,
        downloaded_at=downloaded_at,
    )
    return output_path


def derive_pitcher_strikeout_side_events(
    years: Iterable[int],
    *,
    http_get: HttpGet,
) -> Iterable[PitcherHalfInning]:
    """Yield pitcher half-innings where all recorded outs were strikeouts."""
    for year in years:
        response = http_get(f"{RETROSHEET_EVENT_BASE_URL}/{year}eve.zip", 60)
        if response.status_code == 404:
            continue
        if response.status_code != 200:
            raise RuntimeError(f"Failed to download Retrosheet events for {year}")
        archive_bytes = b"".join(chunk for chunk in response.iter_content(1024 * 1024) if chunk)
        yield from _derive_year_pitcher_strikeout_side_events(year, archive_bytes)


def _derive_year_pitcher_strikeout_side_events(
    year: int,
    archive_bytes: bytes,
) -> Iterable[PitcherHalfInning]:
    half_innings: dict[tuple[str, int, int], _HalfInningBuilder] = defaultdict(_HalfInningBuilder)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        for member_name in archive.namelist():
            if not member_name.upper().endswith((".EVA", ".EVN", ".EVF", ".EVR")):
                continue
            current_pitcher: dict[int, str | None] = {0: None, 1: None}
            game_id: str | None = None
            for raw_line in archive.read(member_name).decode("latin1").splitlines():
                if not raw_line:
                    continue
                fields = _parse_csv_line(raw_line)
                row_type = fields[0]
                if row_type == "id":
                    game_id = fields[1]
                    current_pitcher = {0: None, 1: None}
                elif row_type in {"start", "sub"} and len(fields) >= 6 and fields[5] == "1":
                    current_pitcher[int(fields[3])] = fields[1]
                elif row_type == "play" and len(fields) >= 7 and game_id is not None:
                    event = fields[6]
                    if event == "NP":
                        continue
                    inning = int(fields[1])
                    batting_home = int(fields[2])
                    fielding_home = 1 - batting_home
                    pitcher_id = current_pitcher.get(fielding_home)
                    if pitcher_id is None:
                        continue
                    builder = half_innings[(game_id, inning, batting_home)]
                    builder.add_event(
                        pitcher_id=pitcher_id,
                        event=event,
                        outs=_event_out_counts(event),
                    )

    for (game_id, inning, batting_home), builder in sorted(half_innings.items()):
        for row in builder.rows(
            year=year,
            game_id=game_id,
            inning=inning,
            batting_home=batting_home,
        ):
            if row.is_strikeout_side:
                yield row


class _HalfInningBuilder:
    def __init__(self) -> None:
        self.first_pitcher_id: str | None = None
        self.events_by_pitcher: dict[str, list[tuple[str, tuple[int, int]]]] = defaultdict(list)

    def add_event(
        self,
        *,
        pitcher_id: str,
        event: str,
        outs: tuple[int, int],
    ) -> None:
        if self.first_pitcher_id is None:
            self.first_pitcher_id = pitcher_id
        self.events_by_pitcher[pitcher_id].append((event, outs))

    def rows(
        self,
        *,
        year: int,
        game_id: str,
        inning: int,
        batting_home: int,
    ) -> Iterable[PitcherHalfInning]:
        for pitcher_id, events in self.events_by_pitcher.items():
            total_outs = sum(total for _event, (total, _strikeout) in events)
            strikeout_outs = sum(strikeout for _event, (_total, strikeout) in events)
            yield PitcherHalfInning(
                retro_id=pitcher_id,
                year=year,
                game_id=game_id,
                inning=inning,
                batting_home=batting_home,
                started_half_inning=pitcher_id == self.first_pitcher_id,
                strikeout_outs=strikeout_outs,
                total_outs_recorded=total_outs,
                event_sequence=tuple(event for event, _outs in events),
            )


def _event_out_counts(event: str) -> tuple[int, int]:
    """Return ``(total_outs, strikeout_outs)`` for one Retrosheet play event."""
    if event in {"NP", "BK", "WP", "PB", "OA", "DI"}:
        return 0, 0

    main_event = _main_event(event)
    total_outs = 0
    strikeout_outs = 0
    if main_event.startswith("K"):
        if not _batter_reached(event):
            total_outs += 1
            strikeout_outs += 1
        total_outs += _runner_out_count(event)
        return total_outs, strikeout_outs

    if _batter_out(main_event):
        total_outs += 1
    total_outs += len(re.findall(r"\([123]\)", main_event))
    total_outs += _runner_out_count(event)
    return total_outs, strikeout_outs


def _main_event(event: str) -> str:
    return event.split(".", 1)[0].split("/", 1)[0]


def _batter_reached(event: str) -> bool:
    return bool(re.search(r"(?:^|[.;])B-[123H]", event))


def _batter_out(main_event: str) -> bool:
    return bool(
        re.match(r"^[1-9]+", main_event)
        or re.match(r"^(?:F|L|P|G)[1-9]", main_event)
        or re.match(r"^C/[A-Z]", main_event)
        or re.match(r"^S[HF][1-9]", main_event)
    )


def _runner_out_count(event: str) -> int:
    runner_outs = re.findall(
        r"(?:^|[.;+])((?:[123]X[123H]|CS[23H]|POCS[23H]|PO[123])(?:\([^)]*\))?)",
        event,
    )
    return sum(1 for runner_out in runner_outs if "E" not in runner_out)


def _write_pitcher_strikeout_side_events(
    path: Path,
    rows: list[PitcherHalfInning],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "retroID",
                "year",
                "game_id",
                "inning",
                "batting_home",
                "started_half_inning",
                "strikeout_outs",
                "total_outs_recorded",
                "event_sequence",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "retroID": row.retro_id,
                    "year": row.year,
                    "game_id": row.game_id,
                    "inning": row.inning,
                    "batting_home": row.batting_home,
                    "started_half_inning": str(row.started_half_inning).lower(),
                    "strikeout_outs": row.strikeout_outs,
                    "total_outs_recorded": row.total_outs_recorded,
                    "event_sequence": "|".join(row.event_sequence),
                }
            )


def _write_event_manifest(
    target_dir: Path,
    *,
    output_path: Path,
    rows: list[PitcherHalfInning],
    downloaded_at: str | None,
) -> Path:
    years = [row.year for row in rows]
    timestamp = downloaded_at or datetime.now(ZoneInfo("America/New_York")).isoformat(
        timespec="seconds"
    )
    manifest = {
        "dataset": {
            "name": "Retrosheet event-derived local aggregates",
            "source_url": RETROSHEET_EVENT_BASE_URL,
            "attribution": RETROSHEET_ATTRIBUTION,
            "license_notes": (
                "Retrosheet data is free to use with required attribution. Retrosheet "
                "makes no guarantees of accuracy and updates data as corrections arrive."
            ),
        },
        "download": {
            "downloaded_at": timestamp,
            "download_tool": "python -m baseball_rag.db.secondary_sources.retrosheet_events",
            "notes": "Generated pitcher strikeout-side evidence from Retrosheet event archives.",
        },
        "coverage": {
            "year_coverage": {
                "min": min(years) if years else None,
                "max": max(years) if years else None,
            }
        },
        "files": [
            {
                "path": f"data/secondary_sources/retrosheet/{output_path.name}",
                "source_url": f"{RETROSHEET_EVENT_BASE_URL}/",
                "table": "retrosheet_pitcher_strikeout_side_events",
                "kind": "event_derived_evidence",
                "rows": len(rows),
                "year_coverage": {
                    "min": min(years) if years else None,
                    "max": max(years) if years else None,
                },
                "sha256": _sha256(output_path),
            }
        ],
    }
    manifest_path = target_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def _requests_get(url: str, timeout: int) -> requests.Response:
    return requests.get(url, timeout=timeout)


def _parse_csv_line(raw_line: str) -> list[str]:
    return next(csv.reader([raw_line]))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download Retrosheet event files and derive pitcher strikeout-side rows."
    )
    parser.add_argument("--data-dir", type=Path, default=RETROSHEET_EVENT_DATA_DIR)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    args = parser.parse_args()

    output_path = download_pitcher_strikeout_side_events(
        args.data_dir,
        start_year=args.start_year,
        end_year=args.end_year,
    )
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
