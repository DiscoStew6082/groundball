"""Conversation follow-up resolution for grounded answer turns."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

from baseball_rag.conversation_transcript import (
    active_player_from_recent_turn,
    normalize_transcript,
    player_name_from_row,
    row_from_recent_turn,
)
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.routing import PlayerBiographyCase

ReferenceKind = Literal["pronoun", "ordinal_row", "none"]
ResolutionConfidence = Literal["high", "unsupported"]
UnsupportedReason = Literal[
    "no_conversation",
    "no_reference",
    "no_active_player",
    "row_not_found",
    "player_name_not_found",
]

_ORDINAL_ROW_INDEX = {
    "first": 0,
    "1st": 0,
    "second": 1,
    "2nd": 1,
    "third": 2,
    "3rd": 2,
    "fourth": 3,
    "4th": 3,
    "fifth": 4,
    "5th": 4,
    "sixth": 5,
    "6th": 5,
    "seventh": 6,
    "7th": 6,
    "eighth": 7,
    "8th": 7,
    "ninth": 8,
    "9th": 8,
    "tenth": 9,
    "10th": 9,
}
_FOLLOWUP_PRONOUN_RE = re.compile(r"\b(he|him|his|that player|this player)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ConversationResolution:
    """Question rewrite plus provenance for a resolved conversational reference."""

    resolved_question: str
    referenced_player_name: str | None = None
    reference_kind: ReferenceKind = "none"
    source_turn: str | None = None
    confidence: ResolutionConfidence = "unsupported"
    unsupported_reason: UnsupportedReason | None = None


def resolve_followup(
    question: str,
    conversation: list[dict[str, Any]] | None,
) -> ConversationResolution:
    """Resolve simple follow-up references against prior grounded answer rows."""
    transcript = normalize_transcript(conversation)
    if not transcript:
        return _unresolved(question, "no_conversation")

    row_reference = _referenced_row_reference(question)
    if row_reference.row_index is None:
        return _unresolved(question, "no_reference")

    if (
        row_reference.reference_kind == "pronoun"
        and row_reference.row_index == 0
        and _FOLLOWUP_PRONOUN_RE.search(question)
    ):
        active_player, active_source = active_player_from_recent_turn(transcript)
        if active_player is not None:
            return ConversationResolution(
                resolved_question=_question_for_player_followup(
                    question,
                    active_player,
                    replace_ordinals=False,
                ),
                referenced_player_name=active_player,
                reference_kind="pronoun",
                source_turn=active_source,
                confidence="high",
            )

    row, source_turn = row_from_recent_turn(transcript, row_reference.row_index)
    if row is None:
        reason: UnsupportedReason = (
            "no_active_player" if row_reference.reference_kind == "pronoun" else "row_not_found"
        )
        return _unresolved(question, reason)

    player_name = player_name_from_row(row)
    if player_name is None:
        return _unresolved(question, "player_name_not_found")

    return ConversationResolution(
        resolved_question=_question_for_player_followup(
            question,
            player_name,
            replace_pronouns=False,
            ordinal_reference=row_reference.reference_text,
        ),
        referenced_player_name=player_name,
        reference_kind=row_reference.reference_kind,
        source_turn=source_turn,
        confidence="high",
    )


def conversation_turn(question: str, answer: StructuredAnswer | dict[str, Any]) -> dict[str, Any]:
    """Build the compact turn shape used for future follow-up resolution."""
    answer_payload = answer.to_dict() if isinstance(answer, StructuredAnswer) else dict(answer)
    metadata = answer_payload.get("metadata") or {}
    compact_payload = {
        "answer": answer_payload.get("answer"),
        "intent": answer_payload.get("intent"),
        "metadata": {
            key: metadata[key]
            for key in (
                "original_question",
                "context_question",
                "context_source",
                "context_player_name",
            )
            if key in metadata
        },
        "sources": [_conversation_source(source) for source in answer_payload.get("sources", [])],
    }
    return {"question": question, "answer": compact_payload}


def attach_context_metadata(
    answer: StructuredAnswer,
    *,
    original_question: str,
    resolution: ConversationResolution,
    decision: Any,
) -> None:
    """Attach follow-up context metadata to an answer."""
    if resolution.source_turn is not None:
        answer.metadata["original_question"] = original_question
        answer.metadata["context_question"] = resolution.resolved_question
        answer.metadata["context_source"] = resolution.source_turn
    if answer.unsupported:
        return
    if resolution.referenced_player_name is not None:
        answer.metadata["context_player_name"] = resolution.referenced_player_name
    elif isinstance(decision, PlayerBiographyCase) and (
        decision.intent == "player_biography" and decision.player_name
    ):
        answer.metadata["context_player_name"] = decision.player_name


@dataclass(frozen=True)
class _RowReference:
    row_index: int | None
    reference_kind: ReferenceKind
    reference_text: str | None = None


def _unresolved(question: str, reason: UnsupportedReason) -> ConversationResolution:
    return ConversationResolution(resolved_question=question, unsupported_reason=reason)


def _referenced_row_reference(question: str) -> _RowReference:
    lowered = question.lower()
    if _looks_like_ordinal_achievement_question(lowered):
        return _RowReference(None, "none")
    for ordinal, index in _ORDINAL_ROW_INDEX.items():
        match = re.search(
            rf"\b(?:the\s+)?{re.escape(ordinal)}\s+(player|row|result)\b",
            lowered,
        )
        if match:
            return _RowReference(index, "ordinal_row", question[match.start() : match.end()])
        match = re.search(
            rf"\b(?:tell me about|who was|what about)\s+(?:the\s+)?{re.escape(ordinal)}\b"
            r"(?!\s+(?:base|baseman|inning|time|season|year))",
            lowered,
        )
        if match:
            prefix_match = re.search(rf"\b(?:the\s+)?{re.escape(ordinal)}\b", match.group(0))
            if prefix_match:
                start = match.start() + prefix_match.start()
                end = match.start() + prefix_match.end()
                return _RowReference(index, "ordinal_row", question[start:end])
            return _RowReference(index, "ordinal_row", question[match.start() : match.end()])
    if _FOLLOWUP_PRONOUN_RE.search(question):
        return _RowReference(0, "pronoun")
    return _RowReference(None, "none")


def _looks_like_ordinal_achievement_question(lowered_question: str) -> bool:
    ordinal_alt = "|".join(re.escape(ordinal) for ordinal in _ORDINAL_ROW_INDEX)
    ordinal_noun = rf"(?:{ordinal_alt})(?:\s+(?:player|row|result))?"
    achievement_intro = r"\b(?:who|which|tell\s+me\s+about)\b"
    achievement_to = rf"{achievement_intro}.*\b{ordinal_noun}\b(?:\s+[\w'-]+){{0,6}}\s+to\b"
    achievement_with_number = (
        rf"{achievement_intro}.*\b{ordinal_noun}\b"
        rf"(?:\s+[\w'-]+){{0,6}}\s+with\s+\d"
    )
    return bool(
        re.search(achievement_to, lowered_question)
        or re.search(achievement_with_number, lowered_question)
    )


def _row_from_recent_turn(
    conversation: list[dict[str, Any]],
    row_index: int,
) -> tuple[dict[str, Any] | None, str | None]:
    row, source_turn = row_from_recent_turn(normalize_transcript(conversation), row_index)
    return dict(row) if row is not None else None, source_turn


def _active_player_from_recent_turn(
    conversation: list[dict[str, Any]],
) -> tuple[str | None, str | None]:
    return active_player_from_recent_turn(normalize_transcript(conversation))


def _answer_payload(turn: dict[str, Any]) -> dict[str, Any] | None:
    answer_payload = turn.get("answer")
    if isinstance(answer_payload, StructuredAnswer):
        answer_payload = answer_payload.to_dict()
    return answer_payload if isinstance(answer_payload, dict) else None


def _turn_question(turn: dict[str, Any]) -> str | None:
    question = turn.get("question")
    return question if isinstance(question, str) else None


def _player_name_from_row(row: dict[str, Any]) -> str | None:
    return player_name_from_row(row)


def _conversation_source(source: dict[str, Any]) -> dict[str, Any]:
    rows = source.get("rows") or []
    compact_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        compact_row = {
            key: row[key]
            for key in ("name", "player_name", "full_name", "year", "team", "stat_value")
            if key in row
        }
        if "nameFirst" in row:
            compact_row["nameFirst"] = row["nameFirst"]
        if "nameLast" in row:
            compact_row["nameLast"] = row["nameLast"]
        if compact_row:
            compact_rows.append(compact_row)
    return {
        "type": source.get("type"),
        "label": source.get("label"),
        "rows": compact_rows,
    }


def _question_for_player_followup(
    question: str,
    player_name: str,
    *,
    replace_ordinals: bool = True,
    replace_pronouns: bool = True,
    ordinal_reference: str | None = None,
) -> str:
    rewritten = question
    if replace_ordinals and ordinal_reference is not None:
        rewritten = re.sub(
            re.escape(ordinal_reference),
            player_name,
            rewritten,
            count=1,
            flags=re.IGNORECASE,
        )
    elif replace_ordinals:
        for ordinal in _ORDINAL_ROW_INDEX:
            rewritten = re.sub(
                rf"\b(?:the\s+)?{re.escape(ordinal)}(?:\s+(?:player|row|result))?\b",
                player_name,
                rewritten,
                count=1,
                flags=re.IGNORECASE,
            )
    if replace_pronouns:
        possessive = f"{player_name}'" if player_name.endswith("s") else f"{player_name}'s"
        rewritten = re.sub(r"\bhis\b", possessive, rewritten, count=1, flags=re.IGNORECASE)
        rewritten = re.sub(
            r"\b(he|him|that player|this player)\b",
            player_name,
            rewritten,
            count=1,
            flags=re.IGNORECASE,
        )
    if rewritten == question:
        return f"{question} about {player_name}"
    return rewritten
