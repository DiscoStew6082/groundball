"""Bounded, provider-neutral research built from source records and Query Runs.

The language model selects a supported request. It never supplies factual prose,
source URLs, numerical values or attribution. Facts below are rendered only from
validated source records and verified deterministic Query Runs.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml

from baseball_rag.public_results import run_public_query_input
from baseball_rag.source_attribution import source_credit

TEAM_NAMES = {
    "ARI": "Arizona Diamondbacks",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHA": "Chicago White Sox",
    "CHN": "Chicago Cubs",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KCA": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAN": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYA": "New York Yankees",
    "NYN": "New York Mets",
    "ATH": "Athletics",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SDN": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SFN": "San Francisco Giants",
    "SLN": "St. Louis Cardinals",
    "TBA": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WAS": "Washington Nationals",
}
DEFINITIONS = ("2B", "AVG", "BB", "ERA", "HR", "OPS", "PO", "RBI", "SB", "WHIP")


@dataclass(frozen=True)
class ResearchSources:
    """Deployment-owned bounded I/O; the product owns interpretation and answers."""

    next_fixture: Callable[[str], dict[str, Any] | None]
    postseason_meetings: Callable[[str, str], list[dict[str, Any]]]


def validate_research_request(request: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"topic", "team", "count", "statistic"}
    if not isinstance(request, Mapping) or set(request) - allowed:
        raise ValueError("Unknown research fields.")
    topic = request.get("topic")
    if topic not in {"pregame", "team_history", "definition"}:
        raise ValueError("Unsupported research topic.")
    count = request.get("count", 5)
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError("Request between one and five details.")
    team = request.get("team")
    statistic = request.get("statistic")
    if topic == "definition":
        if team is not None or statistic not in DEFINITIONS:
            raise ValueError("Choose a supported stat definition.")
    elif team not in TEAM_NAMES or statistic is not None:
        raise ValueError("Choose an unambiguous MLB team.")
    return {"topic": topic, "team": team, "count": count, "statistic": statistic}


def _source(raw: Mapping[str, Any], provider: str) -> dict[str, Any]:
    url = raw.get("url")
    if not isinstance(url, str):
        raise ValueError("Source URL is missing.")
    parsed = urlsplit(url)
    hosts = {
        "thesportsdb": {"www.thesportsdb.com", "thesportsdb.com"},
        "retrosheet": {"www.retrosheet.org", "retrosheet.org"},
        "lahman": {"sabr.org"},
        "wikidata": {"www.wikidata.org"},
        "groundball": {"github.com"},
        "mlb_glossary": {"www.mlb.com"},
    }
    if (
        parsed.scheme != "https"
        or parsed.hostname not in hosts[provider]
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 443}
    ):
        raise ValueError("Untrusted source URL.")
    if not isinstance(raw.get("record"), dict):
        raise ValueError("Supporting source fields are required.")
    for key in ("id", "title", "observed_at"):
        if not isinstance(raw.get(key), str) or not raw[key] or len(raw[key]) > 500:
            raise ValueError("Invalid source identity.")
    observed = datetime.fromisoformat(raw["observed_at"].replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise ValueError("Source observation requires a timezone.")
    source = {key: raw[key] for key in ("id", "title", "url", "observed_at", "record")}
    source.update(
        provider=provider,
        attribution=source_credit(provider)["text"],
        license={
            "lahman": "CC BY-SA 3.0",
            "retrosheet": "Free use with required credit",
            "thesportsdb": "TheSportsDB API terms",
            "wikidata": "CC0",
            "groundball": "Project license",
            "mlb_glossary": "Original paraphrase of the MLB glossary",
        }[provider],
    )
    encoded = json.dumps(source, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    if len(encoded) > 200_000:
        raise ValueError("Source record is too large.")
    source["fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return source


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _recipe(
    team: str,
    source: str,
    grain: str,
    selections: list[str],
    rank: str,
    extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    conditions = [{"kind": "compare", "value": "team.id", "operator": "equals", "literal": team}]
    conditions.extend(extra or [])
    return {
        "source": source,
        "grain": grain,
        "selections": selections,
        "predicate": {"kind": "all", "predicates": conditions},
        "ranking": {
            "value": rank,
            "direction": "highest",
            "count": 1,
            "tie_policy": "include_ties",
            "within": [],
        },
        "output": {"kind": "interactive_page", "size": 25, "offset": 0},
    }


def _query_fact(
    identity: str, recipe: dict[str, Any], render: Callable[[dict[str, Any]], str]
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    run = run_public_query_input(recipe=recipe)
    if (
        run.get("kind") != "rows"
        or run.get("verification", {}).get("status") != "verified"
        or not run.get("rows")
        or run.get("pagination", {}).get("has_more")
    ):
        return None
    row = run["rows"][0]
    source = _source(
        {
            "id": identity,
            "title": "Lahman historical statistics",
            "url": "https://sabr.org/lahman-database/",
            "observed_at": _now(),
            "record": {"rows": run["rows"], "evidence": run["evidence"], "plan": run["plan"]},
        },
        "lahman",
    )
    return (
        {"id": identity, "text": render(row), "source_ids": [identity], "query_run": run},
        source,
    )


def _history(team: str, *, only_team: bool = False) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    name = TEAM_NAMES[team]
    facts = []
    team_record = _query_fact(
        f"{team}-team-hr",
        _recipe(
            team, "Batting", "team-season", ["team.name", "season", "batting.HR"], "batting.HR"
        ),
        lambda r: f"The {r['team.name']} hit {r['batting.HR']} home runs in {r['season']}.",
    )
    if team_record:
        facts.append(team_record)
    if only_team:
        return facts
    balanced = _query_fact(
        f"{team}-power-speed",
        _recipe(
            team,
            "Batting",
            "player-team-season",
            ["player.name", "team.name", "season", "batting.HR", "batting.SB"],
            "batting.SB",
            [
                {
                    "kind": "compare",
                    "value": "batting.HR",
                    "operator": "greater_or_equal",
                    "literal": 30,
                },
                {
                    "kind": "compare",
                    "value": "batting.SB",
                    "operator": "greater_or_equal",
                    "literal": 30,
                },
            ],
        ),
        lambda r: (
            f"{r['player.name']} combined {r['batting.HR']} home runs with "
            f"{r['batting.SB']} stolen bases for the {r['team.name']} in {r['season']}."
        ),
    )
    if balanced:
        facts.append(balanced)
    else:
        hitter = _query_fact(
            f"{team}-hitter-hr",
            _recipe(
                team,
                "Batting",
                "player-team-season",
                ["player.name", "season", "batting.HR"],
                "batting.HR",
            ),
            lambda r: (
                f"{r['player.name']} hit {r['batting.HR']} home runs "
                f"for the {name} in {r['season']}."
            ),
        )
        if hitter:
            facts.append(hitter)
    pitcher = _query_fact(
        f"{team}-pitcher-so",
        _recipe(
            team,
            "Pitching",
            "player-team-season",
            ["player.name", "team.name", "season", "pitching.SO"],
            "pitching.SO",
        ),
        lambda r: (
            f"{r['player.name']} struck out {r['pitching.SO']} batters "
            f"for the {r['team.name']} in {r['season']}."
        ),
    )
    if pitcher:
        facts.append(pitcher)
    return facts


def _meeting_fact(
    meeting: dict[str, Any], team: str, opponent: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    winner, loser = meeting["winner_id"], meeting["loser_id"]
    if {winner, loser} != {team, opponent}:
        raise ValueError("Postseason meeting does not match this fixture.")
    year, wins, losses = meeting["year"], meeting["winner_wins"], meeting["loser_wins"]
    if (
        any(type(value) is not int for value in (year, wins, losses))
        or not 1903 <= year <= datetime.now(UTC).year - 1
        or not 0 <= losses < wins <= 5
    ):
        raise ValueError("Invalid historical series result.")
    source = _source(meeting["source"], "retrosheet")
    fact = {
        "id": f"series-{year}",
        "text": f"These teams met in the {year} World Series: "
        f"the {TEAM_NAMES[winner]} beat the {TEAM_NAMES[loser]} {wins}–{losses}.",
        "source_ids": [source["id"]],
    }
    return fact, source


def research_answer(
    request: Mapping[str, Any], *, sources: ResearchSources | None = None
) -> dict[str, Any]:
    """Answer a supported request with bounded tools and inspectable source records."""
    plan = validate_research_request(request)
    if plan["topic"] == "definition":
        return _definition(plan["statistic"])
    team, count = plan["team"], plan["count"]
    fixture = None
    evidence = []
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    limitations = [
        "Historical statistics use the verified release through 2025. "
        "They do not establish current rosters, starters, injuries or this season's form."
    ]
    if plan["topic"] == "pregame":
        try:
            fixture = sources.next_fixture(team) if sources else None
            if fixture is None:
                raise ValueError("No supported fixture.")
            home, away = fixture["home_team_id"], fixture["away_team_id"]
            start = datetime.fromisoformat(fixture["starts_at"].replace("Z", "+00:00"))
            if (
                team not in {home, away}
                or home == away
                or home not in TEAM_NAMES
                or away not in TEAM_NAMES
                or start.tzinfo is None
                or start <= datetime.now(UTC)
                or fixture["status"] != "NS"
            ):
                raise ValueError("No unstarted matching game.")
            opponent = away if team == home else home
            evidence.append(_source(fixture["source"], "thesportsdb"))
            # Display names are canonical; strings returned by external APIs are data only.
            fixture = {**fixture, "home_team": TEAM_NAMES[home], "away_team": TEAM_NAMES[away]}
            fixture.pop("source")
        except (OSError, ValueError, KeyError, TypeError):
            return {
                "kind": "unavailable",
                "reason": "I could not verify an upcoming fixture. "
                "Try a team-history question instead; I won't guess the opponent or date.",
            }
        assert sources is not None
        try:
            meetings = sources.postseason_meetings(team, opponent)
            if meetings:
                candidates.append(
                    _meeting_fact(max(meetings, key=lambda m: m["year"]), team, opponent)
                )
        except (OSError, ValueError, KeyError, TypeError):
            limitations.append("Postseason meeting evidence is unavailable for this answer.")
        limitations.append(
            "Fixture coverage is limited: this is the next listed game, "
            "not a guarantee of a complete schedule. Start times may change."
        )
    candidates.extend(_history(team))
    if fixture:
        opponent = (
            fixture["away_team_id"] if fixture["home_team_id"] == team else fixture["home_team_id"]
        )
        candidates.extend(_history(opponent, only_team=True))
    chosen = candidates[:count]
    evidence.extend(source for _, source in chosen)
    if len(chosen) < count:
        limitations.append(
            f"I found {len(chosen)} supported details rather than the requested {count}."
        )
    return {
        "kind": "answer",
        "schema": "ground-ball-assistant-answer-v1",
        "title": f"{TEAM_NAMES[team]}: {'game context' if fixture else 'historical context'}",
        "summary": "Dated baseball facts selected from source records. "
        "Historical players are not a prediction of who will play.",
        "facts": [fact for fact, _ in chosen],
        "sources": evidence,
        "fixture": fixture,
        "limitations": limitations,
        "attributions": [
            source_credit(provider)
            for provider in dict.fromkeys(source["provider"] for source in evidence)
        ],
        "requested_count": count,
        "context": {"team": team, "topic": plan["topic"]},
    }


def _definition(statistic: str) -> dict[str, Any]:
    path = Path(__file__).parent / "corpus" / "stat_definitions" / f"{statistic}.md"
    if not path.is_file():
        return {"kind": "unavailable", "reason": "That sourced stat definition is unavailable."}
    content = path.read_text()
    _, metadata, content = content.split("---", 2)
    reference = yaml.safe_load(metadata)
    content = content.strip()
    source = _source(
        {
            "id": f"definition-{statistic}",
            "title": f"MLB glossary: {reference['title']}",
            "url": reference["source_url"],
            "observed_at": _now(),
            "record": {"definition": content},
        },
        "mlb_glossary",
    )
    return {
        "kind": "answer",
        "schema": "ground-ball-assistant-answer-v1",
        "title": statistic,
        "summary": "A sourced stat explanation.",
        "facts": [{"id": source["id"], "text": content, "source_ids": [source["id"]]}],
        "sources": [source],
        "fixture": None,
        "limitations": [],
        "attributions": [source_credit("mlb_glossary")],
        "requested_count": 1,
    }
