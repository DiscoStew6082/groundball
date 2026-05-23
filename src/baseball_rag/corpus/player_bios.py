"""Resolve baseball player identities from DuckDB data."""

from dataclasses import dataclass

import duckdb


@dataclass(frozen=True)
class PlayerCandidate:
    """A possible player identity for a user-provided name."""

    player_id: str
    full_name: str
    debut: str | None
    final_game: str | None


@dataclass(frozen=True)
class PlayerResolution:
    """Result of resolving a user-provided name to local player identities."""

    query: str
    candidates: list[PlayerCandidate]

    @property
    def player_id(self) -> str | None:
        return self.candidates[0].player_id if len(self.candidates) == 1 else None

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


def get_player_id_by_name(name: str, conn: duckdb.DuckDBPyConnection) -> str | None:
    """Look up a player's ID by their name.

    Args:
        name: Full name or partial name to search for
        conn: A DuckDB connection

    Returns:
        The playerID if found, or None
    """
    return resolve_player_by_name(name, conn).player_id


def resolve_player_by_name(name: str, conn: duckdb.DuckDBPyConnection) -> PlayerResolution:
    """Resolve a player name without silently choosing among ambiguous matches."""
    normalized = _normalize_for_sql(name)
    if not normalized:
        return PlayerResolution(query=name, candidates=[])

    exact_rows = conn.execute(
        """
        SELECT playerID, nameFirst || ' ' || nameLast AS full_name, debut, finalGame
        FROM people
        WHERE strip_accents(LOWER(nameFirst || ' ' || nameLast)) = ?
        ORDER BY debut NULLS LAST, playerID
        LIMIT 20
        """,
        [normalized],
    ).fetchall()
    if exact_rows:
        return PlayerResolution(query=name, candidates=[_candidate(row) for row in exact_rows])

    parts = normalized.split()
    if len(parts) < 2:
        rows = conn.execute(
            """
            SELECT playerID, nameFirst || ' ' || nameLast AS full_name, debut, finalGame
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
        """
        SELECT playerID, nameFirst || ' ' || nameLast AS full_name, debut, finalGame
        FROM people
        WHERE strip_accents(LOWER(nameLast)) = ?
          AND strip_accents(LOWER(nameFirst)) LIKE ?
        ORDER BY debut NULLS LAST, playerID
        LIMIT 20
        """,
        [last, f"{first}%"],
    ).fetchall()
    return PlayerResolution(query=name, candidates=[_candidate(row) for row in rows])


def _candidate(row: tuple) -> PlayerCandidate:
    return PlayerCandidate(
        player_id=str(row[0]),
        full_name=str(row[1]),
        debut=str(row[2]) if row[2] else None,
        final_game=str(row[3]) if row[3] else None,
    )


def _normalize_for_sql(value: str) -> str:
    import re
    import unicodedata

    from unidecode import unidecode

    suffixes = {"jr", "sr", "ii", "iii", "iv"}
    parts = [p for p in value.strip().split() if p.lower().rstrip(".") not in suffixes]
    folded = unidecode(unicodedata.normalize("NFD", " ".join(parts))).lower()
    return re.sub(r"[^a-z ]+", "", folded).strip()
