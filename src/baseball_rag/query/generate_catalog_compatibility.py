"""Generate the exact catalog-to-data compatibility binding."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.query.registry import CATALOG_DIR

COMPATIBILITY_PATH = CATALOG_DIR / "compatibility.json"


def render_compatibility(data_dir: Path) -> bytes:
    """Return canonical compatibility JSON for all revision-bearing inputs."""
    catalog_path = CATALOG_DIR / "published_catalog.json"
    catalog = _read_json(catalog_path)
    inventory_path = CATALOG_DIR / "raw_fields.json"
    inventory = _read_json(inventory_path)
    registry_path = CATALOG_DIR / "published_sources.json"
    registry = _read_json(registry_path)
    team_manifest_path = CATALOG_DIR / "assets/team_reference.manifest.json"
    team_manifest = _read_json(team_manifest_path)
    data_manifest_path = data_dir / "manifest.json"
    payload = {
        "catalog_revision": catalog["catalog_revision"],
        "catalog_sha256": _sha256(catalog_path),
        "data_manifest_sha256": _sha256(data_manifest_path),
        "raw_inventory_revision": inventory["inventory_revision"],
        "raw_inventory_sha256": _sha256(inventory_path),
        "source_registry_revision": registry["registry_revision"],
        "source_registry_sha256": _sha256(registry_path),
        "team_reference_revision": team_manifest["reference_version"],
        "team_reference_manifest_sha256": _sha256(team_manifest_path),
    }
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    rendered = render_compatibility(args.data_dir)
    if args.check:
        if COMPATIBILITY_PATH.read_bytes() != rendered:
            raise SystemExit("compatibility.json is stale")
        return 0
    COMPATIBILITY_PATH.write_bytes(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
