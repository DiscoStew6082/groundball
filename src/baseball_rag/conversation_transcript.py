"""Typed transcript facts used for conversation follow-up resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from baseball_rag.provenance import StructuredAnswer


@dataclass(frozen=True)
class TranscriptRow:
    """A normalized source row that can identify a player."""

    facts: Mapping[str, Any]
    player_name: str


@dataclass(frozen=True)
class TranscriptSource:
    """A normalized answer source with follow-up relevant rows."""

    type: str | None
    label: str | None
    rows: tuple[TranscriptRow, ...]


@dataclass(frozen=True)
class TranscriptTurn:
    """A normalized conversation turn accepted from API or UI adapters."""

    question: str | None
    metadata: Mapping[str, Any]
    sources: tuple[TranscriptSource, ...]


def normalize_transcript(
    conversation: Sequence[Mapping[str, Any]] | None,
) -> tuple[TranscriptTurn, ...]:
    """Return typed transcript facts, ignoring malformed adapter entries."""
    if not conversation:
        return ()
    turns: list[TranscriptTurn] = []
    for raw_turn in conversation:
        if not isinstance(raw_turn, Mapping):
            continue
        answer_payload = _answer_payload(raw_turn)
        if answer_payload is None:
            continue
        question = raw_turn.get("question")
        metadata = answer_payload.get("metadata")
        turns.append(
            TranscriptTurn(
                question=question if isinstance(question, str) else None,
                metadata=metadata if isinstance(metadata, Mapping) else {},
                sources=_normalize_sources(answer_payload.get("sources")),
            )
        )
    return tuple(turns)


def active_player_from_recent_turn(
    transcript: Sequence[TranscriptTurn],
) -> tuple[str | None, str | None]:
    """Return the most recent explicit active player, if one exists."""
    for turn in reversed(transcript):
        player_name = turn.metadata.get("context_player_name")
        if isinstance(player_name, str) and player_name.strip():
            return player_name.strip(), turn.question
    return None, None


def row_from_recent_turn(
    transcript: Sequence[TranscriptTurn],
    row_index: int,
) -> tuple[Mapping[str, Any] | None, str | None]:
    """Return the requested recent player row from normalized transcript facts."""
    for turn in reversed(transcript):
        player_rows = [row for source in turn.sources for row in source.rows]
        if player_rows and len(player_rows) <= row_index:
            return None, None
        if not player_rows:
            continue
        return player_rows[row_index].facts, turn.question
    return None, None


def player_name_from_row(row: Mapping[str, Any]) -> str | None:
    """Return a display player name from supported transcript row keys."""
    raw_name = row.get("name") or row.get("player_name") or row.get("full_name")
    if raw_name is None:
        first_name = row.get("nameFirst")
        last_name = row.get("nameLast")
        if isinstance(first_name, str) and isinstance(last_name, str):
            raw_name = f"{first_name.strip()} {last_name.strip()}"
    if not isinstance(raw_name, str) or raw_name.strip() == "":
        return None
    name = raw_name.strip()
    if "," in name:
        last, first = [part.strip() for part in name.split(",", 1)]
        if first and last:
            return f"{first} {last}"
    return name


def _answer_payload(turn: Mapping[str, Any]) -> Mapping[str, Any] | None:
    answer_payload = turn.get("answer")
    if isinstance(answer_payload, StructuredAnswer):
        answer_payload = answer_payload.to_dict()
    return answer_payload if isinstance(answer_payload, Mapping) else None


def _normalize_sources(raw_sources: object) -> tuple[TranscriptSource, ...]:
    if not isinstance(raw_sources, Sequence) or isinstance(raw_sources, str | bytes):
        return ()
    sources: list[TranscriptSource] = []
    for raw_source in raw_sources:
        if not isinstance(raw_source, Mapping):
            continue
        rows = _normalize_rows(raw_source.get("rows"))
        sources.append(
            TranscriptSource(
                type=raw_source.get("type") if isinstance(raw_source.get("type"), str) else None,
                label=raw_source.get("label") if isinstance(raw_source.get("label"), str) else None,
                rows=rows,
            )
        )
    return tuple(sources)


def _normalize_rows(raw_rows: object) -> tuple[TranscriptRow, ...]:
    if not isinstance(raw_rows, Sequence) or isinstance(raw_rows, str | bytes):
        return ()
    rows: list[TranscriptRow] = []
    for raw_row in raw_rows:
        if not isinstance(raw_row, Mapping):
            continue
        player_name = player_name_from_row(raw_row)
        if player_name is None:
            continue
        rows.append(TranscriptRow(facts=raw_row, player_name=player_name))
    return tuple(rows)
