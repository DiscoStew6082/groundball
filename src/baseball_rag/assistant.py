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
from decimal import Decimal
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
RESEARCH_TOPICS = (
    "pregame",
    "team_history",
    "definition",
    "series_meeting",
    "current_leaders",
    "probable_pitchers",
)
CURRENT_BATTING_STATS = ("HR", "RBI", "SB")


@dataclass(frozen=True)
class ResearchSources:
    """Deployment-owned bounded I/O; the product owns interpretation and answers."""

    next_fixture: Callable[[str], dict[str, Any] | None]
    postseason_meetings: Callable[[str, str], list[dict[str, Any]]]
    batting_leaders: Callable[[str, int, int], dict[str, Any] | None] | None = None
    probable_pitchers: Callable[[str], dict[str, Any] | None] | None = None


def validate_answer_context(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Accept only bounded references; every follow-up retrieves evidence anew."""
    if value is None:
        return None
    allowed = {"version", "topic", "team", "opponent", "season", "statistic"}
    if not isinstance(value, Mapping) or set(value) - allowed:
        raise ValueError("Answer context must contain references only.")
    if any(type(item) not in (str, int, type(None)) for item in value.values()):
        raise ValueError("Answer context references must be scalar values.")
    if len(json.dumps(dict(value), ensure_ascii=False, allow_nan=False).encode()) > 2048:
        raise ValueError("Answer context is too large.")
    if value.get("version", 1) != 1 or type(value.get("version", 1)) is not int:
        raise ValueError("Unsupported answer context version.")
    if value.get("topic") not in RESEARCH_TOPICS:
        raise ValueError("Unknown answer context topic.")
    for key in ("team", "opponent"):
        if value.get(key) is not None and (
            not isinstance(value[key], str) or value[key] not in TEAM_NAMES
        ):
            raise ValueError("Unknown team reference.")
    if value.get("season") is not None and (
        type(value["season"]) is not int or not 1871 <= value["season"] <= datetime.now(UTC).year
    ):
        raise ValueError("Invalid season reference.")
    if value.get("statistic") is not None and value["statistic"] not in DEFINITIONS:
        raise ValueError("Unknown statistic reference.")
    return {"version": 1, **dict(value)}


def validate_research_request(request: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"topic", "team", "count", "statistic", "opponent", "season"}
    if not isinstance(request, Mapping) or set(request) - allowed:
        raise ValueError("Unknown research fields.")
    topic = request.get("topic")
    if topic not in RESEARCH_TOPICS:
        raise ValueError("Unsupported research topic.")
    count = request.get("count", 2 if topic == "probable_pitchers" else 5)
    if type(count) is not int or not 1 <= count <= 5:
        raise ValueError("Request between one and five details.")
    team = request.get("team")
    statistic = request.get("statistic")
    if topic == "current_leaders":
        if team is not None or statistic not in CURRENT_BATTING_STATS:
            raise ValueError("Current leaders require a supported league-wide batting statistic.")
    elif topic == "definition":
        if team is not None or statistic not in DEFINITIONS:
            raise ValueError("Choose a supported stat definition.")
    elif team not in TEAM_NAMES or statistic is not None:
        raise ValueError("Choose an unambiguous MLB team.")
    result = {"topic": topic, "team": team, "count": count, "statistic": statistic}
    season, opponent = request.get("season"), request.get("opponent")
    if topic == "current_leaders":
        season = datetime.now(UTC).year if season is None else season
        if type(season) is not int or season != datetime.now(UTC).year:
            raise ValueError("The current source covers this season only.")
        result["season"] = season
    elif topic == "series_meeting":
        if opponent not in TEAM_NAMES or opponent == team:
            raise ValueError("Choose two distinct teams for a World Series meeting.")
        if type(season) is not int or not 1903 <= season < datetime.now(UTC).year:
            raise ValueError("Choose the historical World Series season.")
        result.update(season=season, opponent=opponent)
    elif season is not None:
        raise ValueError("This research topic does not accept a season constraint.")
    if topic != "series_meeting" and opponent is not None:
        raise ValueError("This research topic does not accept an opponent constraint.")
    if topic == "probable_pitchers" and count > 2:
        raise ValueError("A fixture has at most two probable pitchers.")
    return result


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
        "mlb_stats": {"statsapi.mlb.com"},
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
            "mlb_stats": "MLB source terms apply",
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
    record = source["record"]
    games = record.get("games")
    if (
        type(record.get("year")) is not int
        or record["year"] != year
        or record.get("round") != "World Series"
        or not isinstance(games, list)
        or not 1 <= len(games) <= 20
    ):
        raise ValueError("The retained record does not identify this World Series.")
    tally = {team: 0, opponent: 0}
    seen = set()
    aliases = {"ANA": "LAA", "FLO": "MIA"}
    for game in games:
        if not isinstance(game, list) or len(game) < 6:
            raise ValueError("Invalid retained game record.")
        date, number, away, home, away_score, home_score, *_ = game
        if not isinstance(away, str) or not isinstance(home, str):
            raise ValueError("Invalid retained team identity.")
        away, home = aliases.get(away, away), aliases.get(home, home)
        if (
            away == home
            or {away, home} != {team, opponent}
            or datetime.strptime(date, "%Y%m%d").year != year
            or any(type(score) is not int or score < 0 for score in (away_score, home_score))
            or (date, number) in seen
        ):
            raise ValueError("Retained games do not match this series.")
        seen.add((date, number))
        if away_score != home_score:
            tally[away if away_score > home_score else home] += 1
    if tally[winner] != wins or tally[loser] != losses:
        raise ValueError("Series summary differs from the retained game scores.")
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
    if plan["topic"] == "series_meeting":
        return _series_answer(plan, sources)
    if plan["topic"] in {"current_leaders", "probable_pitchers"}:
        return _current_answer(plan, sources)
    team, count = plan["team"], plan["count"]
    fixture = None
    evidence = []
    candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    context: dict[str, Any] = {"version": 1, "team": team, "topic": plan["topic"]}
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
            context["opponent"] = opponent
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
                meeting = max(meetings, key=lambda m: m["year"])
                candidates.append(_meeting_fact(meeting, team, opponent))
                context["season"] = meeting["year"]
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
        "context": context,
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
        "context": {"version": 1, "topic": "definition", "statistic": statistic},
    }


def _series_answer(plan: dict[str, Any], sources: ResearchSources | None) -> dict[str, Any]:
    try:
        meetings = sources.postseason_meetings(plan["team"], plan["opponent"]) if sources else []
        meeting = next(m for m in meetings if m["year"] == plan["season"])
        fact, source = _meeting_fact(meeting, plan["team"], plan["opponent"])
        facts = [fact]
        for game in source["record"].get("games", []):
            if len(facts) >= plan["count"]:
                break
            date, _, away, home, away_score, home_score, *_ = game
            aliases = {"ANA": "LAA", "FLO": "MIA"}
            away, home = aliases.get(away, away), aliases.get(home, home)
            day = datetime.strptime(date, "%Y%m%d").date()
            facts.append(
                {
                    "id": f"series-game-{len(facts)}",
                    "text": f"On {day.isoformat()}, {TEAM_NAMES[away]} scored {away_score} "
                    f"and {TEAM_NAMES[home]} scored {home_score}.",
                    "source_ids": [source["id"]],
                }
            )
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return {
            "kind": "unavailable",
            "reason": "I could not verify that World Series meeting from the available records.",
        }
    return {
        "kind": "answer",
        "schema": "ground-ball-assistant-answer-v1",
        "title": f"{plan['season']} World Series",
        "summary": "Details checked against retained World Series records.",
        "facts": facts,
        "sources": [source],
        "fixture": None,
        "limitations": []
        if len(facts) == plan["count"]
        else [f"I found {len(facts)} supported details."],
        "attributions": [source_credit("retrosheet")],
        "requested_count": plan["count"],
        "context": {
            "version": 1,
            "topic": "series_meeting",
            "team": plan["team"],
            "opponent": plan["opponent"],
            "season": plan["season"],
        },
    }


def _current_answer(plan: dict[str, Any], sources: ResearchSources | None) -> dict[str, Any]:
    topic = plan["topic"]
    label = "current batting leaders" if topic == "current_leaders" else "probable pitchers"

    def identifier(value: object) -> bool:
        return type(value) is int and 0 < value < 100_000_000

    def name(value: object) -> bool:
        return (
            isinstance(value, str)
            and 1 <= len(value) <= 120
            and bool(value.strip())
            and all(char.isalnum() or char in " .,'’()-" for char in value)
        )

    try:
        if sources is None:
            raise ValueError("No current-data source.")
        if topic == "current_leaders":
            data = (
                sources.batting_leaders(plan["statistic"], plan["season"], plan["count"])
                if sources.batting_leaders
                else None
            )
        else:
            data = sources.probable_pitchers(plan["team"]) if sources.probable_pitchers else None
        if not isinstance(data, dict) or not isinstance(data.get("source"), Mapping):
            raise ValueError("Current source unavailable.")
        source = _source(data["source"], "mlb_stats")
        normalized = {key: value for key, value in data.items() if key != "source"}
        if source["record"].get("normalized") != normalized:
            raise ValueError("Current facts differ from retained normalized source records.")
        observed = datetime.fromisoformat(source["observed_at"].replace("Z", "+00:00"))
        age = (datetime.now(UTC) - observed).total_seconds()
        if not -60 <= age <= 600:
            raise ValueError("Current observation is stale.")
        if topic == "current_leaders":
            if (
                set(normalized) != {"season", "statistic", "rows"}
                or type(data["season"]) is not int
                or data["season"] != plan["season"]
                or data["statistic"] != plan["statistic"]
            ):
                raise ValueError("Current statistic scope differs.")
            rows = data["rows"]
            if not isinstance(rows, list) or not 1 <= len(rows) <= 50:
                raise ValueError("No bounded current leaders.")
            lines = []
            people = set()
            previous, rank = None, 0
            for index, row in enumerate(rows):
                if (
                    not isinstance(row, dict)
                    or set(row)
                    != {"rank", "player_id", "player_name", "team_id", "team_name", "value"}
                    or not isinstance(row["team_id"], str)
                    or row["team_id"] not in TEAM_NAMES
                    or row["team_name"] != TEAM_NAMES[row["team_id"]]
                    or not identifier(row["player_id"])
                    or row["player_id"] in people
                    or not name(row["player_name"])
                ):
                    raise ValueError("Invalid current player identity.")
                people.add(row["player_id"])
                value = row["value"]
                if type(value) is not int or not 0 <= value < 100_000:
                    raise ValueError("Invalid current statistic.")
                if previous is not None and value > previous:
                    raise ValueError("Current leaders are not sorted.")
                if value != previous:
                    rank = index + 1
                if not identifier(row["rank"]) or row["rank"] != rank:
                    raise ValueError("Current leader rank differs from values.")
                if index >= plan["count"] and value != rows[plan["count"] - 1]["value"]:
                    raise ValueError("Only cutoff ties may extend the requested leader count.")
                previous = value
                lines.append(
                    f"{row['player_name']} ({TEAM_NAMES[row['team_id']]}): "
                    f"{value} {plan['statistic']}."
                )
            facts = [
                {
                    "id": "current-leaders",
                    "text": f"{plan['season']} regular-season batting leaders "
                    f"as of {source['observed_at']}: " + " ".join(lines),
                    "source_ids": [source["id"]],
                }
            ]
            title = f"{plan['season']} batting {plan['statistic']} leaders"
            context = {
                "version": 1,
                "topic": topic,
                "statistic": plan["statistic"],
                "season": plan["season"],
            }
            limitations = [
                "Current standings are a dated source snapshot and may change. "
                "Ties at the requested cutoff are included."
            ]
            fixture = None
        else:
            home, away = data["home_team_id"], data["away_team_id"]
            if not isinstance(data["starts_at"], str):
                raise ValueError("Fixture start must be a timestamp.")
            start = datetime.fromisoformat(data["starts_at"].replace("Z", "+00:00"))
            if (
                set(normalized)
                != {
                    "game_id",
                    "home_team_id",
                    "away_team_id",
                    "home_team",
                    "away_team",
                    "starts_at",
                    "status",
                    "home_pitcher",
                    "away_pitcher",
                }
                or not identifier(data["game_id"])
                or not isinstance(home, str)
                or not isinstance(away, str)
                or home == away
                or home not in TEAM_NAMES
                or away not in TEAM_NAMES
                or data["home_team"] != TEAM_NAMES[home]
                or data["away_team"] != TEAM_NAMES[away]
                or plan["team"] not in {home, away}
                or start.tzinfo is None
                or not 0 < (start - datetime.now(UTC)).total_seconds() <= 7 * 86400
                or data["status"] != "probable"
            ):
                raise ValueError("Invalid upcoming probable-pitcher fixture.")
            facts = []
            pitcher_ids = set()
            for side, team in (("away", away), ("home", home)):
                pitcher = data[f"{side}_pitcher"]
                if pitcher is not None:
                    if (
                        not isinstance(pitcher, dict)
                        or set(pitcher) != {"id", "name"}
                        or not identifier(pitcher["id"])
                        or pitcher["id"] in pitcher_ids
                        or not name(pitcher["name"])
                    ):
                        raise ValueError("Invalid probable-pitcher identity.")
                    pitcher_ids.add(pitcher["id"])
                if plan["count"] == 1 and team != plan["team"]:
                    continue
                text = (
                    f"{TEAM_NAMES[team]}'s listed probable pitcher is {pitcher['name']}."
                    if pitcher is not None
                    else f"{TEAM_NAMES[team]} has no probable pitcher announced in this source."
                )
                facts.append({"id": f"probable-{team}", "text": text, "source_ids": [source["id"]]})
            title = f"{TEAM_NAMES[away]} at {TEAM_NAMES[home]}: probable pitchers"
            fixture = {
                "home_team_id": home,
                "home_team": TEAM_NAMES[home],
                "away_team_id": away,
                "away_team": TEAM_NAMES[away],
                "starts_at": data["starts_at"],
                "status": "probable",
            }
            context = {
                "version": 1,
                "topic": topic,
                "team": plan["team"],
                "opponent": away if home == plan["team"] else home,
            }
            limitations = [
                "Probable pitchers are not confirmed final starters and may change before the game."
            ]
    except (OSError, ValueError, KeyError, TypeError, ArithmeticError):
        return {
            "kind": "unavailable",
            "reason": f"I could not verify {label} from a fresh MLB source. "
            "I will not fill that gap with historical data.",
        }
    return {
        "kind": "answer",
        "schema": "ground-ball-assistant-answer-v1",
        "title": title,
        "summary": "Current records with observation time and source evidence.",
        "facts": facts,
        "sources": [source],
        "fixture": fixture,
        "limitations": limitations,
        "attributions": [source_credit("mlb_stats")],
        "requested_count": plan["count"],
        "context": context,
    }


def _query_answer(run: dict[str, Any]) -> dict[str, Any]:
    rows = run.get("rows")
    evidence = run.get("evidence", {})
    if (
        run.get("verification", {}).get("status") != "verified"
        or not rows
        or run.get("pagination", {}).get("has_more")
        or run.get("pagination", {}).get("offset", 0) != 0
        or len(rows) != evidence.get("matched_row_count")
        or len(rows) != evidence.get("row_count")
        or hashlib.sha256(
            json.dumps(
                rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str
            ).encode()
        ).hexdigest()
        != evidence.get("result_fingerprint")
    ):
        return {
            "kind": "unavailable",
            "reason": "The complete comparison could not be verified. "
            "Please narrow the requested records.",
        }
    from baseball_rag.query.adapters import catalog_payload

    values = {v["identity"]: v for v in catalog_payload()["values"]}
    labels = {identity: value["friendly_name"] for identity, value in values.items()}
    identity = (
        "query-"
        + hashlib.sha256(
            json.dumps({"plan": run["plan"], "rows": run["rows"]}, sort_keys=True).encode()
        ).hexdigest()[:16]
    )
    source = _source(
        {
            "id": identity,
            "title": "Verified historical comparison",
            "url": "https://sabr.org/lahman-database/",
            "observed_at": _now(),
            "record": {"rows": run["rows"], "evidence": run["evidence"], "plan": run["plan"]},
        },
        "lahman",
    )

    def display(value: Any, identity: str) -> str:
        if values.get(identity, {}).get("data_type") == "baseball_innings" and value is not None:
            return f"{value:.1f}"
        if isinstance(value, float):
            return f"{value:.3f}"
        return "unavailable" if value is None else str(value)

    lines = [
        "; ".join(f"{labels.get(k, k)}: {display(v, k)}" for k, v in row.items()) + "."
        for row in run["rows"]
    ]
    facts = [{"id": identity, "text": " ".join(lines), "source_ids": [identity], "query_run": run}]
    rows = run["rows"]
    if len(rows) == 2 and rows[0].get("season") == rows[1].get("season"):
        name_key = "player.name" if "player.name" in rows[0] else "team.name"
        if name_key in rows[0] and name_key in rows[1] and rows[0][name_key] != rows[1][name_key]:
            for key in rows[0]:
                if (
                    values.get(key, {}).get("kind") in {"count", "calculation"}
                    and values.get(key, {}).get("data_type") in {"integer", "number"}
                    and all(type(row.get(key)) in (int, float) for row in rows)
                ):
                    high, low = sorted(rows, key=lambda row: row[key], reverse=True)
                    difference = Decimal(str(high[key])) - Decimal(str(low[key]))
                    amount = (
                        f"{difference:.3f}"
                        if any(type(row[key]) is float for row in rows)
                        else str(difference)
                    )
                    text = (
                        f"{high[name_key]} and {low[name_key]} had equal {labels.get(key, key)}."
                        if difference == 0
                        else f"{high[name_key]} had {amount} higher {labels.get(key, key)} "
                        f"than {low[name_key]} in {high.get('season', 'the selected period')}."
                    )
                    facts.append(
                        {
                            "id": identity + "-difference-" + key,
                            "text": text,
                            "source_ids": [identity],
                        }
                    )
    return {
        "kind": "answer",
        "facts": facts,
        "sources": [source],
        "limitations": [],
        "attributions": [source_credit("lahman")],
        "recipe": run["recipe"],
    }


def compose_answers(parts: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine up to three checked tool results, never model-written factual prose."""
    if not 1 <= len(parts) <= 3:
        return {
            "kind": "needs_clarification",
            "question": "Please request between one and three supported parts.",
        }
    answers = [_query_answer(part) if part.get("kind") == "rows" else part for part in parts]
    for answer in answers:
        if answer.get("kind") != "answer":
            return {
                "kind": "unavailable",
                "reason": "I could not verify every part of that request. "
                + str(answer.get("reason", answer.get("question", "Please narrow the request."))),
            }
        source_ids = {source["id"] for source in answer["sources"]}
        if (
            not answer["facts"]
            or len(source_ids) != len(answer["sources"])
            or any(
                not fact["source_ids"] or not set(fact["source_ids"]) <= source_ids
                for fact in answer["facts"]
            )
            or len(answer["sources"]) > len(answer["facts"]) + 1
        ):
            return {
                "kind": "unavailable",
                "reason": "I could not bind every part of that request to its supporting sources.",
            }
    if sum(len(answer["facts"]) for answer in answers) > 5:
        return {
            "kind": "needs_clarification",
            "question": "Please narrow the comparison or request fewer details "
            "so I can show all parts together.",
        }
    facts: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for index, answer in enumerate(answers):
        prefix = f"part-{index}-"
        sources.extend({**source, "id": prefix + source["id"]} for source in answer["sources"])
        facts.extend(
            {
                **fact,
                "id": prefix + fact["id"],
                "source_ids": [prefix + key for key in fact["source_ids"]],
            }
            for fact in answer["facts"]
        )
    # Source fingerprints include IDs; recompute after namespacing without changing records.
    sources = [_source(source, source["provider"]) for source in sources]
    result = {
        "kind": "answer",
        "schema": "ground-ball-assistant-answer-v1",
        "title": "Verified results and context",
        "summary": "Each part is supported by the linked records.",
        "facts": facts,
        "sources": sources,
        "fixture": next((a.get("fixture") for a in answers if a.get("fixture")), None),
        "limitations": list(
            dict.fromkeys(limit for a in answers for limit in a.get("limitations", []))
        ),
        "attributions": [
            source_credit(provider) for provider in dict.fromkeys(s["provider"] for s in sources)
        ],
        "requested_count": len(facts),
    }
    recipes = [answer["recipe"] for answer in answers if answer.get("recipe")]
    recipe = recipes[0] if recipes and all(item == recipes[0] for item in recipes) else None
    contexts = [a["context"] for a in answers if a.get("context")]
    research_contexts = [context for context in contexts if context["topic"] != "definition"]
    candidates = research_contexts or contexts
    context = (
        candidates[0]
        if candidates and all(candidate == candidates[0] for candidate in candidates)
        else None
    )
    if recipe is not None:
        result["recipe"] = recipe
    if context is not None:
        result["context"] = context
    return result
