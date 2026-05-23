"""Historical MLB franchise location/name changes for query-time context injection.

The LLM doesn't reliably know that e.g. "the Braves in 1936" means the Boston Braves
(BSN), not the Atlanta Braves (ATL). This module provides plain-English hints that get
appended to grounded database questions before SQL generation so the LLM can reason
correctly.
"""

from __future__ import annotations

import re

from baseball_rag.db.freeform_types import TeamIdentity

# ---------------------------------------------------------------------------
# Franchise history: {team_nickname} -> list of (start_year, end_year, team_id)
# ---------------------------------------------------------------------------
# Years are inclusive. A query in year Y for a given nickname uses whichever
# entry covers Y.

_FRANCHISE_HISTORY: dict[str, list[tuple[int, int, str]]] = {
    "braves": [
        # (from_year, through_year, team_id)
        (1871, 1952, "BSN"),  # Boston Braves
        (1953, 1965, "ML1"),  # Milwaukee Braves
        (1966, 2030, "ATL"),  # Atlanta Braves
    ],
    "athletics": [
        (1901, 1954, "PHA"),  # Philadelphia Athletics
        (1955, 1967, "KC1"),  # Kansas City Athletics
        (1968, 2030, "OAK"),  # Oakland Athletics
    ],
    "dodgers": [
        (1890, 1957, "BRO"),  # Brooklyn Dodgers
        (1958, 2030, "LAN"),  # Los Angeles Dodgers
    ],
    "giants": [
        (1883, 1957, "NY1"),  # New York Giants (NL)
        (1958, 2030, "SFN"),  # San Francisco Giants
    ],
    "rangers": [
        (1961, 1971, "WS2"),  # Washington Senators (original AL expansion)
        (1972, 2030, "TEX"),  # Texas Rangers
    ],
    "twins": [
        (1901, 1960, "WS1"),  # Washington Senators
        (1961, 2030, "MIN"),  # Minnesota Twins
    ],
    "orioles": [
        (1901, 1953, "SLA"),  # St. Louis Browns
        (1954, 2030, "BAL"),  # Baltimore Orioles
    ],
    "marlins": [
        (1993, 2011, "FLO"),  # Florida Marlins
        (2012, 2030, "MIA"),  # Miami Marlins (same code, different name)
    ],
    "angels": [
        (1961, 1964, "LAA"),  # Los Angeles Angels
        (1965, 1996, "CAL"),  # California Angels
        (1997, 2004, "ANA"),  # Anaheim Angels
        (2005, 2030, "LAA"),  # Los Angeles Angels
    ],
}

# Teams that did not exist before the given year — useful for negative context.
_ANACHRONISTIC_TEAMS: dict[str, int] = {
    # team_id -> earliest season
    "ATL": 1966,
    "SEA": 1977,
    "TOR": 1977,
    "MIL": 1969,
    "COL": 1993,
    "ARI": 1998,
    "TBD": 1998,
    "TEX": 1972,
    "MIN": 1961,
    "SDN": 1969,
    "SFN": 1958,
    "LAN": 1958,
    "OAK": 1968,
    "KCA": 1955,
    "MON": 1969,
}


def _team_id_for_year(nickname: str, year: int) -> str | None:
    """Return the team_id for a nickname in a given year, or None if not found."""
    entries = _FRANCHISE_HISTORY.get(nickname.lower())
    if not entries:
        return None
    for start, end, code in entries:
        if start <= year <= end:
            return code
    return None


def resolve_team_identity(
    question: str,
    *,
    team_name_pattern: str | None,
    year: int | None,
) -> TeamIdentity | None:
    """Resolve a historical team nickname to a Lahman teamID for a season."""
    if year is None:
        return None

    candidates: list[str] = []
    if team_name_pattern:
        candidates.append(team_name_pattern)
    candidates.extend(_FRANCHISE_HISTORY)

    lower_q = question.lower()
    for candidate in candidates:
        nickname = candidate.lower().strip()
        if nickname not in _FRANCHISE_HISTORY:
            continue
        if not re.search(rf"\b{re.escape(nickname)}s?\b", lower_q):
            continue
        team_id = _team_id_for_year(nickname, year)
        if team_id is None:
            continue
        return TeamIdentity(nickname=nickname, year=year, team_id=team_id)

    return None


def get_contextual_hint(question: str, year: int | None) -> str:
    """Build a plain-English hint about team locations based on the question and year.

    Detects mentions of historically-sensitive team nicknames (braves, athletics,
    dodgers, giants, rangers, twins, orioles, marlins, angels) and appends a
    brief reminder of which city/location the team was in for the given year.
    """
    if year is None:
        return ""

    lower_q = question.lower()

    hints: list[str] = []

    # Check each historically-sensitive nickname — only if the nickname (or its
    # plural) actually appears as a whole word in the question.
    for nickname, entries in _FRANCHISE_HISTORY.items():
        # Build match candidates: "braves", "athletics" etc. and also bare stem
        plurals = {nickname, f"{nickname}s"}
        if not any(word in lower_q.split() for word in plurals):
            continue

        code = _team_id_for_year(nickname, year)
        if code is None:
            continue

        # Derive a readable city name from the team ID
        city_map: dict[str, str] = {
            "BSN": "Boston",
            "ML1": "Milwaukee",
            "ATL": "Atlanta",
            "PHA": "Philadelphia",
            "KC1": "Kansas City",
            "OAK": "Oakland",
            "BRO": "Brooklyn",
            "LAN": "Los Angeles",
            "NY1": "New York (Giants)",
            "SFN": "San Francisco",
            "WS2": "Washington Senators (1961-71)",
            "TEX": "Texas",
            "WS1": "Washington Senators (1901-60)",
            "MIN": "Minnesota",
            "SLA": "St. Louis Browns",
            "BAL": "Baltimore",
            "FLO": "Florida",
            "MIA": "Miami",
            "LAA": "Los Angeles Angels",
            "CAL": "California",
            "ANA": "Anaheim",
        }
        city = city_map.get(code, code)

        # Build the hint
        if nickname == "athletics":
            team_word = "Athletics"
        elif nickname == "rangers":
            team_word = "Rangers"
        else:
            team_word = nickname.capitalize()

        hints.append(f"The {team_word} were in {city} in {year} (code: {code}).")

    # Also warn about anachronistic teams
    for code, earliest in _ANACHRONISTIC_TEAMS.items():
        if year < earliest and code.lower() in lower_q:
            hints.append(f"{code} did not exist until {earliest} — check the team name or year.")

    return " ".join(hints)
