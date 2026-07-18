"""Deterministic natural-language and named-recipe Adapter for promoted queries."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from baseball_rag.query.contracts import (
    All,
    Compare,
    Literal,
    NeedsClarification,
    QueryRecipe,
    RankSpec,
    Rejected,
    SortSpec,
    ValueRef,
)
from baseball_rag.query.registry import named_recipe_by_identity

RecipeAdaptation = QueryRecipe | NeedsClarification | Rejected


def build_named_recipe(identity: str, **parameters: object) -> RecipeAdaptation:
    """Expand a catalog-owned named recipe into ordinary recipe semantics."""
    recipe = named_recipe_by_identity(identity)
    if recipe is None:
        return Rejected(f"Named recipe {identity!r} is not published.")
    eligibility = _resolve_eligibility(recipe.eligibility, parameters)
    if isinstance(eligibility, NeedsClarification):
        return eligibility
    predicates: list[Compare] = []
    for declaration in recipe.predicates:
        if declaration.get("eligibility_floor") is True:
            if eligibility is None:
                return NeedsClarification(
                    "Which exact league and season should use the reviewed eligibility rule?"
                )
            predicates.append(
                Compare(
                    str(eligibility["value"]),
                    "greater_or_equal",
                    int(eligibility["minimum"]),
                )
            )
            continue
        reference = str(declaration["value"])
        operator = str(declaration["operator"])
        if "value_ref" in declaration:
            literal: Literal = ValueRef(str(declaration["value_ref"]))
        elif "parameter" in declaration:
            parameter = str(declaration["parameter"])
            if parameter not in parameters:
                return NeedsClarification(f"What {parameter} should this named recipe use?")
            candidate = parameters[parameter]
            if declaration.get("transform") == "upper" and isinstance(candidate, str):
                candidate = candidate.upper()
            if not isinstance(candidate, (str, int, float, bool, type(None))):
                return Rejected(
                    f"Named recipe {identity!r} received an invalid {parameter} parameter."
                )
            literal = candidate
        else:
            literal = declaration.get("literal")
        if not isinstance(literal, (str, int, float, bool, type(None), ValueRef)):
            return Rejected(f"Named recipe {identity!r} has an invalid literal declaration.")
        predicates.append(Compare(reference, operator, literal))
    return QueryRecipe(
        source=recipe.source,
        grain=recipe.grain,
        selections=recipe.selections,
        predicate=All(tuple(predicates)),
        ordering=tuple(
            SortSpec(
                value=str(spec["value"]),
                direction=str(spec["direction"]),
                nulls=str(spec.get("nulls", "last")),
            )
            for spec in recipe.ordering
        ),
    )


def _resolve_eligibility(
    rules: tuple[Mapping[str, Any], ...], parameters: dict[str, object]
) -> Mapping[str, Any] | NeedsClarification | None:
    if not rules:
        return None
    year = parameters.get("year")
    league = parameters.get("league")
    if not isinstance(year, int) or isinstance(year, bool) or not isinstance(league, str):
        return NeedsClarification(
            "Which exact league and season should use the reviewed batting-title rule?"
        )
    rule = next(
        (
            item
            for item in rules
            if item.get("year") == year and item.get("league") == league.upper()
        ),
        None,
    )
    if rule is None:
        return NeedsClarification(
            f"No reviewed batting-title eligibility rule is published for {league.upper()} {year}."
        )
    return rule


def interpret_recipe(question: str) -> RecipeAdaptation:
    """Interpret the reviewed deterministic phrases for the initial Adapter."""
    normalized = " ".join(question.casefold().replace("’", "'").split())
    ambiguous_strikeouts = re.fullmatch(
        r"who had the most (?:strikeouts|so) in (\d{4})\??",
        normalized,
    )
    if ambiguous_strikeouts:
        return NeedsClarification("Should strikeouts mean batting or pitching strikeouts?")
    pitching_strikeouts = re.fullmatch(
        r"which pitcher had the most (?:strikeouts|so) in (\d{4})\??",
        normalized,
    )
    if pitching_strikeouts:
        year = int(pitching_strikeouts.group(1))
        return QueryRecipe(
            source="Pitching",
            grain="player-season",
            selections=("player.id", "season", "pitching.SO"),
            predicate=Compare("season", "equals", year),
            ranking=RankSpec("pitching.SO", "highest", 1, "include_ties"),
        )
    contextual_leader = re.fullmatch(
        r"which (pitcher|batter|hitter) had the most "
        r"(games|hits|home runs|walks|strikeouts|g|h|hr|bb|so) in (\d{4})\??",
        normalized,
    )
    if contextual_leader:
        role, requested_value, year_text = contextual_leader.groups()
        source = "Pitching" if role == "pitcher" else "Batting"
        identity = {
            "games": "G",
            "g": "G",
            "hits": "H",
            "h": "H",
            "home runs": "HR",
            "hr": "HR",
            "walks": "BB",
            "bb": "BB",
            "strikeouts": "SO",
            "so": "SO",
        }[requested_value]
        promoted_value = f"{source.casefold()}.{identity}"
        return QueryRecipe(
            source=source,
            grain="player-season",
            selections=("player.id", "season", promoted_value),
            predicate=Compare("season", "equals", int(year_text)),
            ranking=RankSpec(promoted_value, "highest", 1, "include_ties"),
        )
    ambiguous_leader = re.fullmatch(
        r"who had the most (games|hits|home runs|walks|g|h|hr|bb) in (\d{4})\??",
        normalized,
    )
    if ambiguous_leader:
        return NeedsClarification(
            "Should that statistic use batting, pitching, or fielding context?"
        )
    fielding_games = re.fullmatch(
        r"which fielder (?:played|had) the most (?:games|g) in (\d{4})\??",
        normalized,
    )
    if fielding_games:
        return NeedsClarification("Which fielding position should the games leaderboard use?")
    position_games = re.fullmatch(
        r"which (catcher|first baseman|second baseman|third baseman|shortstop|"
        r"left fielder|center fielder|right fielder|pitcher) "
        r"(?:played|had) the most (?:games|g) in (\d{4})\??",
        normalized,
    )
    if position_games:
        position_name, year_text = position_games.groups()
        position = {
            "catcher": "C",
            "first baseman": "1B",
            "second baseman": "2B",
            "third baseman": "3B",
            "shortstop": "SS",
            "left fielder": "LF",
            "center fielder": "CF",
            "right fielder": "RF",
            "pitcher": "P",
        }[position_name]
        return QueryRecipe(
            source="Fielding",
            grain="player-position-season",
            selections=("player.id", "season", "position", "fielding.G"),
            predicate=All(
                (
                    Compare("season", "equals", int(year_text)),
                    Compare("position", "equals", position),
                )
            ),
            ranking=RankSpec("fielding.G", "highest", 1, "include_ties"),
        )
    if re.search(r"\b40\s*[- ]\s*40\b", normalized):
        return build_named_recipe("batting.40-40")
    if re.search(r"\b30\s*[- ]\s*30\b", normalized):
        return build_named_recipe("batting.30-30")
    if "500" in normalized and ("home run" in normalized or "homer" in normalized):
        return build_named_recipe("batting.500-home-runs")

    rbi_year = re.fullmatch(
        r"who had the most (?:rbi|rbis|runs batted in) in (\d{4})\??",
        normalized,
    )
    if rbi_year:
        year = int(rbi_year.group(1))
        return QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.name", "season", "batting.RBI"),
            predicate=Compare("season", "equals", year),
            ranking=RankSpec("batting.RBI", "highest", 1, "include_ties"),
        )

    player_ops = re.fullmatch(r"([a-z .'-]+)'s (\d{4}) ops\??", normalized)
    if player_ops:
        player_name = " ".join(part.capitalize() for part in player_ops.group(1).split())
        year = int(player_ops.group(2))
        return QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=(
                "player.name",
                "season",
                "batting.AB",
                "batting.H",
                "batting.2B",
                "batting.3B",
                "batting.HR",
                "batting.BB",
                "batting.HBP",
                "batting.SF",
                "batting.AVG",
                "batting.OBP",
                "batting.SLG",
                "batting.OPS",
            ),
            predicate=All(
                (
                    Compare("player.name", "equals", player_name),
                    Compare("season", "equals", year),
                )
            ),
        )

    average = re.fullmatch(
        r"highest batting average in (\d{4})"
        r"(?:,? (?:minimum|min) (\d+) (?:at-bats|at bats|ab))?\??",
        normalized,
    )
    if average:
        year = int(average.group(1))
        minimum = average.group(2)
        if minimum is None:
            return NeedsClarification(
                "What minimum at-bat sample should this batting-average leaderboard use?"
            )
        return QueryRecipe(
            source="Batting",
            grain="player-season",
            selections=("player.name", "season", "batting.AB", "batting.AVG"),
            predicate=All(
                (
                    Compare("season", "equals", year),
                    Compare("batting.AB", "greater_or_equal", int(minimum)),
                )
            ),
            ranking=RankSpec("batting.AVG", "highest", 1, "include_ties"),
        )

    if re.search(r"\b(?:plus|added to|sum of)\b", normalized) and any(
        phrase in normalized for phrase in ("home run", "stolen base", "hits", "walks")
    ):
        return Rejected("Arbitrary formulas are not published; choose a catalog calculation.")
    return Rejected("That natural-language batting recipe is not published yet.")
