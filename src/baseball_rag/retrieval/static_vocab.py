"""Shared vocabulary for known static corpus documents."""

from __future__ import annotations

STAT_DEFINITION_DOC_IDS: dict[str, str] = {
    "2b": "2B",
    "avg": "AVG",
    "batting average": "AVG",
    "bb": "BB",
    "base on balls": "BB",
    "era": "ERA",
    "earned run average": "ERA",
    "hr": "HR",
    "home run": "HR",
    "home runs": "HR",
    "ops": "OPS",
    "on-base plus slugging": "OPS",
    "po": "PO",
    "putout": "PO",
    "putouts": "PO",
    "rbi": "RBI",
    "run batted in": "RBI",
    "runs batted in": "RBI",
    "sb": "SB",
    "stolen base": "SB",
    "stolen bases": "SB",
    "whip": "WHIP",
}

HOF_DOC_IDS: dict[str, str] = {
    "babe ruth": "Babe_Ruth",
    "hank aaron": "Hank_Aaron",
    "mickey mantle": "Mickey_Mantle",
    "ted williams": "Ted_Williams",
    "willie mays": "Willie_Mays",
}

EXPLANATION_TERMS = ("what is", "what does", "explain", "mean", "definition")


def stat_definition_doc_ids_for_query(query: str) -> list[str]:
    """Return static stat-definition document IDs mentioned by query text."""
    return _doc_ids_for_query(query, STAT_DEFINITION_DOC_IDS)


def static_doc_ids_for_query(query: str) -> list[str]:
    """Return known static corpus document IDs mentioned by query text."""
    return _doc_ids_for_query(query, {**STAT_DEFINITION_DOC_IDS, **HOF_DOC_IDS})


def query_mentions_stat_definition(query: str) -> bool:
    """Return whether query mentions a known stat-definition phrase."""
    lower_query = query.lower()
    return any(phrase in lower_query for phrase in STAT_DEFINITION_DOC_IDS)


def query_asks_for_explanation(query: str) -> bool:
    """Return whether query phrasing asks for an explanatory corpus answer."""
    lower_query = query.lower()
    return any(phrase in lower_query for phrase in EXPLANATION_TERMS)


def _doc_ids_for_query(query: str, phrase_map: dict[str, str]) -> list[str]:
    lower_query = query.lower()
    ids: list[str] = []
    for phrase, doc_id in phrase_map.items():
        if phrase in lower_query and doc_id not in ids:
            ids.append(doc_id)
    return ids
