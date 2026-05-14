"""Retired corpus indexing entry point."""

from __future__ import annotations

import argparse
from pathlib import Path


def build_index(persist_dir: Path, *, include_players: bool = True) -> None:
    """Reject legacy corpus index builds."""
    _ = (persist_dir, include_players)
    raise RuntimeError(
        "Corpus indexing was removed. Baseball RAG now uses DuckDB for structured facts "
        "and the local LLM for open explanations and biographies."
    )


def main(argv: list[str] | None = None) -> int:
    """Explain that corpus indexing is no longer supported."""
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("--persist-dir", type=Path, default=None)
    parser.add_argument("--static-only", action="store_true")
    parser.parse_args(argv)
    print(
        "Corpus indexing was removed. No local vector index is built or required.",
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
