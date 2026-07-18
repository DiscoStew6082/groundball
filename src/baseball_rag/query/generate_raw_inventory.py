"""Generate the exhaustive checked-in raw-field inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import duckdb

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.query.registry import CATALOG_DIR

INVENTORY_PATH = CATALOG_DIR / "raw_fields.json"
SOURCE_ASSETS = (
    ("People", "People.csv"),
    ("Batting", "Batting.csv"),
    ("Pitching", "Pitching.csv"),
    ("Fielding", "Fielding.csv"),
    ("TeamReference", "assets/team_reference.csv"),
)
TYPE_MAP = {
    "BIGINT": "integer",
    "DOUBLE": "number",
    "DATE": "date",
    "VARCHAR": "text",
}
TEXT_OPERATIONS = ("select", "equals", "one_of", "group", "sort", "export")
ORDERED_OPERATIONS = (
    "select",
    "equals",
    "not_equals",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "range",
    "group",
    "sort",
    "export",
)


def render_inventory(data_dir: Path) -> bytes:
    """Return canonical inventory JSON for the exact installed sources."""
    fields: list[dict[str, object]] = []
    connection = duckdb.connect(database=":memory:")
    try:
        for source, asset in SOURCE_ASSETS:
            path = (CATALOG_DIR / asset) if source == "TeamReference" else (data_dir / asset)
            description = connection.execute(
                "DESCRIBE SELECT * FROM read_csv_auto(?)",
                [str(path)],
            ).fetchall()
            for ordinal, row in enumerate(description):
                column = str(row[0])
                duckdb_type = str(row[1])
                logical_type = TYPE_MAP.get(duckdb_type)
                if logical_type is None:
                    raise ValueError(
                        f"Unsupported inferred type {duckdb_type!r} for {source}.{column}"
                    )
                operations = TEXT_OPERATIONS if logical_type == "text" else ORDERED_OPERATIONS
                field = {
                    "identity": f"{source}.{column}",
                    "source": source,
                    "column": column,
                    "ordinal": ordinal,
                    "duckdb_type": duckdb_type,
                    "data_type": logical_type,
                    "operations": list(operations),
                }
                fields.append(field)
    finally:
        connection.close()

    identities = [str(field["identity"]) for field in fields]
    if len(identities) != len(set(identities)):
        raise ValueError("Raw inventory contains duplicate field identities.")
    inventory_bytes = json.dumps(fields, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload = {
        "schema_version": 1,
        "inventory_revision": (f"raw-fields-{hashlib.sha256(inventory_bytes).hexdigest()[:16]}"),
        "fields": fields,
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rendered = render_inventory(args.data_dir)
    if args.check:
        if INVENTORY_PATH.read_bytes() != rendered:
            raise SystemExit("raw_fields.json is stale")
        return 0
    INVENTORY_PATH.write_bytes(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
