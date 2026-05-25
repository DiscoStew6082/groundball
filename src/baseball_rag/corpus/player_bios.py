"""Compatibility facade for the shared player identity authority."""

from baseball_rag.db.player_identity import (
    PlayerCandidate,
    PlayerResolution,
    resolve_player_by_name,
)

__all__ = ["PlayerCandidate", "PlayerResolution", "resolve_player_by_name"]
