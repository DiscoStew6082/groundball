"""Database layer — queries via DuckDB over HuggingFace CSV data."""

from baseball_rag.db.duckdb_schema import DATA_DIR
from baseball_rag.db.queries import (
    execute_stat_query,
    get_career_stat_leaders,
    get_fielding_leaders,
    get_stat_leaders_range,
)

__all__ = [
    "DATA_DIR",
    "execute_stat_query",
    "get_stat_leaders_range",
    "get_career_stat_leaders",
    "get_fielding_leaders",
]
