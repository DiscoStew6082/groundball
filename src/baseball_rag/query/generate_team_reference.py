"""Generate the versioned season-aware team reference from Lahman sources."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path

from baseball_rag.db.duckdb_schema import DATA_DIR

REFERENCE_VERSION = "season-aware-v1"
FACT_FILES = ("Batting.csv", "Pitching.csv", "Fielding.csv")
ASSET_DIR = Path(__file__).with_name("catalog") / "assets"
REFERENCE_PATH = ASSET_DIR / "team_reference.csv"
REFERENCE_MANIFEST_PATH = ASSET_DIR / "team_reference.manifest.json"
UPSTREAM_URL = "https://sabr.org/lahman-database/"


def render_team_reference(data_dir: Path, teams_path: Path) -> tuple[bytes, bytes]:
    """Return deterministic CSV and manifest bytes for referenced team seasons."""
    referenced: set[tuple[int, str]] = set()
    for filename in FACT_FILES:
        with (data_dir / filename).open(newline="", encoding="utf-8") as source:
            for row in csv.DictReader(source):
                referenced.add((int(row["yearID"]), row["teamID"]))

    upstream: dict[tuple[int, str], str] = {}
    with teams_path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            key = (int(row["yearID"]), row["teamID"])
            name = row["name"].strip()
            if key in upstream and upstream[key] != name:
                raise ValueError(f"Conflicting team names for {key!r}.")
            upstream[key] = name

    missing = sorted(referenced - upstream.keys())
    if missing:
        raise ValueError(
            f"Official Teams.csv is missing {len(missing)} referenced identities: {missing[:5]}"
        )

    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(("yearID", "teamID", "name"))
    for year_id, team_id in sorted(referenced):
        name = upstream[(year_id, team_id)]
        if not name:
            raise ValueError(f"Missing team name for {(year_id, team_id)!r}.")
        writer.writerow((year_id, team_id, name))
    csv_bytes = output.getvalue().encode("utf-8")

    manifest = {
        "reference_version": REFERENCE_VERSION,
        "source": {
            "name": "SABR Lahman Baseball Database Teams.csv",
            "url": UPSTREAM_URL,
            "sha256": _sha256(teams_path.read_bytes()),
        },
        "fact_sources": list(FACT_FILES),
        "rows": len(referenced),
        "sha256": _sha256(csv_bytes),
        "columns": ["yearID", "teamID", "name"],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    return csv_bytes, manifest_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--teams", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    csv_bytes, manifest_bytes = render_team_reference(args.data_dir, args.teams)
    if args.check:
        if REFERENCE_PATH.read_bytes() != csv_bytes:
            raise SystemExit("team_reference.csv is stale")
        if REFERENCE_MANIFEST_PATH.read_bytes() != manifest_bytes:
            raise SystemExit("team_reference.manifest.json is stale")
        return 0
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_bytes(csv_bytes)
    REFERENCE_MANIFEST_PATH.write_bytes(manifest_bytes)
    return 0


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
