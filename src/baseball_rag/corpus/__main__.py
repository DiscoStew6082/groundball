"""CLI entrypoint for corpus diagnostics."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from baseball_rag.corpus.diagnostics import diagnostics_json


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Print corpus diagnostics as JSON.")
    parser.add_argument("command", choices=["diagnostics", "diag"])
    parser.add_argument("--persist-dir", type=Path, default=None)
    parsed = parser.parse_args(args)
    print(diagnostics_json(parsed.persist_dir))
    return 0


raise SystemExit(main())
