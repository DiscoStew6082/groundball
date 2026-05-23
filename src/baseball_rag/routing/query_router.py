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
doesn't match any type or the LLM is unsure, it returns null for time_period,
and the CLI uses career-level results (no time filter).
"""

import csv
import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

from unidecode import unidecode

from baseball_rag.arch.tracing import traced
from baseball_rag.db.stat_registry import (
    find_stat_in_text,
    normalize_stat,
    supported_stat_prompt_list,
)
from baseball_rag.generation.json_parsing import extract_json_blocks, strip_markdown_fence
from baseball_rag.routing.contracts import (
    GeneralExplanationCase,
    GroundedDatabaseQuestionCase,
    Intent,
    PlayerBiographyCase,
    RoutedCase,
    StatQueryCase,
    TimePeriod,
    TimePeriodType,
    routed_case,
)
from baseball_rag.routing.decisions import RouteDecisionChain
from baseball_rag.routing.grounded_database_ownership import (
    deterministic_grounded_database_owns,
)
from baseball_rag.year_parsing import extract_spelled_year

_NAME_TOKEN_RE = r"[^\W\d_](?:[^\W\d_]|[.'-])*"
_NAME_RE = rf"{_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE})*"

__all__ = [
    "GeneralExplanationCase",
    "GroundedDatabaseQuestionCase",
    "Intent",
    "PlayerBiographyCase",
    "RoutedCase",
    "StatQueryCase",
    "TimePeriod",
    "TimePeriodType",
    "route",
    "routed_case",
]


_ROUTING_PROMPT = (
    "You are a baseball query classifier. Given a user question, "
    "respond with ONLY valid JSON (no markdown, no explanation).\n\n"
    "Identify:\n"
    "- intent: 'stat_query' if asking about a specific stat for a player or "
    "league-wide leaders; 'player_biography' if asking about a player's "
    "career history, teams, biographical info (e.g., 'who was Wally Pipp', "
    "'what teams did he play for', 'tell me about this player'); "
    "'grounded_database_question' if the question requires data from the database — "
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
    '{{"intent":"grounded_database_question","stat":null,"time_period":{{"type":"single","value":1936}},'
    '"position":null,"player_name":null}}\n'
    '- "list all pitchers with over 300 wins" → '
    '{{"intent":"grounded_database_question","stat":null,"time_period":null,'
    '"position":null,"player_name":null}}\n'
    '- "who won the Triple Crown and which years" → '
    '{{"intent":"grounded_database_question","stat":null,"time_period":null,'
    '"position":null,"player_name":null}}\n'
    "\nQuestion: {question}"
)


def _parse_llm_json(raw: str) -> dict | None:
    """Parse LLM JSON response.

    Gemma 4 often wraps its output in a reasoning/thinking block even when
    instructed to return only JSON. We find the {...} block that actually
    parses as valid route JSON.
    """
    text = strip_markdown_fence(raw)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find all {...} blocks and try each one
    for start, end in extract_json_blocks(text):
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
def route(question: str) -> RoutedCase:
    """Classify a natural language question using the LLM.

    Uses a simple heuristic route if LM Studio is unavailable.
    """
    deterministic = _heuristic_route(question)
    return RouteDecisionChain(
        decisions=(
            lambda: _player_bio_followup_route(question),
            lambda: _claim_verification_route(question),
            lambda: _player_bio_name_route(question),
            lambda: _deterministic_route_decision(question, deterministic),
            lambda: _grounded_database_route(question),
        ),
        fallback=lambda: _llm_route_or_heuristic(question, deterministic),
    ).decide()


def _player_bio_followup_route(question: str) -> RoutedCase | None:
    if _looks_like_player_bio_followup(question):
        return routed_case(
            intent="player_biography",
            raw_question=question,
        )
    return None


def _claim_verification_route(question: str) -> RoutedCase | None:
    claim_verification_name = _extract_claim_verification_player_name(question)
    if claim_verification_name is not None:
        return routed_case(
            intent="player_biography",
            player_name=claim_verification_name,
            raw_question=question,
        )
    return None


def _player_bio_name_route(question: str) -> RoutedCase | None:
    player_bio_name = _extract_player_bio_name_heuristic(question)
    if player_bio_name is not None:
        return routed_case(
            intent="player_biography",
            player_name=player_bio_name,
            raw_question=question,
        )
    return None


def _deterministic_route_decision(
    question: str,
    deterministic: RoutedCase,
) -> RoutedCase | None:
    if (
        deterministic.intent == "stat_query"
        and deterministic.stat is not None
        and (_should_use_deterministic_stat_route(question) or deterministic.player_name)
    ):
        if deterministic_grounded_database_owns(
            question,
            competing_stat=deterministic.stat,
        ):
            return routed_case(
                intent="grounded_database_question",
                raw_question=question,
            )
        return deterministic
    if (
        deterministic.intent == "general_explanation"
        and deterministic.stat is not None
        and not _should_use_deterministic_stat_route(question)
    ):
        if deterministic_grounded_database_owns(
            question,
            competing_stat=deterministic.stat,
        ):
            return routed_case(
                intent="grounded_database_question",
                raw_question=question,
            )
        return deterministic
    return None


def _grounded_database_route(question: str) -> RoutedCase | None:
    if deterministic_grounded_database_owns(question):
        return routed_case(
            intent="grounded_database_question",
            raw_question=question,
        )
    return None


def _llm_route_or_heuristic(question: str, deterministic: RoutedCase) -> RoutedCase:
    try:
        from baseball_rag.generation.llm import LLMError, LLMRoutingOutputError, make_request

        prompt = (
            "You are a baseball query classifier. Return only valid JSON.",
            _ROUTING_PROMPT.format(question=question),
        )
        response = make_request(prompt, max_tokens=500, temperature=0.1)
        data = _parse_llm_json(response.content)

        if not isinstance(data, dict):
            raise LLMRoutingOutputError("LLM router output was not a JSON object.")

        if data.get("intent") in (
            "stat_query",
            "player_biography",
            "grounded_database_question",
            "general_explanation",
        ):
            time_period_data = data.get("time_period")
            time_period: TimePeriod | None = _build_time_period(time_period_data)
            raw_stat = data.get("stat")
            if raw_stat is not None and not isinstance(raw_stat, str):
                raise LLMRoutingOutputError("LLM router stat must be a string or null.")
            raw_position = data.get("position")
            if raw_position is not None and not isinstance(raw_position, str):
                raise LLMRoutingOutputError("LLM router position must be a string or null.")
            raw_player_name = data.get("player_name")
            if raw_player_name is not None and not isinstance(raw_player_name, str):
                raise LLMRoutingOutputError("LLM router player_name must be a string or null.")

            return routed_case(
                intent=cast(Intent, data["intent"]),
                stat=normalize_stat(raw_stat) if raw_stat else None,
                time_period=time_period,
                position=raw_position,
                player_name=raw_player_name,
                raw_question=question,
            )
        raise LLMRoutingOutputError("LLM router output did not contain a supported intent.")
    except (ConnectionError, LLMError, ValueError):
        pass  # Fall through to heuristic

    # LM Studio unavailable or LLM returned garbled — use the local heuristic route.
    return deterministic


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
    if not isinstance(data, dict):
        raise ValueError("time_period must be a JSON object or null")

    try:
        period_type = TimePeriodType(data.get("type"))
    except ValueError:
        # Unknown type — degrade gracefully rather than crashing
        return None

    raw_value: Any = data.get("value")
    return TimePeriod(type=period_type, value=raw_value)  # type: ignore[arg-type]


def _heuristic_route(question: str) -> RoutedCase:
    """Heuristic routing when the LLM is unavailable.

    Only handles explicit leaderboard queries (who had most/least/top N).
    Player-specific stat lookups always go through the LLM path.
    """
    import re

    # Only classify as stat_query if it's clearly a league-wide leader request
    lower_q = question.lower()
    leader_re = re.compile(
        r"\b(career|most|least|highest|lowest|lead|leads|led|leader|leaders|top|bottom|best|greatest)\b"
    )
    is_leaderboard = bool(leader_re.search(lower_q))

    # Extract explicit ranges before single years.
    range_match = re.search(
        r"\b(20\d{2}|19\d{2}|18\d{2})\s*[-–]\s*(20\d{2}|19\d{2}|18\d{2})\b",
        question,
    )
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
    full_decade_match = re.search(r"\b((?:18|19|20)\d0)s\b", question, re.IGNORECASE)
    if full_decade_match:
        decade = int(full_decade_match.group(1))
    else:
        m = re.search(r"\b((?:19)?(\d{2})s)\b", question, re.IGNORECASE)
        if m:
            decade = int(m.group(2))
        else:
            # Try word forms: "seventies", "eighties", etc.
            for words, val in decade_words.items():
                if words in lower_q:
                    decade = val
                    break

    # Extract a 4-digit year as a last resort after range and decade parsing.
    year: int | None = None
    m = re.search(r"\b(20\d{2}|19\d{2}|18\d{2})\b", question)
    if m:
        year = int(m.group(1))
    else:
        year = extract_spelled_year(lower_q)

    stat = find_stat_in_text(question)

    player_name = _extract_player_name_heuristic(question)
    position = _extract_position_heuristic(lower_q)

    # Build the most specific time_period available
    if year_range is not None:
        time_period = TimePeriod(type=TimePeriodType.RANGE, value=year_range)
    elif _looks_like_last_year(lower_q):
        time_period = TimePeriod(
            type=TimePeriodType.RELATIVE,
            value={"direction": "past", "unit": "year", "count": 1},
        )
    elif decade is not None:
        time_period = TimePeriod(type=TimePeriodType.DECADE, value=decade)
    elif year is not None:
        time_period = TimePeriod(type=TimePeriodType.SINGLE, value=year)
    else:
        time_period = None

    intent: Intent = (
        "stat_query"
        if stat is not None and (is_leaderboard or player_name)
        else "general_explanation"
    )
    return routed_case(
        intent=intent,
        stat=stat,
        time_period=time_period,
        position=position,
        player_name=player_name,
        raw_question=question,
    )


def _looks_like_last_year(lower_q: str) -> bool:
    return "last year" in lower_q or "last season" in lower_q


def _extract_position_heuristic(lower_q: str) -> str | None:
    """Extract common defensive position phrasing for deterministic fielding queries."""
    position_aliases = [
        ("center field", "OF"),
        ("centre field", "OF"),
        ("centerfielder", "OF"),
        ("center fielder", "OF"),
        ("left field", "OF"),
        ("leftfielder", "OF"),
        ("left fielder", "OF"),
        ("right field", "OF"),
        ("rightfielder", "OF"),
        ("right fielder", "OF"),
        ("outfield", "OF"),
        ("outfielder", "OF"),
        ("catcher", "C"),
        ("first base", "1B"),
        ("second base", "2B"),
        ("third base", "3B"),
        ("shortstop", "SS"),
        ("pitcher", "P"),
    ]
    for text, position in position_aliases:
        if text in lower_q:
            return position
    return None


def _should_use_deterministic_stat_route(question: str) -> bool:
    """Return True for simple leaderboard phrasing the heuristic can safely own."""
    lower_q = question.lower()
    leaderboard_terms = (
        "most",
        "least",
        "highest",
        "lowest",
        "lead",
        "led",
        "leader",
        "leaders",
        "top",
        "bottom",
        "best",
    )
    return any(term in lower_q for term in leaderboard_terms)


def _extract_player_name_heuristic(question: str) -> str | None:
    """Extract common two-word player-name patterns for stat questions."""
    import re

    stat_phrase = (
        r"rbi|rbis|runs\s+batted\s+in|hr|hrs|home\s+runs?|homers?|"
        r"sb|stolen\s+bases?|avg|batting\s+average|era|whip|"
        r"strikeouts?|so|hits?"
    )
    possessive = re.search(rf"\b({_NAME_RE})'s\b", question)
    if possessive:
        candidate = _rightmost_name_phrase(possessive.group(1))
        if candidate is not None and _looks_like_known_player_name(candidate):
            return candidate

    did_pattern = re.search(
        rf"\b(?:did|does)\s+({_NAME_RE})\s+"
        r"(?:hit|have|get|record)\b",
        question,
    )
    if did_pattern:
        candidate = did_pattern.group(1)
        if _looks_like_player_name(candidate):
            return candidate

    stat_subject_pattern = re.search(
        rf"\b(?:what\s+was|what\s+were)\s+({_NAME_RE})\s+"
        rf"(?i:{stat_phrase})\b",
        question,
        flags=re.IGNORECASE,
    )
    if stat_subject_pattern:
        candidate = _rightmost_name_phrase(stat_subject_pattern.group(1))
        if candidate is not None and _looks_like_known_player_name(candidate):
            return candidate

    compact_stat_pattern = re.search(
        rf"^\s*({_NAME_RE})\s+"
        rf"(?i:{stat_phrase})\b",
        question,
    )
    if compact_stat_pattern:
        candidate = compact_stat_pattern.group(1)
        if _looks_like_player_name(candidate) and _looks_like_known_player_name(candidate):
            return candidate

    return None


def _extract_player_bio_name_heuristic(question: str) -> str | None:
    """Extract explicit full-name biography questions without LLM routing."""
    patterns = (
        rf"^\s*who\s+was\s+({_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE})+)\??\s*$",
        rf"^\s*tell\s+me\s+about\s+({_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE})+)\.?\s*$",
        rf"^\s*(?:what|which)\s+teams?\s+did\s+({_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE})+)"
        r"\s+play\s+for\??\s*$",
    )
    for pattern in patterns:
        match = re.search(pattern, question, flags=re.IGNORECASE)
        if match and _looks_like_explicit_player_bio_name(match.group(1)):
            return _normalize_player_name_casing(match.group(1))
    return None


def _extract_claim_verification_player_name(question: str) -> str | None:
    lower_q = question.lower()
    if "duckdb" not in lower_q or "claim" not in lower_q:
        return None
    if not any(term in lower_q for term in ("verified", "verify", "verifiable")):
        return None

    for pattern in (
        rf"^\s*({_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE})+?)"
        r"(?=,|\s+(?:recorded|had|hit|has|was|is)\b)",
        rf"\bthat\s+({_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE})+?)"
        r"(?=\s+(?:recorded|had|hit|has|was|is)\b)",
        rf"\?\s*({_NAME_TOKEN_RE}(?:\s+{_NAME_TOKEN_RE})+?)"
        r"(?=\s+(?:recorded|had|hit|has|was|is)\b)",
    ):
        match = re.search(pattern, question)
        if match and _looks_like_player_name(match.group(1)):
            return _normalize_player_name_casing(match.group(1))
    return _extract_player_bio_name_heuristic(question)


def _looks_like_explicit_player_bio_name(value: str) -> bool:
    tokens = value.split()
    if len(tokens) < 2:
        return False
    if tokens[0].lower() in {"a", "an", "the"}:
        return False
    return _looks_like_player_name(value) or value.islower()


def _normalize_player_name_casing(value: str) -> str:
    """Return title-cased spacing for explicit player-name biography queries."""
    return " ".join(token[:1].upper() + token[1:] for token in value.split())


def _looks_like_player_bio_followup(question: str) -> bool:
    lower_q = question.lower()
    return (
        "team" in lower_q
        and "play" in lower_q
        and any(pronoun in lower_q for pronoun in (" he ", " she ", " they ", " this player"))
    )


def _rightmost_name_phrase(text: str) -> str | None:
    tokens = text.split()
    name_tokens: list[str] = []
    for token in reversed(tokens):
        if not _looks_like_name_token(token):
            break
        name_tokens.append(token)
    if not name_tokens:
        return None
    candidate = " ".join(reversed(name_tokens))
    return candidate if _looks_like_player_name(candidate) else None


def _looks_like_player_name(value: str) -> bool:
    tokens = value.split()
    return bool(tokens) and all(_looks_like_name_token(token) for token in tokens)


def _looks_like_known_player_name(value: str) -> bool:
    normalized = _normalize_player_name_for_lookup(value)
    if normalized in _known_full_player_names():
        return True
    return " " not in normalized and normalized in _known_player_last_names()


def _normalize_player_name_for_lookup(value: str) -> str:
    folded = unidecode(unicodedata.normalize("NFD", value)).lower()
    return re.sub(r"[^a-z0-9]+", " ", folded).strip()


@lru_cache(maxsize=1)
def _known_full_player_names() -> frozenset[str]:
    return frozenset(full_name for full_name, _last_name in _load_player_name_aliases())


@lru_cache(maxsize=1)
def _known_player_last_names() -> frozenset[str]:
    return frozenset(last_name for _full_name, last_name in _load_player_name_aliases())


@lru_cache(maxsize=1)
def _load_player_name_aliases() -> frozenset[tuple[str, str]]:
    people_path = Path(__file__).resolve().parents[3] / "data" / "People.csv"
    if not people_path.exists():
        return frozenset()
    aliases: set[tuple[str, str]] = set()
    with people_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            first = row.get("nameFirst") or ""
            last = row.get("nameLast") or ""
            full_name = _normalize_player_name_for_lookup(f"{first} {last}")
            last_name = _normalize_player_name_for_lookup(last)
            if full_name and last_name:
                aliases.add((full_name, last_name))
    return frozenset(aliases)


def _looks_like_name_token(value: str) -> bool:
    stripped = value.strip("'-.")
    return bool(stripped) and stripped[0].isupper()
