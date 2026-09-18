"""Shared player identity authority backed by Lahman people data."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import duckdb
from unidecode import unidecode

_SINGLE_CANDIDATE_SUFFIX_ALIASES: dict[tuple[str, str], str] = {
    ("ronald acuna", "jr"): "acunaro01",
}


@dataclass(frozen=True)
class PlayerCandidate:
    """A possible player identity for a user-provided name."""

    player_id: str
    full_name: str
    debut: str | None
    final_game: str | None
    retro_id: str | None = None


@dataclass(frozen=True)
class PlayerResolution:
    """Result of resolving a user-provided name to local player identities."""

    query: str
    candidates: list[PlayerCandidate]

    @property
    def player_id(self) -> str | None:
        return self.candidates[0].player_id if len(self.candidates) == 1 else None

    @property
    def player(self) -> PlayerCandidate | None:
        return self.candidates[0] if len(self.candidates) == 1 else None

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


def resolve_player_by_name(name: str, conn: duckdb.DuckDBPyConnection) -> PlayerResolution:
    """Resolve a player name without silently choosing among ambiguous matches."""
    requested_suffix = _requested_suffix(name)
    normalized = _normalize_for_sql(name)
    if not normalized:
        return PlayerResolution(query=name, candidates=[])

    exact_rows = conn.execute(
        f"""
        SELECT playerID, nameFirst || ' ' || nameLast AS full_name, debut, finalGame,
               {_retroid_select_expr(conn)}
        FROM people
        WHERE strip_accents(LOWER(nameFirst || ' ' || nameLast)) = ?
        ORDER BY debut NULLS LAST, playerID
        LIMIT 20
        """,
        [normalized],
    ).fetchall()
    if exact_rows:
        return PlayerResolution(
            query=name,
            candidates=_disambiguate_suffix(
                [_candidate(row) for row in exact_rows],
                requested_suffix,
                normalized,
            ),
        )

    parts = normalized.split()
    if len(parts) < 2:
        rows = conn.execute(
            f"""
            SELECT playerID, nameFirst || ' ' || nameLast AS full_name, debut, finalGame,
                   {_retroid_select_expr(conn)}
            FROM people
            WHERE strip_accents(LOWER(nameLast)) = ?
            ORDER BY debut NULLS LAST, playerID
            LIMIT 20
            """,
            [normalized],
        ).fetchall()
        return PlayerResolution(query=name, candidates=[_candidate(row) for row in rows])

    first, last = parts[0], " ".join(parts[1:])
    rows = conn.execute(
        f"""
        SELECT playerID, nameFirst || ' ' || nameLast AS full_name, debut, finalGame,
               {_retroid_select_expr(conn)}
        FROM people
        WHERE strip_accents(LOWER(nameLast)) = ?
          AND strip_accents(LOWER(nameFirst)) LIKE ?
        ORDER BY debut NULLS LAST, playerID
        LIMIT 20
        """,
        [last, f"{first}%"],
    ).fetchall()
    return PlayerResolution(
        query=name,
        candidates=_disambiguate_suffix(
            [_candidate(row) for row in rows],
            requested_suffix,
            normalized,
        ),
    )


@dataclass(frozen=True)
class PlayerMention:
    """An explicit full-name mention grounded in the same people identity authority."""

    start: int
    end: int
    resolution: PlayerResolution


@lru_cache(maxsize=1)
def _known_full_names(connection: duckdb.DuckDBPyConnection) -> frozenset[str]:
    return frozenset(
        _mention_text(str(row[0]))
        for row in connection.execute("SELECT nameFirst || ' ' || nameLast FROM people").fetchall()
        if row[0]
    )


def _mention_text(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", unidecode(value).lower())


def find_player_mentions(text: str, conn: duckdb.DuckDBPyConnection) -> list[PlayerMention]:
    """Find explicit published full names, preserving suffixes and source spans.

    This is grounding for validation, not intent routing or a fuzzy entity guess.
    Unknown names remain the responsibility of the normal identity resolver.
    """
    names = _known_full_names(conn)
    tokens = list(re.finditer(r"\S+", text))
    words = [_mention_text(token.group()) for token in tokens]
    mentions = []
    for start in range(len(words)):
        for end in range(start + 2, min(start + 6, len(words)) + 1):
            name = " ".join(words[start:end])
            if name not in names:
                continue
            if end < len(words) and words[end] in {"jr", "sr", "ii", "iii", "iv"}:
                name += " " + words[end]
                end += 1
            mentions.append(
                PlayerMention(
                    tokens[start].start(), tokens[end - 1].end(), resolve_player_by_name(name, conn)
                )
            )
    return [
        mention
        for mention in mentions
        if not any(
            other.start <= mention.start
            and other.end >= mention.end
            and other.end - other.start > mention.end - mention.start
            for other in mentions
        )
    ]


def resolve_retrosheet_id(
    conn: duckdb.DuckDBPyConnection,
    player_id: str,
) -> tuple[str | None, str | None]:
    """Resolve the optional Retrosheet ID for a Lahman player."""
    if not _table_exists(conn, "people"):
        return None, "Retrosheet verification requires people.retroID mapping."
    if "retroid" not in _table_columns(conn, "people"):
        return None, "Retrosheet verification requires people.retroID mapping."

    row = conn.execute(
        "SELECT retroID FROM people WHERE playerID = ?",
        [player_id],
    ).fetchone()
    if row is None or row[0] is None or str(row[0]).strip() == "":
        return None, f"No people.retroID mapping exists for Lahman playerID {player_id!r}."
    return str(row[0]), None


def _candidate(row: tuple) -> PlayerCandidate:
    return PlayerCandidate(
        player_id=str(row[0]),
        full_name=str(row[1]),
        debut=str(row[2]) if row[2] else None,
        final_game=str(row[3]) if row[3] else None,
        retro_id=str(row[4]) if len(row) > 4 and row[4] else None,
    )


def _retroid_select_expr(conn: duckdb.DuckDBPyConnection) -> str:
    return "retroID" if "retroid" in _table_columns(conn, "people") else "NULL AS retroID"


def _normalize_for_sql(value: str) -> str:
    suffixes = {"jr", "sr", "ii", "iii", "iv"}
    parts = [p for p in value.strip().split() if p.lower().rstrip(".") not in suffixes]
    folded = unidecode(unicodedata.normalize("NFD", " ".join(parts))).lower()
    return re.sub(r"[^a-z ]+", "", folded).strip()


def _requested_suffix(value: str) -> str | None:
    parts = value.strip().split()
    if not parts:
        return None
    suffix = parts[-1].lower().rstrip(".")
    return suffix if suffix in {"jr", "sr", "ii", "iii", "iv"} else None


def _disambiguate_suffix(
    candidates: list[PlayerCandidate],
    requested_suffix: str | None,
    normalized_name: str,
) -> list[PlayerCandidate]:
    if requested_suffix is None:
        return candidates
    if len(candidates) < 2:
        expected_player_id = _SINGLE_CANDIDATE_SUFFIX_ALIASES.get(
            (normalized_name, requested_suffix)
        )
        if candidates and candidates[0].player_id == expected_player_id:
            return candidates
        return []
    ordered = sorted(candidates, key=lambda candidate: candidate.debut or "")
    if requested_suffix == "sr":
        return [ordered[0]]
    if requested_suffix == "jr":
        return [ordered[-1]]
    roman_index = {"ii": 1, "iii": 2, "iv": 3}[requested_suffix]
    return [ordered[roman_index]] if len(ordered) > roman_index else candidates


def _table_exists(conn: duckdb.DuckDBPyConnection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = ? LIMIT 1",
        [table],
    ).fetchone()
    return row is not None


def _table_columns(conn: duckdb.DuckDBPyConnection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]).casefold() for row in rows}
