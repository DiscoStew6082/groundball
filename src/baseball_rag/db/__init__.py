"""Database layer — queries via DuckDB over HuggingFace CSV data."""

from baseball_rag.db.duckdb_schema import DATA_DIR

__all__ = [
    "DATA_DIR",
]
