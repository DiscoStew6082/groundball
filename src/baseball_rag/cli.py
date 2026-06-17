"""Groundball query engine — CLI entry point."""

import sys

from baseball_rag.request_execution import execute_request
from baseball_rag.service import render_text


def answer(question: str) -> str:
    """Answer a single question as CLI-friendly text."""
    return render_text(execute_request(question, adapter_component_id="cli").answer)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] == "--help":
        print(
            "Groundball Query Engine\n"
            "Usage: groundball 'your question'\n\n"
            "Compatibility alias: baseball-rag\n\n"
            "Examples:\n"
            "  groundball 'who had the most RBIs in 1962'\n"
            "  groundball 'career home run leaders'\n"
        )
        sys.exit(0)

    question = " ".join(sys.argv[1:])
    result = answer(question)
    print(result)


if __name__ == "__main__":
    main()
