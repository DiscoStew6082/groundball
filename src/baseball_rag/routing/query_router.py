"""Query routing - classify user intent and extract structured arguments via LLM.

Architecture
============
The router uses an LLM to classify user queries into one of four intents, then
extracts structured parameters from the natural language. The extracted fields
are deliberately rich — particularly the time_period field, which replaces a
simple "year: int | None" with a discriminated union covering:

  - single   : a specific year          → {"type": "single",    "value": 1972}
  - decade   : a named decade           → {"type": "decade",     "value": 70}   # 1970-1979
  - range    : an explicit year span    → {"type": "range",      "value": [1960, 1980]}
  - relative : last/next/past + unit →
      {"type": "relative", "value": {"direction": "past", "unit": "year", "count": 2}}

This matters because natural language time expressions are compositional and
ambiguous. A scalar year field can't capture "seventies" or "between 1960-80"
without an ever-growing list of special-case fields (decade, start_year,
end_year...). A discriminated union keeps the schema fixed as new time types
are added — just a new "type" variant and one handler in the dispatch.

The routing prompt teaches the LLM these types through examples. If a query
doesn't match any type the LLM is unsure, it returns null for time_period,
and the CLI falls back to career-level results (no time filter).
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from baseball_rag.arch.tracing import traced
from baseball_rag.db.stat_registry import (
    find_stat_in_text,
    normalize_stat,
    supported_stat_prompt_list,
)
from baseball_rag.generation.json_parsing import extract_json_blocks, strip_markdown_fence


class TimePeriodType(str, Enum):
    """Discriminated union tag for time period extraction.

    Each variant represents a structurally distinct way users express time:
      single    - A specific year: "1972", "last year" (resolved to an integer)
      decade    - A named decade: "seventies", "the 1980s"
      range     - An explicit span: "1960-1980", "from 1990 to 2000"
      relative  - Relative offset: "past 5 years", "next 3 seasons"

    Using an Enum (rather than a bare str) enforces exhaustive matching in
    downstream dispatch logic — adding a new variant forces all `match`
    statements to handle it or raise a compile/runtime error.
    """

    SINGLE = "single"
    DECADE = "decade"
    RANGE = "range"
    RELATIVE = "relative"


@dataclass
class TimePeriod:
    """Extracted time filter from a natural language query.

    Attributes
    ----------
    type : TimePeriodType
        Discriminant that determines which field holds the actual value.
    value : int | list[int] | dict
        The payload — interpretation depends on ``type``:

        - single    → int year (e.g. 1972)
        - decade    → int decade number, 0-99 (e.g. 70 for 1970s)
        - range     → [start_year, end_year] list of two ints
        - relative  → {"direction": "past"|"future", "unit": str, "count": int}
                      e.g. {"direction": "past", "unit": "year", "count": 5} for
                      "past 5 years".  Unit may be "year", "season", "decade".

    resolved_start : int | None
        After resolution: the concrete start year. Populated by cli.py when
        handling the route, not extracted from the LLM directly (the LLM only
        provides ``value``). This avoids forcing the model to do calendar math.

    resolved_end : int | None
        After resolution: the concrete end year (inclusive).

    Examples
    --------
    >>> tp = TimePeriod(type=TimePeriodType.DECADE, value=70)
    >>> tp.resolved_start, tp.resolved_end
    (None, None)          # not yet resolved — cli.py fills these

    A fully-resolved range:
    >>> tp = TimePeriod(
    ...     type=TimePeriodType.RANGE,
    ...     value=[1960, 1980],
    ...     resolved_start=1960,
    ...     resolved_end=1980
    ... )
    """

    type: TimePeriodType = TimePeriodType.SINGLE
    # int | list[int] | dict — typed more precisely via discriminated union below
    value: int | list[int] | dict = field(default_factory=lambda: 0)
    # Concrete years filled in by cli.py after extraction
    resolved_start: int | None = None
    resolved_end: int | None = None


@dataclass
class RouteResult:
    """Parsed result from classifying a user query."""

    intent: str  # "stat_query" | "player_biography" | "freeform_query" | "general_explanation"
    stat: str | None  # e.g., "RBI", "HR"
    time_period: TimePeriod | None = None  # extracted time filter (replaces old year field)
    position: str | None = None  # e.g., "OF", "CF"
    player_name: str | None = None  # e.g., "Mike Trout"
    raw_question: str = ""  # original question text

    @property
    def year(self) -> int | None:
        """Backward-compatibility shim.

        Legacy code and tests pass ``year=int`` directly. This property extracts
        the year from a SINGLE time_period so existing call sites don't break::

            decision.year   ← still works on RouteResult even though the field
                              is now time_period: TimePeriod | None

        Returns None if the query used a range, decade, or relative period.
        """
        if self.time_period is None:
            return None
        if self.time_period.type == TimePeriodType.SINGLE and isinstance(
            self.time_period.value, int
        ):
            return self.time_period.value
        return None


_ROUTING_PROMPT = (
    "You are a baseball query classifier. Given a user question, "
    "respond with ONLY valid JSON (no markdown, no explanation).\n\n"
    "Identify:\n"
    "- intent: 'stat_query' if asking about a specific stat for a player or "
    "league-wide leaders; 'player_biography' if asking about a player's "
    "career history, teams, biographical info (e.g., 'who was Wally Pipp', "
    "'what teams did he play for', 'tell me about this player'); "
    "'freeform_query' if the question requires data from the database — "
    "including award winners, historical achievements, records, career "
    "leaders across multiple stats or seasons (e.g., 'who won the Triple Crown', "
    "'list all MVP winners in the 1970s', 'who has the most HRs ever'); "
    "'general_explanation' only for questions about baseball rules, terminology, "
    "or concepts that do not require querying player statistics\n"
    "- stat: the canonical stat name if detectable (RBI, HR, AVG, ERA, WHIP, SO, SB, 2B,"
    " 3B, W, L, PO, etc.); null otherwise\n"
    "- time_period: a time filter object with 'type' and 'value'. Types:\n"
    "  - single   : a specific year — value is an integer (e.g. 1972)\n"
    "  - decade   : a named decade  — value is the decade number 0-99 "
    "(e.g. 70 for 'seventies' or '1970s', 80 for '80s')\n"
    "  - range    : an explicit year span — value is [start_year, end_year]\n"
    "  - relative : a past/future offset — value is {{direction: 'past'|'future', "
    "unit: 'year'|'season'|'decade', count: integer}}\n"
    "  - null if no time filter is present\n"
    "- position: 'OF' or 'CF' etc. if a defensive position is specified; null otherwise\n"
    "- player_name: the full player name if one is mentioned "
    '(e.g., "Ronald Acuna Jr."); null otherwise\n\n'
    f"Stat name mapping: {', '.join(supported_stat_prompt_list())}\n"
    "Never guess — return null for any field not explicitly in the question.\n\n"
    "Examples:\n"
    '- "who led MLB in RBIs in 2022" → '
    '{{"intent":"stat_query","stat":"RBI","time_period":{{"type":"single","value":2022}},'
    '"position":null,"player_name":null}}\n'
    '- "most HRs in the seventies" → '
    '{{"intent":"stat_query","stat":"HR","time_period":{{"type":"decade","value":70}},'
    '"position":null,"player_name":null}}\n'
    '- "who had most RBIs between 1960-1980" → '
    '{{"intent":"stat_query","stat":"RBI","time_period":{{"type":"range","value":[1960,1980]}},'
    '"position":null,"player_name":null}}\n'
    '- "how many HRs did Aaron Judge have last year" → '
    '{{"intent":"stat_query","stat":"HR","time_period":{{"type":"relative",'
    '"value":{{"direction":"past","unit":"year","count":1}}}},'
    '"position":null,"player_name":"Aaron Judge"}}\n'
    '- "who was Wally Pipp" → '
    '{{"intent":"player_biography","stat":null,"time_period":null,'
    '"position":null,"player_name":"Wally Pipp"}}\n'
    '- "what teams did he play for" → '
    '{{"intent":"player_biography","stat":null,"time_period":null,'
    '"position":null,"player_name":null}}\n'
    "- 'tell me about this player' → "
    '{{"intent":"player_biography","stat":null,"time_period":null,'
    '"position":null,"player_name":null}}\n'
    "- 'what is a forced play in baseball' → "
    '{{"intent":"general_explanation","stat":null,"time_period":null,'
    '"position":null,"player_name":null}}\n'
    '- "who played for the Braves in 1936" → '
    '{{"intent":"freeform_query","stat":null,"time_period":{{"type":"single","value":1936}},'
    '"position":null,"player_name":null}}\n'
    '- "list all pitchers with over 300 wins" → '
    '{{"intent":"freeform_query","stat":null,"time_period":null,'
    '"position":null,"player_name":null}}\n'
    '- "who won the Triple Crown and which years" → '
    '{{"intent":"freeform_query","stat":null,"time_period":null,'
    '"position":null,"player_name":null}}\n'
    "\nQuestion: {question}"
)


def _extract_json_blocks(text: str) -> list[tuple[int, int]]:
    """Backward-compatible wrapper for tests importing the private helper."""
    return extract_json_blocks(text)


def _parse_llm_json(raw: str) -> dict | None:
    """Parse LLM JSON response.

    Gemma 4 often wraps its output in a reasoning/thinking block even when
    instructed to return only JSON. We find the {...} block that actually
    parses as valid RouteResult-shaped JSON.
    """
    text = strip_markdown_fence(raw)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find all {...} blocks and try each one
    for start, end in _extract_json_blocks(text):
        candidate = text[start:end]
        try:
            data = json.loads(candidate)
            # Sanity-check: must have 'intent' field
            if isinstance(data, dict) and "intent" in data:
                return data
        except json.JSONDecodeError:
            continue

    return None


@traced(component_id="query-router", label="Route Query")
def route(question: str) -> RouteResult:
    """Classify a natural language question using the LLM.

    Falls back to a simple heuristic if LM Studio is unavailable.
    """
    if _looks_like_player_bio_followup(question):
        return RouteResult(
            intent="player_biography",
            stat=None,
            time_period=None,
            position=None,
            player_name=None,
            raw_question=question,
        )

    player_bio_name = _extract_player_bio_name_heuristic(question)
    if player_bio_name is not None:
        return RouteResult(
            intent="player_biography",
            stat=None,
            time_period=None,
            position=None,
            player_name=player_bio_name,
            raw_question=question,
        )

    if _should_use_deterministic_freeform_route(question):
        return RouteResult(
            intent="freeform_query",
            stat=None,
            time_period=None,
            position=None,
            player_name=None,
            raw_question=question,
        )

    deterministic = _heuristic_route(question)
    if (
        deterministic.intent == "stat_query"
        and deterministic.stat is not None
        and (_should_use_deterministic_stat_route(question) or deterministic.player_name)
    ):
        return deterministic

    try:
        from baseball_rag.generation.llm import make_request

        prompt = _ROUTING_PROMPT.format(question=question)
        response = make_request(prompt, max_tokens=500, temperature=0.1)
        data = _parse_llm_json(response.content)

        if data and data.get("intent") in (
            "stat_query",
            "player_biography",
            "freeform_query",
            "general_explanation",
        ):
            time_period_data = data.get("time_period")
            time_period: TimePeriod | None = _build_time_period(time_period_data)

            return RouteResult(
                intent=data["intent"],
                stat=normalize_stat(data["stat"]) if data.get("stat") else None,
                time_period=time_period,
                position=data.get("position"),
                player_name=data.get("player_name"),
                raw_question=question,
            )
    except ConnectionError:
        pass  # Fall through to heuristic

    # LM Studio unavailable or LLM returned garbled — use safe fallback
    return _heuristic_route(question)


def _build_time_period(data: dict | None) -> TimePeriod | None:
    """Convert a raw time_period JSON dict from the LLM into a typed TimePeriod.

    Parameters
    ----------
    data : dict | None
        The ``time_period`` field parsed from the routing prompt's JSON output.
        Shape depends on type::

            {"type": "single",   "value": 1972}
            {"type": "decade",   "value": 70}
            {"type": "range",    "value": [1960, 1980]}
            {"type": "relative", "value": {"direction": "past", "unit": "year", "count": 1}}

        May also be None if the LLM determined no time filter was present.

    Returns
    -------
    TimePeriod | None
        Typed TimePeriod instance. The ``resolved_start`` / ``resolved_end``
        fields are left as None here — cli.py fills them after extracting a
        concrete year range based on type.
    """
    if data is None:
        return None

    try:
        period_type = TimePeriodType(data.get("type"))
    except ValueError:
        # Unknown type — degrade gracefully rather than crashing
        return None

    raw_value: Any = data.get("value")
    return TimePeriod(type=period_type, value=raw_value)  # type: ignore[arg-type]


def _heuristic_route(question: str) -> RouteResult:
    """Fallback routing when the LLM is unavailable.

    Only handles explicit leaderboard queries (who had most/least/top N).
    Player-specific stat lookups always go through the LLM path.
    """
    import re

    # Only classify as stat_query if it's clearly a league-wide leader request
    lower_q = question.lower()
    leader_re = re.compile(
        r"\b(career|most|least|highest|lowest|lead|leader|leaders|top|bottom|best)\b"
    )
    is_leaderboard = bool(leader_re.search(lower_q))

    # Extract explicit ranges before single years.
    range_match = re.search(r"\b(20\d{2}|19\d{2})\s*[-–]\s*(20\d{2}|19\d{2})\b", question)
    year_range: list[int] | None = None
    if range_match:
        year_range = [int(range_match.group(1)), int(range_match.group(2))]

    # Extract decade from "70s", "1970s", or word forms like "seventies"
    decade_words = {
        "nineteen-hundreds": 0,
        "nineteen hundreds": 0,
        "aughts": 0,
        "tens": 10,
        "twenties": 20,
        "thirties": 30,
        "forties": 40,
        "fifties": 50,
        "sixties": 60,
        "seventies": 70,
        "eighties": 80,
        "nineties": 90,
    }
    decade: int | None = None
    m = re.search(r"\b((?:19)?(\d{2})s)\b", question, re.IGNORECASE)
    if m:
        decade = int(m.group(2))
    else:
        # Try word forms: "seventies", "eighties", etc.
        for words, val in decade_words.items():
            if words in lower_q:
                decade = val
                break

    # Extract a 4-digit year as last resort (fallback only — prefer decade above)
    year: int | None = None
    m = re.search(r"\b(20\d{2}|19\d{2})\b", question)
    if m:
        year = int(m.group(1))

    stat = find_stat_in_text(question)

    player_name = _extract_player_name_heuristic(question)

    # Build the most specific time_period available
    if year_range is not None:
        time_period = TimePeriod(type=TimePeriodType.RANGE, value=year_range)
    elif decade is not None:
        time_period = TimePeriod(type=TimePeriodType.DECADE, value=decade)
    elif year is not None:
        time_period = TimePeriod(type=TimePeriodType.SINGLE, value=year)
    else:
        time_period = None

    return RouteResult(
        intent="stat_query" if is_leaderboard or (stat and player_name) else "general_explanation",
        stat=stat,
        time_period=time_period,
        position=None,
        player_name=player_name,
        raw_question=question,
    )


def _should_use_deterministic_stat_route(question: str) -> bool:
    """Return True for simple leaderboard phrasing the heuristic can safely own."""
    lower_q = question.lower()
    leaderboard_terms = (
        "most",
        "least",
        "highest",
        "lowest",
        "lead",
        "leader",
        "leaders",
        "top",
        "bottom",
        "best",
    )
    return any(term in lower_q for term in leaderboard_terms)


def _should_use_deterministic_freeform_route(question: str) -> bool:
    """Return True for freeform templates that do not need router LLM help."""
    lower_q = question.lower()
    compact = re.sub(r"[^a-z0-9]+", " ", lower_q)

    if "triple crown" in compact:
        return True
    if re.search(r"\b30\s*30\b", compact) or "thirty thirty" in compact:
        return True
    if "500 club" in compact:
        return True
    if ("home run" in compact or "homer" in compact or re.search(r"\bhrs?\b", compact)) and (
        "500" in compact or "club" in compact
    ):
        return True
    if ("pitching" in compact or "pitcher" in compact or "career" in compact) and (
        "wins" in compact and ("leader" in compact or "500" in compact or "300" in compact)
    ):
        return True
    if "era" in compact and (
        "career" in compact
        or "qualified" in compact
        or "qualifying" in compact
        or "enough innings" in compact
        or " innings" in compact
    ):
        return True
    return False


def _extract_player_name_heuristic(question: str) -> str | None:
    """Extract common two-word player-name patterns for stat questions."""
    import re

    possessive = re.search(r"\b([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)'s\b", question)
    if possessive:
        return possessive.group(1)

    did_pattern = re.search(
        r"\b(?:did|does)\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+?)\s+"
        r"(?:hit|have|get|record)\b",
        question,
        re.IGNORECASE,
    )
    if did_pattern:
        return did_pattern.group(1)

    compact_stat_pattern = re.search(
        r"^\s*([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+?)\s+"
        r"(?i:"
        r"rbi|rbis|runs\s+batted\s+in|hr|hrs|home\s+runs?|homers?|"
        r"sb|stolen\s+bases?|avg|batting\s+average|era|whip"
        r")\b",
        question,
    )
    if compact_stat_pattern:
        return compact_stat_pattern.group(1)

    return None


def _extract_player_bio_name_heuristic(question: str) -> str | None:
    """Extract explicit full-name biography questions without LLM routing."""
    patterns = (
        r"^\s*who\s+was\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)\??\s*$",
        r"^\s*tell\s+me\s+about\s+([A-Z][A-Za-z.'-]+(?:\s+[A-Z][A-Za-z.'-]+)+)\.?\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, question)
        if match:
            return match.group(1)
    return None


def _looks_like_player_bio_followup(question: str) -> bool:
    lower_q = question.lower()
    return (
        "team" in lower_q
        and "play" in lower_q
        and any(pronoun in lower_q for pronoun in (" he ", " she ", " they ", " this player"))
    )
