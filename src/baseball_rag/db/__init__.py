"""Database layer — queries via DuckDB over HuggingFace CSV data."""

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.db.queries import execute_stat_query

__all__ = [
    "DATA_DIR",
    "execute_stat_query",
]
