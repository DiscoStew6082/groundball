"""Shared vocabulary for known static corpus documents."""

from __future__ import annotations

from baseball_rag.stat_mentions import for_stat_definition_lookup

STAT_DEFINITION_DOC_IDS: dict[str, str] = dict(for_stat_definition_lookup().aliases)


def stat_definition_doc_ids_for_query(query: str) -> list[str]:
    """Return static stat-definition document IDs mentioned by query text."""
    return _doc_ids_for_query(query)


def _doc_ids_for_query(query: str) -> list[str]:
    return for_stat_definition_lookup().find_stats(query)
