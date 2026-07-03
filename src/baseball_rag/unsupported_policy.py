"""Deterministic policy guardrails for unsupported questions."""

from __future__ import annotations

import re

from baseball_rag.outcomes import unsupported_outcome
from baseball_rag.provenance import SourceRecord, StructuredAnswer

_POLICY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(drop\s+table|delete\s+from|insert\s+into|update\s+\w+\s+set)\b"),
        "SQL mutation text is not a supported baseball question.",
    ),
    (
        re.compile(r"\bvibes?\b"),
        "The local data is grounded in specific baseball stats, not vibes.",
    ),
    (
        re.compile(r"\bbet(?:ting)?\b|\bodds?\b|\bparlay\b"),
        "Betting advice and odds are outside the local grounded baseball data.",
    ),
    (
        re.compile(r"\binjur(?:y|ed|ies)\b|\btoday\b.*\binjur"),
        "Live injury news is outside the local historical dataset.",
    ),
    (
        re.compile(r"\bscore\b.*\b(right now|today|tonight|live)\b"),
        "Live scores are outside the local historical dataset.",
    ),
    (
        re.compile(r"\b(current\s+)?salary\b|\bcontract\b"),
        "Current salary and contract data are outside the local historical dataset.",
    ),
    (
        re.compile(r"\bbest ever\b|\bgreatest\b.*\b(ever|all time|player)\b"),
        "Subjective rankings need a specific grounded metric.",
    ),
    (
        re.compile(r"\bnba\b|\bfootball\b|\bbasketball\b|\bnfl\b|\bnhl\b"),
        "Non-baseball questions are outside this assistant's local dataset.",
    ),
    (
        re.compile(r"\bstatcast\b|\bbarrel rate\b"),
        "Statcast fields are not available in the local Lahman-derived dataset.",
    ),
    (
        re.compile(r"\btriple-a\b|\btriple a\b|\bminor leagues?\b"),
        "Minor-league leaderboards are outside the local MLB-focused dataset.",
    ),
)


def unsupported_policy_outcome(question: str) -> StructuredAnswer | None:
    """Return a structured unsupported answer for deterministic policy misses."""
    lower_question = question.lower()
    for pattern, reason in _POLICY_PATTERNS:
        if pattern.search(lower_question):
            return unsupported_outcome(
                answer=(
                    f"I can't answer that from the grounded local baseball data. {reason} "
                    "Ask for a specific MLB statistic, player, team, season, or historical "
                    "query covered by the local DuckDB data."
                ),
                intent="unsupported",
                reason="unsupported",
                sources=[
                    SourceRecord(
                        type="system",
                        label="Unsupported question policy",
                        detail="Deterministic pre-routing guardrail for out-of-scope requests.",
                    )
                ],
            )
    return None
