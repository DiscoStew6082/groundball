"""Ground Ball command-line Adapters."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from baseball_rag.query.adapters import catalog_payload, run_query_input
from baseball_rag.retrosheet_event_capabilities import retrosheet_event_capabilities


def retrosheet_event_capabilities_text() -> str:
    """Return the separately governed Retrosheet capability matrix."""
    lines = ["Retrosheet event capabilities:"]
    for capability in retrosheet_event_capabilities():
        lines.extend(
            [
                "",
                capability.title,
                f"  table: {capability.local_table}",
                f"  source: {capability.data_source}",
                "  supported:",
            ]
        )
        lines.extend(f"    - {family}" for family in capability.supported_query_families)
        lines.append("  filters:")
        lines.extend(
            f"    - {supported_filter}" for supported_filter in capability.supported_filters
        )
        lines.append("  unsupported nearby:")
        lines.extend(f"    - {family}" for family in capability.unsupported_nearby_families)
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    """Run the clean Query Recipe, catalog, or Retrosheet capability Adapter."""
    parser = argparse.ArgumentParser(prog="groundball", description="Query MLB history")
    commands = parser.add_subparsers(dest="command", required=True)

    query = commands.add_parser("query", help="Plan and execute one query")
    query_input = query.add_mutually_exclusive_group(required=True)
    query_input.add_argument("question", nargs="?", help="Reviewed natural-language question")
    query_input.add_argument("--recipe-json", help="Structured Query Recipe JSON")

    fields = commands.add_parser("fields", help="Discover published query fields")
    fields.add_argument("--source")
    fields.add_argument("--search")

    capabilities = commands.add_parser("capabilities", help="Inspect separate capabilities")
    capabilities.add_argument("capability", choices=("retrosheet-events",))

    args = parser.parse_args(argv)
    if args.command == "query":
        if args.recipe_json is not None:
            try:
                recipe = json.loads(args.recipe_json)
            except json.JSONDecodeError as exc:
                parser.error(f"Invalid Query Recipe JSON: {exc.msg}")
            if not isinstance(recipe, dict):
                parser.error("Query Recipe JSON must be an object.")
            payload = run_query_input(recipe=recipe)
        else:
            payload = run_query_input(question=args.question)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if args.command == "fields":
        payload = catalog_payload(source=args.source, search=args.search)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(retrosheet_event_capabilities_text())


if __name__ == "__main__":
    main()
