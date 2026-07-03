"""Groundball query engine — CLI entry point."""

import sys

from baseball_rag.request_execution import execute_request
from baseball_rag.retrosheet_event_capabilities import retrosheet_event_capabilities
from baseball_rag.service import render_text


def answer(question: str) -> str:
    """Answer a single question as CLI-friendly text."""
    return render_text(execute_request(question, adapter_component_id="cli").answer)


def retrosheet_event_capabilities_text() -> str:
    """Return the Retrosheet event support matrix as CLI-friendly text."""
    lines = ["Retrosheet event capabilities:"]
    for capability in retrosheet_event_capabilities():
        lines.extend(
            [
                "",
                f"{capability.title}",
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


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] == "--help":
        print(
            "Groundball Query Engine\n"
            "Usage: groundball 'your question'\n\n"
            "Inspect capabilities: groundball capabilities retrosheet-events\n\n"
            "Compatibility alias: baseball-rag\n\n"
            "Examples:\n"
            "  groundball 'who had the most RBIs in 1962'\n"
            "  groundball 'career home run leaders'\n"
        )
        sys.exit(0)

    if sys.argv[1:] == ["capabilities", "retrosheet-events"]:
        print(retrosheet_event_capabilities_text())
        sys.exit(0)

    question = " ".join(sys.argv[1:])
    result = answer(question)
    print(result)


if __name__ == "__main__":
    main()
