"""Generate the versioned season-aware Retrosheet team reference."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
from pathlib import Path

REFERENCE_VERSION = "retrosheet-season-aware-v1"
ASSET_DIR = Path(__file__).resolve().parents[1] / "query" / "catalog" / "assets"
REFERENCE_PATH = ASSET_DIR / "retrosheet_team_reference.csv"
MANIFEST_PATH = ASSET_DIR / "retrosheet_team_reference.manifest.json"
UPSTREAM_URL = (
    "https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv/Lahman/Teams.csv"
)
RETROSHEET_URL = "https://www.retrosheet.org/downloads/csvteams.html"


def render_retrosheet_team_reference(
    teams_path: Path,
    retrosheet_teams_path: Path,
) -> tuple[bytes, bytes]:
    """Merge official Retrosheet identities with season-specific Lahman names."""
    reference: dict[tuple[int, str], str] = {}
    official_content = retrosheet_teams_path.read_text(encoding="utf-8")
    for matched in re.finditer(
        r"(?m)^(?P<retro>[A-Z0-9]{3})\t(?P<name>.+?)\s*\t"
        r"(?P<first>\d{8})\t(?P<last>\d{8})\s*$",
        official_content,
    ):
        retro_id = matched.group("retro")
        name = matched.group("name").strip()
        first_year = int(matched.group("first")[:4])
        last_year = int(matched.group("last")[:4])
        for year_id in range(first_year, last_year + 1):
            reference[(year_id, retro_id)] = name
    if not reference:
        raise ValueError("Retrosheet team catalog contained no team identities.")

    with teams_path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            retro_id = row["teamIDretro"].strip()
            if not retro_id:
                continue
            key = (int(row["yearID"]), retro_id)
            name = row["name"].strip()
            if not name:
                raise ValueError(f"Missing team name for {key!r}.")
            reference[key] = name

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("yearID", "retrosheetTeamID", "name"))
    for (year_id, retro_id), name in sorted(reference.items()):
        writer.writerow((year_id, retro_id, name))
    csv_bytes = output.getvalue().encode("utf-8")

    manifest = {
        "reference_version": REFERENCE_VERSION,
        "sources": [
            {
                "name": "Retrosheet official team catalog",
                "url": RETROSHEET_URL,
                "sha256": _sha256(retrosheet_teams_path.read_bytes()),
            },
            {
                "name": "SABR Lahman Teams.csv with season-specific names",
                "url": UPSTREAM_URL,
                "sha256": _sha256(teams_path.read_bytes()),
            },
        ],
        "rows": len(reference),
        "sha256": _sha256(csv_bytes),
        "columns": ["yearID", "retrosheetTeamID", "name"],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return csv_bytes, manifest_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--retrosheet-teams", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    csv_bytes, manifest_bytes = render_retrosheet_team_reference(
        args.teams,
        args.retrosheet_teams,
    )
    if args.check:
        if REFERENCE_PATH.read_bytes() != csv_bytes:
            raise SystemExit("retrosheet_team_reference.csv is stale")
        if MANIFEST_PATH.read_bytes() != manifest_bytes:
            raise SystemExit("retrosheet_team_reference.manifest.json is stale")
        return 0
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_bytes(csv_bytes)
    MANIFEST_PATH.write_bytes(manifest_bytes)
    return 0


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
