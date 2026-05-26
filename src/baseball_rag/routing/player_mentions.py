"""Route-time player mention lookup backed by the Lahman identity authority."""

from __future__ import annotations

from functools import lru_cache

from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.player_identity import resolve_player_by_name


def is_known_player_mention(value: str) -> bool:
    """Return whether a mention resolves to at least one Lahman player."""
    normalized = normalize_player_mention(value)
    if not normalized:
        return False
    return _has_player_identity(normalized)


def normalize_player_mention(value: str) -> str:
    """Normalize user mention spacing/casing without resolving identity."""
    return " ".join(token[:1].upper() + token[1:] for token in value.split())


@lru_cache(maxsize=2048)
def _has_player_identity(value: str) -> bool:
    conn = get_duckdb()
    return bool(resolve_player_by_name(value, conn).candidates)
