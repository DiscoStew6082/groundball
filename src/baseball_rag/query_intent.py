"""Translate statistics slots into the existing catalog-validated Query Recipe.

This adapter supplies no facts or identity resolution. Callers resolve player names
through the shared natural-recipe resolver and execute through the normal Query Run.
Unsupported or ambiguous requests raise ValueError; no conditions are discarded.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from baseball_rag.query.adapters import recipe_from_dict
from baseball_rag.query.contracts import NeedsClarification, Ready
from baseball_rag.query.registry import grain_by_identity, published_values, source_by_identity
from baseball_rag.query.runtime import published_data_runtime
from baseball_rag.query.service import prepare


class StatsIntentClarificationError(ValueError):
    """An incomplete slot request; code uses the shared clarification vocabulary."""

    def __init__(self, code: str, question: str | None = None):
        self.code = code
        self.question = question
        super().__init__(code)


def _statistics() -> list[str]:
    return [
        value.identity
        for value in published_values()
        if value.kind in {"count", "calculation"}
        and value.data_type in {"integer", "number", "baseball_innings"}
    ]


def _sources() -> list[str]:
    grain = grain_by_identity("player-season")
    return list(grain.sources) if grain else []


def seasons_within_release(years: Iterable[int], manifest: Mapping[str, Any], source: str) -> bool:
    """Check requested statistical seasons against the validated release coverage.

    File-level coverage is release-bearing metadata shared by loaded and prepared
    runtimes. Acquisition-only aggregate metadata need not be present. Other
    catalog sources, such as People birth dates, are not statistical seasons.
    """
    if source not in _sources():
        return True
    binding = source_by_identity(source)
    files = manifest.get("files")
    if binding is None or not isinstance(files, list):
        return False
    matches = [
        entry
        for entry in files
        if isinstance(entry, Mapping) and entry.get("table") == binding.manifest_table
    ]
    if len(matches) != 1:
        return False
    coverage = matches[0].get("year_coverage")
    if (
        not isinstance(coverage, Mapping)
        or type(coverage.get("min")) is not int
        or type(coverage.get("max")) is not int
        or coverage["min"] > coverage["max"]
    ):
        return False
    return all(coverage["min"] <= year <= coverage["max"] for year in years)


def stats_intent_schema() -> dict[str, Any]:
    """Model-visible slots for straightforward published statistics requests.

    Team filters use canonical team.id codes (ATL, NYA, etc.). Subject distinguishes
    team totals from player totals filtered to a team. More complex requests retain
    the existing direct Query Recipe path instead of weakening this contract.
    """

    def object_schema(properties: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        }

    strings = {"type": "array", "items": {"type": "string", "minLength": 1}, "maxItems": 50}
    statistic = {"type": "string", "enum": _statistics()}
    year = {"type": "integer", "minimum": 1, "maximum": 9999}
    return object_schema(
        {
            "source": {"type": "string", "enum": _sources()},
            "subject": {
                "type": "string",
                "enum": ["players", "teams"],
                "description": "Entity being compared: individual players or team totals.",
            },
            "players": strings,
            "exclude_players": strings,
            "teams": {
                **strings,
                "description": "Canonical published team.id codes, not nicknames.",
            },
            "exclude_teams": {**strings, "description": "Canonical published team.id codes."},
            "period": {
                "anyOf": [
                    object_schema(
                        {
                            "kind": {"const": "seasons"},
                            "years": {
                                "type": "array",
                                "items": year,
                                "minItems": 1,
                                "maxItems": 50,
                            },
                        }
                    ),
                    object_schema({"kind": {"const": "range"}, "start": year, "end": year}),
                    object_schema({"kind": {"const": "career"}}),
                    object_schema({"kind": {"const": "unspecified"}}),
                ]
            },
            "statistics": {"type": "array", "items": statistic, "minItems": 1, "maxItems": 50},
            "ranking": {
                "anyOf": [
                    {"type": "null"},
                    object_schema(
                        {
                            "value": {**statistic, "description": "Must also occur in statistics."},
                            "direction": {"type": "string", "enum": ["highest", "lowest"]},
                            "count": {"type": "integer", "minimum": 1, "maximum": 50},
                        }
                    ),
                ]
            },
            "unsupported_conditions": {
                **strings,
                "description": (
                    "Every condition unrepresented by these slots. Nonempty means reject; "
                    "never omit conditions to obtain an answer."
                ),
            },
        }
    )


def _object(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ValueError(f"{label} must contain exactly its declared fields.")
    return value


def _strings(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 50
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise ValueError(f"{label} must be a list of at most 50 nonempty strings.")
    return value


def _validate(request: Mapping[str, Any]) -> None:
    _object(
        request,
        {
            "source",
            "subject",
            "players",
            "exclude_players",
            "teams",
            "exclude_teams",
            "period",
            "statistics",
            "ranking",
            "unsupported_conditions",
        },
        "Statistics intent",
    )
    for key in (
        "players",
        "exclude_players",
        "teams",
        "exclude_teams",
        "statistics",
        "unsupported_conditions",
    ):
        _strings(request[key], key)
    if request["unsupported_conditions"]:
        raise ValueError("Statistics intent contains conditions this adapter cannot represent.")
    if request["source"] not in _sources() or request["subject"] not in ("players", "teams"):
        raise ValueError("Statistics source or subject is not published.")
    if not request["statistics"]:
        raise StatsIntentClarificationError("missing_statistic")
    if any(statistic not in _statistics() for statistic in request["statistics"]):
        raise ValueError("Statistics must be published numeric counts or calculations.")
    if request["subject"] == "teams" and (request["players"] or request["exclude_players"]):
        raise ValueError("Team totals with player restrictions require an explicit Query Recipe.")
    period = request["period"]
    if not isinstance(period, Mapping):
        raise ValueError("Period must be an object.")
    kind = period.get("kind")
    if kind == "seasons":
        _object(period, {"kind", "years"}, "Season list")
        years = period["years"]
        if not isinstance(years, list) or len(years) > 50:
            raise ValueError("Season list must contain at most 50 integer years.")
        if not years:
            raise StatsIntentClarificationError("missing_season")
    elif kind == "range":
        _object(period, {"kind", "start", "end"}, "Season range")
        years = [period["start"], period["end"]]
    elif kind in ("career", "unspecified"):
        _object(period, {"kind"}, "Period")
        if kind == "unspecified":
            raise StatsIntentClarificationError("missing_season")
        years = []
    else:
        raise ValueError("Period kind is not supported.")
    if any(type(year) is not int or not 1 <= year <= 9999 for year in years):
        raise ValueError("Seasons must be integer years.")
    if kind == "range" and years[0] > years[1]:
        raise ValueError("Season range is reversed.")
    runtime = published_data_runtime()
    if not seasons_within_release(years, runtime.manifest, request["source"]):
        raise ValueError("Requested seasons exceed the immutable release's year coverage.")
    requested_teams = {*request["teams"], *request["exclude_teams"]}
    if requested_teams:
        reference = source_by_identity("TeamReference")
        if reference is None:
            raise ValueError("Published team identities are unavailable.")
        relation = reference.relation.replace('"', '""')
        with runtime.connection_lock:
            known_teams = {
                row[0]
                for row in runtime.connection.execute(
                    f'SELECT DISTINCT teamID FROM "{relation}"'
                ).fetchall()
            }
        if not requested_teams <= known_teams:
            raise ValueError("Unknown published team ID; resolve the requested team first.")
    ranking = request["ranking"]
    if ranking is not None:
        _object(ranking, {"value", "direction", "count"}, "Ranking")
        if (
            ranking["value"] not in request["statistics"]
            or ranking["direction"] not in ("highest", "lowest")
            or type(ranking["count"]) is not int
            or not 1 <= ranking["count"] <= 50
        ):
            raise ValueError("Ranking requires a selected statistic, direction, and count 1–50.")


def translate_stats_intent(request: Mapping[str, Any]) -> dict[str, Any]:
    """Build a recipe, raising ValueError for unsupported or ambiguous scope."""
    _validate(request)
    predicates = []
    for field, included, excluded in (
        ("player.name", request["players"], request["exclude_players"]),
        ("team.id", request["teams"], request["exclude_teams"]),
    ):
        if included:
            predicates.append(
                {"kind": "compare", "value": field, "operator": "one_of", "literal": included}
            )
        if excluded:
            predicates.append(
                {
                    "kind": "not",
                    "predicate": {
                        "kind": "compare",
                        "value": field,
                        "operator": "one_of",
                        "literal": excluded,
                    },
                }
            )
    period = request["period"]
    if period["kind"] == "range":
        predicates.append(
            {
                "kind": "compare",
                "value": "season",
                "operator": "range",
                "literal": [period["start"], period["end"]],
            }
        )
    elif period["kind"] == "seasons":
        predicates.append(
            {
                "kind": "any",
                "predicates": [
                    {"kind": "compare", "value": "season", "operator": "equals", "literal": year}
                    for year in period["years"]
                ],
            }
        )
    team_scope = bool(request["teams"] or request["exclude_teams"])
    if period["kind"] == "career":
        if request["subject"] != "players" or team_scope:
            raise ValueError("Career team scope requires an explicit published Query Recipe.")
        grain, dimensions = "player-career", ["player.name"]
    elif request["subject"] == "teams":
        grain, dimensions = "team-season", ["team.id", "team.name", "season"]
    elif team_scope:
        grain, dimensions = "player-team-season", ["player.name", "team.id", "season"]
    else:
        grain, dimensions = "player-season", ["player.name", "season"]
    recipe: dict[str, Any] = {
        "source": request["source"],
        "grain": grain,
        "selections": [*dimensions, *request["statistics"]],
        "predicate": {"kind": "all", "predicates": predicates} if predicates else None,
    }
    if request["ranking"] is not None:
        recipe["ranking"] = {**request["ranking"], "tie_policy": "include_ties"}
    outcome = prepare(recipe_from_dict(recipe))
    if isinstance(outcome, NeedsClarification):
        raise StatsIntentClarificationError("missing_scope", outcome.question)
    if not isinstance(outcome, Ready):
        raise ValueError(str(outcome))
    return recipe
