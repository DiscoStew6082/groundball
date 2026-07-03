"""Deterministic SQL templates for common baseball-history questions."""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from baseball_rag.db.grounded_database_types import AssembledSQL, QuerySpec, TeamIdentity
from baseball_rag.db.stat_registry import StatDefinition, get_stat
from baseball_rag.db.team_history import resolve_team_identity
from baseball_rag.year_parsing import extract_spelled_year


@dataclass(frozen=True)
class MatchedTemplate:
    """Read model for one deterministic grounded database template match."""

    assembled: AssembledSQL
    source_detail: str
    route_owner: bool = True
    query_spec: QuerySpec | None = None
    template_id: str = ""
    description: str = ""
    match_facts: Mapping[str, Any] = field(default_factory=dict)
    _route_owner_policy: Callable[[str | None], bool] = field(
        default=lambda _competing_stat: True,
        repr=False,
        compare=False,
    )

    @property
    def unsupported_reason(self) -> str | None:
        return self.assembled.unsupported_reason

    def should_route(self, *, competing_stat: str | None = None) -> bool:
        """Return whether this matched template should own routing."""
        return self.route_owner and self._route_owner_policy(competing_stat)


TemplateMatcher = Callable[[str], Mapping[str, Any] | None]
TemplateAssembler = Callable[[Mapping[str, Any], str], AssembledSQL]
TemplateSourceDetail = Callable[[Mapping[str, Any], str], str]
TemplateQuerySpec = Callable[[Mapping[str, Any], str], QuerySpec | None]
TemplateRouteOwner = Callable[[Mapping[str, Any], str, str | None], bool]


@dataclass(frozen=True)
class BattingStreakStat:
    """Whitelisted Retrosheet batting-log stat that can define player-game streaks."""

    stat_key: str
    column: str
    streak_column: str
    total_column: str
    streak_label: str
    event_label: str
    source_label: str
    definition_label: str


_BATTING_GAME_LOG_STAT_CODES = {
    "stolen_base": "SB",
    "hit": "H",
    "home_run": "HR",
    "rbi": "RBI",
    "run": "R",
}


@dataclass(frozen=True)
class GroundedDatabaseTemplate:
    """Local owner for one deterministic grounded database template."""

    template_id: str
    description: str
    matcher: TemplateMatcher
    assemble: TemplateAssembler
    source_detail: TemplateSourceDetail
    route_owner: TemplateRouteOwner = lambda _facts, _question, _stat: True
    query_spec: TemplateQuerySpec = lambda _facts, _question: None

    def match(self, question: str) -> MatchedTemplate | None:
        facts = self.matcher(question)
        if facts is None:
            return None

        return MatchedTemplate(
            assembled=self.assemble(facts, question),
            source_detail=self.source_detail(facts, question),
            route_owner=self.route_owner(facts, question, None),
            query_spec=self.query_spec(facts, question),
            template_id=self.template_id,
            description=self.description,
            match_facts=dict(facts),
            _route_owner_policy=lambda competing_stat: self.route_owner(
                facts,
                question,
                competing_stat,
            ),
        )


def _normalize_question(question: str) -> str:
    """Return a compact lowercase form for deterministic template matching."""
    normalized = re.sub(r"[^a-z0-9]+", " ", question.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _extract_threshold(text: str, *, default: int) -> int:
    match = re.search(r"\b(\d{2,4})\b", text)
    return int(match.group(1)) if match else default


def _extract_game_stat_threshold(text: str, *, default: int = 1) -> int:
    match = re.search(
        r"\b(?:at least|minimum|min|with|had|have|steal|stole|strike out|struck out)\s+"
        r"(\d{1,3})\b",
        text,
    )
    if match:
        return int(match.group(1))
    return default


def _extract_explicit_wins_threshold(text: str) -> int | None:
    match = re.search(
        r"\b(?:over|more than|at least|minimum|min|with|threshold|>=)\s+(\d{2,4})\s+wins?\b",
        text,
    )
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{2,4})\s+wins?\s+(?:club|threshold)\b", text)
    return int(match.group(1)) if match else None


def _extract_year(text: str) -> int | None:
    match = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", text)
    return int(match.group(1)) if match else extract_spelled_year(text)


def _extract_min_ipouts(text: str, *, default: int) -> int:
    match = re.search(r"\b(?:at least|minimum|min)?\s*(\d{2,4})\s+innings\b", text)
    return int(match.group(1)) * 3 if match else default


def _extract_min_ab(text: str, *, default: int) -> int:
    match = re.search(r"\b(?:at least|minimum|min|with)?\s*(\d{2,4})\s+at bats?\b", text)
    return int(match.group(1)) if match else default


def _unsupported_sql(reason: str, *, code: str = "unsupported") -> AssembledSQL:
    return AssembledSQL(
        "SELECT ? AS unsupported_reason WHERE FALSE",
        [reason],
        unsupported_reason=code,
    )


def match_template(question: str) -> MatchedTemplate | None:
    """Return the matched deterministic template spec for a question."""
    q = _normalize_question(question)
    for template in _TEMPLATES:
        matched = template.match(q)
        if matched is not None:
            return matched

    return None


def _detect_template(question: str) -> AssembledSQL | None:
    """Return deterministic SQL for high-value grounded database baseball-history patterns."""
    matched = match_template(question)
    return matched.assembled if matched is not None else None


def can_plan_deterministically(question: str) -> bool:
    """Return whether a question is owned by a deterministic grounded database template."""
    return match_template(question) is not None


def should_route_deterministic_grounded_database(
    question: str,
    *,
    competing_stat: str | None = None,
) -> bool:
    """Return whether deterministic grounded database planning should win routing precedence."""
    matched = match_template(question)
    if matched is None:
        return False
    return matched.should_route(competing_stat=competing_stat)


def _is_plain_career_home_run_leaderboard(q: str) -> bool:
    return (
        "career" in q
        and ("home run" in q or "homer" in q or bool(re.search(r"\bhrs?\b", q)))
        and "club" not in q
        and "500" not in q
    )


def _is_plain_season_era_leaderboard(q: str) -> bool:
    return (
        "era" in q
        and _extract_year(q) is not None
        and "career" not in q
        and not _has_era_qualification_guard(q)
    )


def _has_era_qualification_guard(q: str) -> bool:
    return "qualified" in q or "qualifying" in q or "enough innings" in q or " innings" in q


def _looks_like_single_season(q: str) -> bool:
    return _extract_year(q) is not None and "career" not in q and "club" not in q


def _looks_like_roster_question(q: str) -> bool:
    return (
        ("played for" in q or "roster" in q or "players" in q)
        and _extract_year(q) is not None
        and _extract_team_nickname(q) is not None
    )


def _looks_like_batting_average_leader(q: str) -> bool:
    return (
        ("batting average" in q or bool(re.search(r"\bavg\b", q)))
        and ("highest" in q or "best" in q or "leader" in q or "leaders" in q)
        and "career" not in q
    )


_TEAM_NICKNAMES = (
    "braves",
    "yankees",
    "dodgers",
    "cubs",
    "red sox",
    "white sox",
    "giants",
    "athletics",
    "cardinals",
    "pirates",
    "reds",
    "tigers",
    "orioles",
    "twins",
    "rangers",
    "angels",
    "astros",
    "blue jays",
    "brewers",
    "diamondbacks",
    "guardians",
    "mariners",
    "marlins",
    "mets",
    "nationals",
    "padres",
    "phillies",
    "rays",
    "royals",
)


def _extract_team_nickname(q: str) -> str | None:
    for nickname in _TEAM_NICKNAMES:
        if re.search(rf"\b{re.escape(nickname)}\b", q):
            return nickname
    return None


def _source_detail(text: str) -> TemplateSourceDetail:
    return lambda _facts, _question: text


def _match_ambiguous_500_club(q: str) -> Mapping[str, Any] | None:
    if "500 club" in q and "home run" not in q and "hr" not in q:
        return {"pattern": "500 club"}
    return None


def _assemble_ambiguous_500_club(
    _facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    return _unsupported_sql(
        "The question says 500 club but does not specify home runs or pitching wins.",
        code="ambiguous",
    )


def _match_triple_crown(q: str) -> Mapping[str, Any] | None:
    if "triple crown" in q:
        return {"pattern": "triple crown"}
    return None


def _match_thirty_thirty(q: str) -> Mapping[str, Any] | None:
    if re.search(r"\b30\s*30\b", q) or "30 30 club" in q or "thirty thirty" in q:
        return {"pattern": "30-30 club"}
    return None


def _match_roster(q: str) -> Mapping[str, Any] | None:
    if not _looks_like_roster_question(q):
        return None
    year = _extract_year(q)
    nickname = _extract_team_nickname(q)
    if year is None or nickname is None:
        return None
    identity = resolve_team_identity(q, team_name_pattern=nickname, year=year)
    return {
        "pattern": "team-season roster",
        "team_nickname": nickname,
        "year": year,
        "team_identity": identity,
    }


def _assemble_roster(facts: Mapping[str, Any], question: str) -> AssembledSQL:
    nickname = str(facts["team_nickname"])
    year = int(facts["year"])
    identity = facts.get("team_identity")
    return _roster_sql(
        nickname,
        year,
        question,
        identity=identity if isinstance(identity, TeamIdentity) else None,
    )


def _roster_query_spec(facts: Mapping[str, Any], _question: str) -> QuerySpec:
    nickname = str(facts["team_nickname"])
    identity = facts.get("team_identity")
    return QuerySpec(
        stat_tables=["batting"],
        team_name_pattern=nickname.title(),
        year_value=int(facts["year"]),
        team_identity=identity if isinstance(identity, TeamIdentity) else None,
    )


def _match_batting_average_leader(q: str) -> Mapping[str, Any] | None:
    if not _looks_like_batting_average_leader(q):
        return None
    return {
        "pattern": "qualified batting average leader",
        "year": _extract_year(q),
        "qualified": "qualified" in q,
        "min_ab": _extract_min_ab(q, default=100),
    }


def _assemble_batting_average_leader(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    year = facts["year"]
    if year is None and not bool(facts["qualified"]):
        return _unsupported_sql("Batting average leader questions need a specific year.")
    return _qualified_season_avg_sql(
        int(year) if year is not None else None,
        int(facts["min_ab"]),
    )


def _match_career_home_runs(q: str) -> Mapping[str, Any] | None:
    if (
        ("home run" in q or "homer" in q or re.search(r"\bhrs?\b", q))
        and ("500" in q or "club" in q or "career" in q)
        and not _looks_like_single_season(q)
    ):
        return {
            "pattern": "career home run totals",
            "threshold": _extract_threshold(q, default=500),
            "plain_leaderboard": _is_plain_career_home_run_leaderboard(q),
        }
    return None


def _assemble_career_home_runs(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    return _career_home_run_sql(int(facts["threshold"]))


def _career_home_run_route_owner(
    facts: Mapping[str, Any],
    _question: str,
    competing_stat: str | None,
) -> bool:
    return not (competing_stat == "HR" and bool(facts["plain_leaderboard"]))


def _match_career_pitching_wins(q: str) -> Mapping[str, Any] | None:
    if (
        ("wins" in q or re.search(r"\bw\b", q))
        and ("pitcher" in q or "pitching" in q or "career" in q or "500" in q)
        and not _looks_like_single_season(q)
    ):
        return {
            "pattern": "career pitching wins",
            "threshold": _extract_explicit_wins_threshold(q),
        }
    return None


def _assemble_career_pitching_wins(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    threshold = facts["threshold"]
    return _career_pitching_wins_sql(int(threshold) if threshold is not None else None)


def _match_career_era(q: str) -> Mapping[str, Any] | None:
    if "era" in q and "career" in q:
        return {
            "pattern": "career ERA leaders",
            "has_qualification_guard": _has_era_qualification_guard(q),
            "min_ipouts": _extract_min_ipouts(q, default=3000),
        }
    return None


def _assemble_career_era(facts: Mapping[str, Any], _question: str) -> AssembledSQL:
    if not bool(facts["has_qualification_guard"]):
        return _unsupported_sql("Career ERA leader questions need an explicit qualification guard.")
    return _career_era_sql(int(facts["min_ipouts"]))


def _match_qualified_season_era(q: str) -> Mapping[str, Any] | None:
    if "era" in q and ("lowest" in q or "best" in q or "leader" in q or "leaders" in q):
        return {
            "pattern": "qualified season ERA leader",
            "year": _extract_year(q),
            "has_qualification_guard": _has_era_qualification_guard(q),
            "min_ipouts": _extract_min_ipouts(q, default=300),
            "plain_leaderboard": _is_plain_season_era_leaderboard(q),
        }
    return None


def _assemble_qualified_season_era(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    year = facts["year"]
    if year is None and not bool(facts["has_qualification_guard"]):
        return _unsupported_sql(
            "Season ERA leader questions need a specific year and innings qualification."
        )
    if not bool(facts["has_qualification_guard"]):
        return _unsupported_sql("Season ERA leader questions need an innings qualification guard.")
    return _qualified_season_era_sql(
        int(year) if year is not None else None,
        int(facts["min_ipouts"]),
    )


def _qualified_season_era_route_owner(
    facts: Mapping[str, Any],
    _question: str,
    competing_stat: str | None,
) -> bool:
    return not (competing_stat == "ERA" and bool(facts["plain_leaderboard"]))


def _has_strikeout_side_phrase(q: str) -> bool:
    return bool(re.search(r"\b(?:strike|struck) out the side\b|\bstrikeout side\b", q))


def _has_pitcher_daily_strikeout_game_log_phrase(q: str) -> bool:
    return (
        bool(re.search(r"\b(?:strikeout|strikeouts|struck out|strike out)\b", q))
        and bool(re.search(r"\b(?:games?|game log|game by game)\b", q))
        and not _has_strikeout_side_phrase(q)
    )


def _unsupported_pitcher_daily_game_log_reason(q: str) -> str | None:
    if re.search(r"\b(?:team|teams)\b", q):
        return "Team pitching game logs are not modeled by this player game-log template."
    if re.search(r"\b(?:pitch by pitch|pitch-level|pitch level|pitch counts?|pitches)\b", q):
        return "Pitch-level details are not modeled in Retrosheet daily pitching logs."
    if re.search(r"\b(?:inning by inning|inning-level|inning level|innings?)\b", q):
        return "Inning-level pitching events are not modeled in Retrosheet daily pitching logs."
    return None


def _extract_pitcher_daily_game_log_player_name(q: str) -> str | None:
    for pattern in (
        r"\b(?:show|list)\s+(?P<player>[a-z][a-z .'\\-]+?)\s+"
        r"(?:(?:postseason|playoff|regular season)\s+)?games?\s+with\b",
        r"\bwhat games did\s+(?P<player>[a-z][a-z .'\\-]+?)\s+"
        r"(?:strike|struck) out\b",
        r"\b(?P<player>[a-z][a-z .'\\-]+?)\s+strikeout\s+game log\b",
    ):
        match = re.search(pattern, q)
        if match is None:
            continue
        player_name = re.sub(r"^(?:show|list)\s+", "", match.group("player").strip())
        if player_name and player_name not in {"what", "who", "which pitchers"}:
            return player_name
    return None


def _extract_pitcher_daily_game_log_threshold(q: str) -> int:
    match = re.search(
        r"\b(?:at least|minimum|min|with|>=)\s+(?P<threshold>\d{1,2})\s+"
        r"(?:strikeouts?|ks?|batters)\b",
        q,
    )
    if match is not None:
        return int(match.group("threshold"))
    match = re.search(
        r"\b(?:strike|struck) out\s+(?P<threshold>\d{1,2})\s+(?:batters|hitters)\b",
        q,
    )
    return int(match.group("threshold")) if match is not None else 0


def _match_pitcher_daily_strikeout_game_log(q: str) -> Mapping[str, Any] | None:
    if not _has_pitcher_daily_strikeout_game_log_phrase(q):
        return None
    unsupported_reason = _unsupported_pitcher_daily_game_log_reason(q)
    player_name = _extract_pitcher_daily_game_log_player_name(q)
    if unsupported_reason is None and player_name is None:
        return None
    return {
        "pattern": "pitcher daily strikeout game log",
        "unsupported_reason": unsupported_reason,
        "player_name": player_name,
        "threshold": _extract_pitcher_daily_game_log_threshold(q),
        "year": _extract_year(q),
        "gametype": "playoff" if _mentions_postseason(q) else "regular",
    }


def _match_pitcher_strikeout_side_leaders(q: str) -> Mapping[str, Any] | None:
    if not _has_strikeout_side_phrase(q):
        return None
    if "postseason" in q or "playoff" in q or _extract_year(q) is not None:
        return None
    if "career" not in q and "careers" not in q:
        return None
    if "pitcher" not in q and "pitchers" not in q:
        return None
    if not re.search(r"\b(?:most|leaders?|leaderboard|top)\b", q):
        return None
    return {
        "pattern": "pitcher strikeout-side career leaders",
        "limit": 10,
    }


def _match_pitcher_strikeout_side_count(q: str) -> Mapping[str, Any] | None:
    if "postseason" in q or "playoff" in q:
        return None
    year = _extract_year(q)
    if year is None and "career" not in q:
        return None
    match = re.search(
        r"\b(?:how many times\s+)?(?:did|has)\s+(?P<player>[a-z][a-z .'\\-]+?)\s+"
        r"(?:strike|struck) out the side\b",
        q,
    )
    if match is None:
        return None

    player_name = match.group("player").strip()
    if not player_name or player_name in {"which pitchers", "who"}:
        return None
    return {
        "pattern": "pitcher strikeout-side count",
        "player_name": player_name,
        "year": year,
        "opponent_team_pattern": _extract_opponent_team_pattern(q),
        "unrecognized_opponent_filter": _has_opponent_clause(q)
        and _extract_opponent_team_pattern(q) is None,
    }


def _match_pitcher_strikeout_side_game_log(q: str) -> Mapping[str, Any] | None:
    if "postseason" in q or "playoff" in q or not _has_strikeout_side_phrase(q):
        return None
    if re.search(r"\b(?:how many|how often|count)\b", q):
        return None
    if not re.search(r"\b(?:when|show|list|games?|game log|game by game)\b", q):
        return None

    match = re.search(
        r"\b(?:when did|show|list|which games did|what games did)?\s*"
        r"(?P<player>[a-z][a-z .'\\-]+?)\s+"
        r"(?:(?:strike|struck) out the side|strikeout side)\b",
        q,
    )
    if match is None:
        return None

    player_name = match.group("player").strip()
    if not player_name or player_name in {"which pitchers", "who"}:
        return None
    return {
        "pattern": "pitcher strikeout-side game log",
        "player_name": player_name,
        "year": _extract_year(q),
        "opponent_team_pattern": _extract_opponent_team_pattern(q),
        "unrecognized_opponent_filter": _has_opponent_clause(q)
        and _extract_opponent_team_pattern(q) is None,
    }


def _has_opponent_clause(q: str) -> bool:
    return bool(re.search(r"\b(?:against|versus|vs)\b", q))


def _extract_opponent_team_pattern(q: str) -> str | None:
    if not _has_opponent_clause(q):
        return None
    nickname = _extract_team_nickname(q)
    if nickname is not None:
        return nickname
    match = re.search(r"\b(?:against|versus|vs)\s+(?:the\s+)?(?P<team_id>[a-z0-9]{2,3})\b", q)
    return match.group("team_id") if match else None


_BATTING_STREAK_STATS: dict[str, BattingStreakStat] = {
    "stolen_base": BattingStreakStat(
        stat_key="stolen_base",
        column="b_sb",
        streak_column="stolen_base_streak_games",
        total_column="stolen_bases",
        streak_label="stolen-base streak",
        event_label="stolen base",
        source_label="stolen-base",
        definition_label="stolen base",
    ),
    "hit": BattingStreakStat(
        stat_key="hit",
        column="b_h",
        streak_column="hit_streak_games",
        total_column="hits",
        streak_label="hit streak",
        event_label="hit",
        source_label="hit",
        definition_label="hit",
    ),
    "home_run": BattingStreakStat(
        stat_key="home_run",
        column="b_hr",
        streak_column="home_run_streak_games",
        total_column="home_runs",
        streak_label="home-run game streak",
        event_label="home run",
        source_label="home-run game",
        definition_label="home run",
    ),
    "rbi": BattingStreakStat(
        stat_key="rbi",
        column="b_rbi",
        streak_column="rbi_streak_games",
        total_column="rbi",
        streak_label="RBI game streak",
        event_label="RBI",
        source_label="RBI game",
        definition_label="RBI",
    ),
    "run": BattingStreakStat(
        stat_key="run",
        column="b_r",
        streak_column="run_scored_streak_games",
        total_column="runs_scored",
        streak_label="run-scored streak",
        event_label="run scored",
        source_label="run-scored",
        definition_label="run scored",
    ),
}


def _match_stolen_base_streak(q: str) -> Mapping[str, Any] | None:
    return _match_batting_stat_streak(q)


def _match_player_batting_game_log(q: str) -> Mapping[str, Any] | None:
    detected_stats = _detect_batting_game_log_stats(q)
    if not detected_stats or "streak" in q:
        return None
    if not re.search(r"\b(?:show|list|what games|which games|games?|game log|game by game)\b", q):
        return None

    stat = detected_stats[0]
    unsupported_reason = _unsupported_player_batting_game_log_reason(q, stat)
    player_name = _extract_player_batting_game_log_player_name(q, stat)
    if unsupported_reason is None and player_name is None:
        return None
    return {
        "pattern": "player batting game log",
        "stat_key": stat.stat_key,
        "unsupported_reason": unsupported_reason,
        "player_name": player_name,
        "threshold": _extract_player_batting_game_log_threshold(q, stat),
        "year": _extract_year(q),
        "gametype": "playoff" if _mentions_postseason(q) else "regular",
    }


def _match_batting_stat_streak(q: str) -> Mapping[str, Any] | None:
    stat = _detect_batting_streak_stat(q)
    if stat is None or "streak" not in q:
        return None
    if not re.search(r"\b(?:longest|best|record|most|leader)\b", q):
        return None
    unsupported_reason = _unsupported_batting_stat_streak_reason(q, stat)
    return {
        "pattern": stat.streak_label,
        "stat_key": stat.stat_key,
        "unsupported_reason": unsupported_reason,
        "player_name": _extract_batting_stat_streak_player_name(q, stat),
        "gametype": "playoff" if _mentions_postseason(q) else "regular",
    }


def _detect_batting_streak_stat(q: str) -> BattingStreakStat | None:
    detected: list[BattingStreakStat] = []
    if re.search(r"\bstolen bases?\b|\bsteal(?:ing)? streak\b", q):
        detected.append(_BATTING_STREAK_STATS["stolen_base"])
    if re.search(r"\bhitting streak\b|\bhit streak\b|\bhits? streak\b", q):
        detected.append(_BATTING_STREAK_STATS["hit"])
    if re.search(r"\bhome runs?\b|\bhomers?\b|\bhrs?\b", q):
        detected.append(_BATTING_STREAK_STATS["home_run"])
    if re.search(r"\brbis?\b|\bruns? batted in\b", q):
        detected.append(_BATTING_STREAK_STATS["rbi"])
    if re.search(r"\bruns?[- ]scored\b|\bruns? scored\b|\bscored runs?\b", q):
        detected.append(_BATTING_STREAK_STATS["run"])
    if len({stat.stat_key for stat in detected}) != 1:
        return None
    return detected[0]


def _detect_batting_game_log_stat(q: str) -> BattingStreakStat | None:
    detected = _detect_batting_game_log_stats(q)
    if len({stat.stat_key for stat in detected}) != 1:
        return None
    return detected[0]


def _detect_batting_game_log_stats(q: str) -> list[BattingStreakStat]:
    return [
        stat
        for stat in _BATTING_STREAK_STATS.values()
        if _detect_batting_game_log_stat_for_key(q, stat)
    ]


def _detect_batting_game_log_stat_for_key(q: str, stat: BattingStreakStat) -> bool:
    if stat.stat_key == "stolen_base":
        return bool(re.search(r"\bstolen bases?\b|\bsteal(?:s|ing)?\b|\bstole\b", q))
    if stat.stat_key == "hit":
        return bool(
            re.search(
                r"\bhits\b|\bhit\s+game log\b|\bhit\s+games\b|"
                r"\bwith\s+(?:at least\s+)?\d{1,2}\s+hits?\b",
                q,
            )
        )
    return _detect_batting_streak_stat_for_key(q, stat)


def _mentions_postseason(q: str) -> bool:
    return bool(re.search(r"\b(?:postseason|playoffs?|world series)\b", q))


def _extract_stolen_base_streak_player_name(q: str) -> str | None:
    return _extract_batting_stat_streak_player_name(q, _BATTING_STREAK_STATS["stolen_base"])


def _extract_batting_stat_streak_player_name(q: str, stat: BattingStreakStat) -> str | None:
    stat_phrase = _batting_streak_stat_phrase(stat)
    for pattern in (
        r"\b(?:what (?:was|is) )?(?P<player>[a-z][a-z .'\\-]+?)'s\s+"
        rf"(?:longest|best)\s+(?:postseason\s+)?{stat_phrase}\s+streak\b",
        r"\b(?:what (?:was|is) )?(?P<player>[a-z][a-z .'\\-]+?)\s+s\s+"
        rf"(?:longest|best)\s+(?:postseason\s+)?{stat_phrase}\s+streak\b",
        r"\b(?P<player>[a-z][a-z .'\\-]+?)\s+"
        rf"(?:longest|best)\s+(?:postseason\s+)?{stat_phrase}\s+streak\b",
        r"\b(?:longest|best|record|most|leader)\s+(?:postseason\s+)?"
        rf"{stat_phrase}\s+streak\s+(?:for|by)\s+(?P<player>[a-z][a-z .'\\-]+?)\b",
    ):
        match = re.search(pattern, q)
        if match is None:
            continue
        player_name = match.group("player").strip()
        if player_name not in {"mlb", "major league baseball", "who", "what"} and not re.match(
            r"^(?:what|who|which|the)\b", player_name
        ):
            return player_name
    return None


def _batting_streak_stat_phrase(stat: BattingStreakStat) -> str:
    if stat.stat_key == "stolen_base":
        return r"stolen bases?"
    if stat.stat_key == "hit":
        return r"(?:hitting|hits?)"
    if stat.stat_key == "home_run":
        return r"(?:home runs?|homers?|hrs?)"
    if stat.stat_key == "rbi":
        return r"(?:rbis?|runs? batted in)"
    return r"(?:runs?[- ]scored|runs? scored|scored runs?)"


def _batting_game_log_stat_phrase(stat: BattingStreakStat) -> str:
    if stat.stat_key == "stolen_base":
        return r"(?:stolen bases?|steals?|stole)"
    return _batting_streak_stat_phrase(stat)


def _unsupported_stolen_base_streak_reason(q: str) -> str | None:
    return _unsupported_batting_stat_streak_reason(q, _BATTING_STREAK_STATS["stolen_base"])


def _unsupported_batting_stat_streak_reason(q: str, stat: BattingStreakStat) -> str | None:
    if re.search(r"\b(?:team|teams)\b", q):
        return f"Team {stat.source_label} streaks are not modeled yet."
    detected_stats = {
        detected.stat_key
        for detected in _BATTING_STREAK_STATS.values()
        if _detect_batting_streak_stat_for_key(q, detected)
    }
    if len(detected_stats) > 1:
        return "Multi-stat batting streaks are not modeled yet."
    if re.search(r"\b(?:play|plays|plate appearance|at bat|inning|innings)\b", q):
        return "Play-level or inning-level batting streaks are not modeled yet."
    if stat.stat_key == "stolen_base" and re.search(
        r"\b(?:caught stealing|without being caught|without getting caught)\b",
        q,
    ):
        return (
            "Consecutive successful stolen-base attempt streaks need caught-stealing-aware "
            "attempt modeling, not just games with at least one stolen base."
        )
    if stat.stat_key == "stolen_base" and re.search(
        r"\b(?:stealing|steal|stolen)\s+(?:second|third|home)\b",
        q,
    ):
        return "Base-specific stolen-base streaks are not modeled yet."
    return None


def _unsupported_player_batting_game_log_reason(q: str, stat: BattingStreakStat) -> str | None:
    if re.search(r"\b(?:team|teams)\b", q):
        return "Team batting game logs are not modeled by this player game-log template."
    detected_stats = {
        detected.stat_key
        for detected in _BATTING_STREAK_STATS.values()
        if _detect_batting_game_log_stat_for_key(q, detected)
    }
    if len(detected_stats) > 1:
        return "Multi-stat batting game logs are not modeled yet."
    if re.search(r"\b(?:play|plays|plate appearance|at bat|inning|innings)\b", q):
        return (
            "Play-level or inning-level batting details are not modeled in Retrosheet daily logs."
        )
    if stat.stat_key == "stolen_base" and re.search(
        r"\b(?:caught stealing|without being caught|without getting caught)\b",
        q,
    ):
        return (
            "Caught-stealing-aware stolen-base attempt logs need play-level attempt modeling, "
            "not just Retrosheet daily batting totals."
        )
    if stat.stat_key == "stolen_base" and re.search(
        r"\b(?:stealing|steal|stolen)\s+(?:second|third|home)\b",
        q,
    ):
        return "Base-specific stolen-base details are not modeled in Retrosheet daily logs."
    return None


def _detect_batting_streak_stat_for_key(q: str, stat: BattingStreakStat) -> bool:
    phrase = _batting_streak_stat_phrase(stat)
    return bool(re.search(rf"\b{phrase}\b", q))


def _extract_player_batting_game_log_player_name(
    q: str,
    stat: BattingStreakStat,
) -> str | None:
    stat_phrase = _batting_game_log_stat_phrase(stat)
    for pattern in (
        r"\b(?:show|list)\s+(?P<player>[a-z][a-z .'\\-]+?)\s+s\s+games?\s+with\b",
        r"\b(?:show|list)\s+(?P<player>[a-z][a-z .'\\-]+?)\s+games?\s+with\b",
        r"\bwhat games did\s+(?P<player>[a-z][a-z .'\\-]+?)\s+hit\s+\d{1,2}\s+"
        r"(?:home runs?|homers?|hrs?)\b",
        rf"\bwhat games did\s+(?P<player>[a-z][a-z .'\\-]+?)\s+{stat_phrase}\b",
        rf"\bwhich games did\s+(?P<player>[a-z][a-z .'\\-]+?)\s+{stat_phrase}\b",
        rf"\b(?P<player>[a-z][a-z .'\\-]+?)\s+{stat_phrase}\s+game log\b",
    ):
        match = re.search(pattern, q)
        if match is None:
            continue
        player_name = re.sub(r"^(?:show|list)\s+", "", match.group("player").strip())
        if player_name and player_name not in {"what", "who", "which players"}:
            return player_name
    return None


def _extract_player_batting_game_log_threshold(q: str, stat: BattingStreakStat) -> int:
    stat_phrase = _batting_game_log_stat_phrase(stat)
    match = re.search(
        rf"\b(?:at least|minimum|min|with|>=)\s+(?P<threshold>\d{{1,2}})\s+"
        rf"{stat_phrase}\b",
        q,
    )
    if match is not None:
        return int(match.group("threshold"))
    if stat.stat_key == "stolen_base":
        match = re.search(r"\b(?:steal|stole)\s+(?P<threshold>\d{1,2})\s+bases?\b", q)
        if match is not None:
            return int(match.group("threshold"))
    if stat.stat_key == "home_run":
        match = re.search(
            r"\bhit\s+(?P<threshold>\d{1,2})\s+(?:home runs?|homers?|hrs?)\b",
            q,
        )
        if match is not None:
            return int(match.group("threshold"))
    return 1


def _assemble_stolen_base_streak(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    if facts.get("unsupported_reason"):
        return _unsupported_sql(str(facts["unsupported_reason"]))
    stat = _BATTING_STREAK_STATS[str(facts.get("stat_key", "stolen_base"))]
    player_name = facts.get("player_name")
    return _batting_stat_streak_sql(
        stat,
        str(player_name) if player_name else None,
        str(facts["gametype"]),
    )


def _assemble_player_batting_game_log(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    if facts.get("unsupported_reason"):
        return _unsupported_sql(str(facts["unsupported_reason"]))
    player_name = facts.get("player_name")
    if player_name is None:
        return _unsupported_sql("Player batting game logs need a player full name.")
    stat = _BATTING_STREAK_STATS[str(facts["stat_key"])]
    return _player_batting_game_log_sql(
        stat,
        str(player_name),
        int(facts["threshold"]),
        facts["year"],
        str(facts["gametype"]),
    )


def _assemble_pitcher_strikeout_side_count(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    if bool(facts.get("unrecognized_opponent_filter")):
        return _unsupported_sql(
            "Opponent filters need a recognized team nickname or Retrosheet team code."
        )
    return _pitcher_strikeout_side_count_sql(
        str(facts["player_name"]),
        facts["year"],
        facts.get("opponent_team_pattern"),
    )


def _assemble_pitcher_strikeout_side_leaders(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    return _pitcher_strikeout_side_leaders_sql(int(facts["limit"]))


def _assemble_pitcher_strikeout_side_game_log(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    if bool(facts.get("unrecognized_opponent_filter")):
        return _unsupported_sql(
            "Opponent filters need a recognized team nickname or Retrosheet team code."
        )
    return _pitcher_strikeout_side_game_log_sql(
        str(facts["player_name"]),
        facts["year"],
        facts.get("opponent_team_pattern"),
    )


def _assemble_pitcher_daily_strikeout_game_log(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    if facts.get("unsupported_reason"):
        return _unsupported_sql(str(facts["unsupported_reason"]))
    player_name = facts.get("player_name")
    if player_name is None:
        return _unsupported_sql("Pitcher game-log queries need a player full name.")
    return _pitcher_daily_strikeout_game_log_sql(
        str(player_name),
        int(facts["threshold"]),
        facts["year"],
        str(facts["gametype"]),
    )


_TEMPLATES: tuple[GroundedDatabaseTemplate, ...] = (
    GroundedDatabaseTemplate(
        template_id="ambiguous_500_club",
        description="Ambiguous 500 club unsupported policy",
        matcher=_match_ambiguous_500_club,
        assemble=_assemble_ambiguous_500_club,
        source_detail=_source_detail("Matched local deterministic grounded database SQL template."),
    ),
    GroundedDatabaseTemplate(
        template_id="triple_crown",
        description="Triple Crown batting leaders by league and season",
        matcher=_match_triple_crown,
        assemble=lambda _facts, _question: _triple_crown_sql(),
        source_detail=_source_detail(
            "Matched local Triple Crown template: batting HR, RBI, and AVG "
            "league leaders by season."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="thirty_thirty_club",
        description="Player seasons with at least 30 HR and 30 SB",
        matcher=_match_thirty_thirty,
        assemble=lambda _facts, _question: _thirty_thirty_sql(),
        source_detail=_source_detail(
            "Matched local 30-30 club template: player seasons with at least 30 HR and 30 SB."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="team_season_roster",
        description="Team-season roster resolved through historical team identity",
        matcher=_match_roster,
        assemble=_assemble_roster,
        source_detail=_source_detail("Matched local team-season roster template."),
        query_spec=_roster_query_spec,
    ),
    GroundedDatabaseTemplate(
        template_id="qualified_batting_average_leader",
        description="Qualified season batting average leaders",
        matcher=_match_batting_average_leader,
        assemble=_assemble_batting_average_leader,
        source_detail=_source_detail(
            "Matched local qualified season batting average leader template with an AB guard."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="career_home_runs",
        description="Career batting home run totals",
        matcher=_match_career_home_runs,
        assemble=_assemble_career_home_runs,
        source_detail=_source_detail(
            "Matched local 500 HR club template: career batting home run totals."
        ),
        route_owner=_career_home_run_route_owner,
    ),
    GroundedDatabaseTemplate(
        template_id="career_pitching_wins",
        description="Career pitching wins totals",
        matcher=_match_career_pitching_wins,
        assemble=_assemble_career_pitching_wins,
        source_detail=_source_detail(
            "Matched local career pitching wins leaders template: career pitching W totals."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="career_era",
        description="Career ERA leaders with innings qualification",
        matcher=_match_career_era,
        assemble=_assemble_career_era,
        source_detail=_source_detail(
            "Matched local career ERA leaders template with an innings qualification guard."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="qualified_season_era",
        description="Qualified season ERA leaders",
        matcher=_match_qualified_season_era,
        assemble=_assemble_qualified_season_era,
        source_detail=_source_detail(
            "Matched local qualified season ERA leader template with an innings guard."
        ),
        route_owner=_qualified_season_era_route_owner,
    ),
    GroundedDatabaseTemplate(
        template_id="batting_stat_streak",
        description="Retrosheet game-log batting stat streaks",
        matcher=_match_stolen_base_streak,
        assemble=_assemble_stolen_base_streak,
        source_detail=_source_detail(
            "Matched local Retrosheet game-level batting log batting stat streak template."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="player_batting_game_log",
        description="Retrosheet daily batting player game log",
        matcher=_match_player_batting_game_log,
        assemble=_assemble_player_batting_game_log,
        source_detail=_source_detail(
            "Matched local Retrosheet daily batting player game-log template."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="pitcher_daily_strikeout_game_log",
        description="Retrosheet daily pitching strikeout game log",
        matcher=_match_pitcher_daily_strikeout_game_log,
        assemble=_assemble_pitcher_daily_strikeout_game_log,
        source_detail=_source_detail(
            "Matched local Retrosheet daily pitching strikeout game-log template."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="pitcher_strikeout_side_game_log",
        description="Retrosheet event-derived pitcher strikeout-side game log",
        matcher=_match_pitcher_strikeout_side_game_log,
        assemble=_assemble_pitcher_strikeout_side_game_log,
        source_detail=_source_detail(
            "Matched local Retrosheet event-derived strikeout-side game log template."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="pitcher_strikeout_side_count",
        description="Retrosheet event-derived pitcher strikeout-side career or year counts",
        matcher=_match_pitcher_strikeout_side_count,
        assemble=_assemble_pitcher_strikeout_side_count,
        source_detail=_source_detail(
            "Matched local Retrosheet event-derived strikeout-side count template."
        ),
    ),
    GroundedDatabaseTemplate(
        template_id="pitcher_strikeout_side_leaders",
        description="Retrosheet event-derived pitcher strikeout-side career leaderboard",
        matcher=_match_pitcher_strikeout_side_leaders,
        assemble=_assemble_pitcher_strikeout_side_leaders,
        source_detail=_source_detail(
            "Matched local Retrosheet event-derived strikeout-side career leaderboard template."
        ),
    ),
)


def _triple_crown_sql() -> AssembledSQL:
    return AssembledSQL(
        """
        WITH season_batting AS (
            SELECT
                b.playerID,
                b.yearID,
                b.lgID,
                p.nameFirst,
                p.nameLast,
                SUM(b.HR) AS HR,
                SUM(b.RBI) AS RBI,
                SUM(b.H) AS H,
                SUM(b.AB) AS AB,
                CAST(SUM(b.H) AS DOUBLE) / NULLIF(SUM(b.AB), 0) AS AVG
            FROM batting b
            JOIN people p ON p.playerID = b.playerID
            WHERE b.lgID IN ('AL', 'NL')
            GROUP BY b.playerID, b.yearID, b.lgID, p.nameFirst, p.nameLast
            HAVING SUM(b.AB) >= ?
        ),
        league_leaders AS (
            SELECT
                yearID,
                lgID,
                MAX(HR) AS HR,
                MAX(RBI) AS RBI,
                MAX(AVG) AS AVG
            FROM season_batting
            GROUP BY yearID, lgID
        )
        SELECT
            s.nameFirst,
            s.nameLast,
            s.yearID,
            s.lgID,
            s.HR,
            s.RBI,
            ROUND(s.AVG, 3) AS AVG
        FROM season_batting s
        JOIN league_leaders l
            ON l.yearID = s.yearID
            AND l.lgID = s.lgID
            AND l.HR = s.HR
            AND l.RBI = s.RBI
            AND l.AVG = s.AVG
        ORDER BY s.yearID, s.lgID, s.nameLast, s.nameFirst
        """,
        [300],
    )


def _thirty_thirty_sql() -> AssembledSQL:
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            b.yearID,
            SUM(b.HR) AS HR,
            SUM(b.SB) AS SB
        FROM batting b
        JOIN people p ON p.playerID = b.playerID
        GROUP BY b.playerID, p.nameFirst, p.nameLast, b.yearID
        HAVING SUM(b.HR) >= ? AND SUM(b.SB) >= ?
        ORDER BY b.yearID, p.nameLast, p.nameFirst
        """,
        [30, 30],
    )


def _roster_sql(
    nickname: str,
    year: int,
    question: str,
    *,
    identity: TeamIdentity | None = None,
) -> AssembledSQL:
    if identity is None:
        identity = resolve_team_identity(question, team_name_pattern=nickname, year=year)
    if identity is not None:
        where = "b.teamID = ? AND b.yearID = ?"
        params: list[object] = [identity.team_id, year]
    else:
        where = "t.name ILIKE ? AND b.yearID = ?"
        params = [f"%{nickname}%", year]
    return AssembledSQL(
        """
        SELECT DISTINCT
            p.nameFirst,
            p.nameLast,
            t.name AS teamName,
            b.yearID
        FROM people p
        JOIN batting b ON p.playerID = b.playerID
        LEFT JOIN teams t ON b.teamID = t.teamID
        WHERE {where}
        ORDER BY p.nameLast, p.nameFirst
        """.format(where=where),
        params,
    )


def _career_home_run_sql(threshold: int) -> AssembledSQL:
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            SUM(b.HR) AS career_HR
        FROM batting b
        JOIN people p ON p.playerID = b.playerID
        GROUP BY b.playerID, p.nameFirst, p.nameLast
        HAVING SUM(b.HR) >= ?
        ORDER BY career_HR DESC, p.nameLast, p.nameFirst
        """,
        [threshold],
    )


def _career_pitching_wins_sql(threshold: int | None) -> AssembledSQL:
    having = "HAVING SUM(pi.W) >= ?" if threshold is not None else ""
    limit = "" if threshold is not None else "LIMIT ?"
    params: list[object] = [threshold] if threshold is not None else [25]
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            SUM(pi.W) AS career_W
        FROM pitching pi
        JOIN people p ON p.playerID = pi.playerID
        GROUP BY pi.playerID, p.nameFirst, p.nameLast
        {having}
        ORDER BY career_W DESC, p.nameLast, p.nameFirst
        {limit}
        """.format(having=having, limit=limit),
        params,
    )


def _career_era_sql(min_ipouts: int) -> AssembledSQL:
    era = get_stat("ERA")
    era_expr = era.aggregate_expression("pi")
    ipouts_guard = _sample_clause(era, "pi", aggregate=True, threshold="?")
    return AssembledSQL(
        f"""
        SELECT
            p.nameFirst,
            p.nameLast,
            ROUND({era_expr}, 2) AS career_ERA,
            SUM(pi.IPouts) AS IPouts
        FROM pitching pi
        JOIN people p ON p.playerID = pi.playerID
        GROUP BY pi.playerID, p.nameFirst, p.nameLast
        HAVING {ipouts_guard}
        ORDER BY career_ERA ASC, IPouts DESC, p.nameLast, p.nameFirst
        """,
        [min_ipouts],
    )


def _qualified_season_era_sql(year: int | None, min_ipouts: int) -> AssembledSQL:
    era = get_stat("ERA")
    era_expr = era.expression("pi")
    era_min_expr = era.expression("p2")
    ipouts_guard = _sample_clause(era, "pi", threshold="?")
    subquery_ipouts_guard = _sample_clause(era, "p2", threshold="?")
    if year is None:
        return AssembledSQL(
            f"""
            SELECT
                p.nameFirst,
                p.nameLast,
                pi.yearID,
                pi.lgID,
                {era_expr} AS ERA,
                pi.IPouts
            FROM pitching pi
            JOIN people p ON p.playerID = pi.playerID
            WHERE {ipouts_guard}
                AND {era_expr} IS NOT NULL
            ORDER BY pi.ERA ASC, pi.IPouts DESC, pi.yearID, pi.lgID, p.nameLast, p.nameFirst
            """,
            [min_ipouts],
        )
    return AssembledSQL(
        f"""
        SELECT
            p.nameFirst,
            p.nameLast,
            pi.yearID,
            pi.lgID,
            {era_expr} AS ERA,
            pi.IPouts
        FROM pitching pi
        JOIN people p ON p.playerID = pi.playerID
        WHERE pi.yearID = ?
            AND {ipouts_guard}
            AND {era_expr} IS NOT NULL
            AND {era_expr} = (
                SELECT MIN({era_min_expr})
                FROM pitching p2
                WHERE p2.yearID = pi.yearID
                    AND p2.lgID = pi.lgID
                    AND {subquery_ipouts_guard}
                    AND {era_min_expr} IS NOT NULL
            )
        ORDER BY pi.yearID, pi.lgID, pi.ERA, p.nameLast, p.nameFirst
        """,
        [year, min_ipouts, min_ipouts],
    )


def _qualified_season_avg_sql(year: int | None, min_ab: int) -> AssembledSQL:
    avg = get_stat("AVG")
    avg_expr = avg.expression("b")
    avg_max_expr = avg.expression("b2")
    ab_guard = _sample_clause(avg, "b", threshold="?")
    subquery_ab_guard = _sample_clause(avg, "b2", threshold="?")
    if year is None:
        return AssembledSQL(
            f"""
            SELECT
                p.nameFirst,
                p.nameLast,
                b.yearID,
                b.lgID,
                ROUND({avg_expr}, 3) AS AVG,
                b.AB
            FROM batting b
            JOIN people p ON p.playerID = b.playerID
            WHERE {ab_guard}
                AND b.AB > 0
            ORDER BY AVG DESC, b.AB DESC, b.yearID, b.lgID, p.nameLast, p.nameFirst
            """,
            [min_ab],
        )
    return AssembledSQL(
        f"""
        SELECT
            p.nameFirst,
            p.nameLast,
            b.yearID,
            b.lgID,
            ROUND({avg_expr}, 3) AS AVG,
            b.AB
        FROM batting b
        JOIN people p ON p.playerID = b.playerID
        WHERE b.yearID = ?
            AND {ab_guard}
            AND {avg_expr} = (
                SELECT MAX({avg_max_expr})
                FROM batting b2
                WHERE b2.yearID = b.yearID
                    AND b2.lgID = b.lgID
                    AND {subquery_ab_guard}
            )
        ORDER BY b.yearID, b.lgID, AVG DESC, p.nameLast, p.nameFirst
        """,
        [year, min_ab, min_ab],
    )


def _retrosheet_date_expr(alias: str) -> str:
    return (
        "CAST(COALESCE("
        f"try_strptime(CAST({alias}.date AS VARCHAR), '%Y%m%d'), "
        f"try_strptime(CAST({alias}.date AS VARCHAR), '%Y-%m-%d')"
        ") AS DATE)"
    )


def _stolen_base_streak_sql(player_name: str | None, gametype: str) -> AssembledSQL:
    return _batting_stat_streak_sql(
        _BATTING_STREAK_STATS["stolen_base"],
        player_name,
        gametype,
    )


def _batting_stat_streak_sql(
    stat: BattingStreakStat,
    player_name: str | None,
    gametype: str,
) -> AssembledSQL:
    player_filter = "AND lower(p.nameFirst || ' ' || p.nameLast) = ?" if player_name else ""
    params: list[object] = [gametype.lower()]
    if player_name:
        params.append(player_name.lower())
    streak_column = stat.streak_column
    total_column = stat.total_column
    return AssembledSQL(
        """
        WITH player_games AS (
            SELECT
                p.playerID,
                p.nameFirst,
                p.nameLast,
                COALESCE(team.name, rb.team) AS team_name,
                rb.gid AS game_id,
                CAST(strptime(CAST(rb.date AS VARCHAR), '%Y%m%d') AS DATE) AS game_date,
                COALESCE(TRY_CAST(rb.{stat_column} AS INTEGER), 0) AS stat_value,
                ROW_NUMBER() OVER (
                    PARTITION BY p.playerID
                    ORDER BY CAST(strptime(CAST(rb.date AS VARCHAR), '%Y%m%d') AS DATE), rb.gid
                ) AS player_game_number
            FROM retrosheet_batting rb
            JOIN people p ON lower(p.retroID) = lower(rb.id)
            LEFT JOIN teams team ON team.teamID = rb.team
            WHERE lower(rb.gametype) = ?
                {player_filter}
        ),
        steal_games AS (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY playerID
                    ORDER BY player_game_number
                ) AS steal_game_number
            FROM player_games
            WHERE stat_value >= 1
        ),
        streak_games AS (
            SELECT
                *,
                player_game_number - steal_game_number AS streak_group
            FROM steal_games
        ),
        streaks AS (
            SELECT
                playerID,
                nameFirst,
                nameLast,
                streak_group,
                COUNT(*) AS {streak_column},
                MIN(game_date) AS start_date,
                MAX(game_date) AS end_date,
                MIN(team_name) AS team,
                SUM(stat_value) AS {total_column},
                STRING_AGG(game_id, ', ' ORDER BY game_date, game_id) AS game_ids
            FROM streak_games
            GROUP BY playerID, nameFirst, nameLast, streak_group
        )
        SELECT
            nameFirst,
            nameLast,
            {streak_column} AS streak_games,
            strftime(start_date, '%Y-%m-%d') AS start_date,
            strftime(end_date, '%Y-%m-%d') AS end_date,
            team,
            ? AS gametype,
            ? AS stat,
            {total_column} AS stat_total,
            ? AS stat_label,
            ? AS streak_label,
            ? AS event_label,
            game_ids,
            ? AS definition,
            {streak_column} AS {streak_column}
        FROM streaks
        ORDER BY {streak_column} DESC, end_date ASC, nameLast, nameFirst
        LIMIT 1
        """.format(
            player_filter=player_filter,
            stat_column=stat.column,
            streak_column=streak_column,
            total_column=total_column,
        ),
        [
            *params,
            gametype.lower(),
            stat.stat_key,
            stat.event_label,
            stat.streak_label,
            stat.event_label,
            (f"Consecutive player games appeared in with at least one {stat.definition_label}."),
        ],
    )


def _player_batting_game_log_sql(
    stat: BattingStreakStat,
    player_name: str,
    threshold: int,
    year: Any | None,
    gametype: str,
) -> AssembledSQL:
    year_filter = "AND date_part('year', game_date) = ?" if year is not None else ""
    stat_code = _BATTING_GAME_LOG_STAT_CODES[stat.stat_key]
    params: list[object] = [player_name.lower(), gametype.lower()]
    if year is not None:
        params.append(int(year))
    params.append(threshold)
    game_date = _retrosheet_date_expr("rb")
    return AssembledSQL(
        """
        WITH player_games AS (
            SELECT
                {game_date} AS game_date,
                rb.gid AS game_id,
                p.nameFirst,
                p.nameLast,
                COALESCE(team.name, rb.team) AS team,
                COALESCE(
                    NULLIF(upper(rb.opp), ''),
                    CASE
                        WHEN upper(rb.team) <> upper(substr(rb.gid, 1, 3))
                        THEN upper(substr(rb.gid, 1, 3))
                        ELSE NULL
                    END
                ) AS opponent_team_id,
                TRY_CAST(rb.{stat_column} AS INTEGER) AS stat_value,
                lower(rb.gametype) AS gametype
            FROM retrosheet_batting rb
            JOIN people p ON lower(p.retroID) = lower(rb.id)
            LEFT JOIN teams team ON team.teamID = rb.team
            WHERE lower(p.nameFirst || ' ' || p.nameLast) = ?
                AND lower(rb.gametype) = ?
        )
        SELECT
            strftime(game_date, '%Y-%m-%d') AS date,
            game_id,
            nameFirst,
            nameLast,
            team,
            COALESCE(opponent.name, opponent_team_id) AS opponent_team,
            '{stat_code}' AS stat,
            stat_value,
            gametype
        FROM player_games
        LEFT JOIN teams opponent ON opponent.teamID = opponent_team_id
        WHERE TRUE
            {year_filter}
            AND stat_value >= ?
        ORDER BY game_date, game_id
        """.format(
            game_date=game_date,
            stat_column=stat.column,
            stat_code=stat_code,
            year_filter=year_filter,
        ),
        params,
    )


def _pitcher_strikeout_side_count_sql(
    player_name: str,
    year: Any | None,
    opponent_team_pattern: Any | None = None,
) -> AssembledSQL:
    opponent_join = (
        "LEFT JOIN teams opponent ON opponent.teamID = e.opponent_team_id"
        if opponent_team_pattern is not None
        else ""
    )
    opponent_filter = (
        "AND (lower(opponent.name) LIKE ? OR lower(e.opponent_team_id) = ?)"
        if opponent_team_pattern is not None
        else ""
    )
    opponent_select = (
        "opponent.name AS opponent_team,"
        if opponent_team_pattern is not None
        else "NULL AS opponent_team,"
    )
    opponent_group = ", opponent.name" if opponent_team_pattern is not None else ""
    if year is not None:
        params: list[object] = [player_name.lower(), int(year)]
        if opponent_team_pattern is not None:
            team_pattern = str(opponent_team_pattern).lower()
            params.extend([f"%{team_pattern}%", team_pattern])
        return AssembledSQL(
            """
            SELECT
                p.nameFirst,
                p.nameLast,
                e.year,
                {opponent_select}
                COUNT(*) AS strikeout_side_count,
                SUM(CASE WHEN e.started_half_inning THEN 1 ELSE 0 END) AS strict_started_half_count,
                CONCAT(
                    'All three outs recorded by the pitcher in a half-inning were strikeouts; ',
                    'strict_started_half_count requires the pitcher to have begun the half-inning.'
                ) AS definition
            FROM retrosheet_pitcher_strikeout_side_events e
            JOIN people p ON lower(p.retroID) = lower(e.retroID)
            {opponent_join}
            WHERE lower(p.nameFirst || ' ' || p.nameLast) = ?
                AND e.year = ?
                {opponent_filter}
            GROUP BY p.playerID, p.nameFirst, p.nameLast, e.year{opponent_group}
            """.format(
                opponent_join=opponent_join,
                opponent_filter=opponent_filter,
                opponent_select=opponent_select,
                opponent_group=opponent_group,
            ),
            params,
        )

    params = [player_name.lower()]
    if opponent_team_pattern is not None:
        team_pattern = str(opponent_team_pattern).lower()
        params.extend([f"%{team_pattern}%", team_pattern])
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            {opponent_select}
            COUNT(*) AS career_strikeout_side_count,
            SUM(CASE WHEN e.started_half_inning THEN 1 ELSE 0 END) AS strict_started_half_count,
            MIN(e.year) AS first_year,
            MAX(e.year) AS last_year,
            CONCAT(
                'All three outs recorded by the pitcher in a half-inning were strikeouts; ',
                'strict_started_half_count requires the pitcher to have begun the half-inning.'
            ) AS definition
        FROM retrosheet_pitcher_strikeout_side_events e
        JOIN people p ON lower(p.retroID) = lower(e.retroID)
        {opponent_join}
        WHERE lower(p.nameFirst || ' ' || p.nameLast) = ?
            {opponent_filter}
        GROUP BY p.playerID, p.nameFirst, p.nameLast{opponent_group}
        """.format(
            opponent_join=opponent_join,
            opponent_filter=opponent_filter,
            opponent_select=opponent_select,
            opponent_group=opponent_group,
        ),
        params,
    )


def _pitcher_strikeout_side_leaders_sql(limit: int) -> AssembledSQL:
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            COUNT(*) AS career_strikeout_side_count,
            SUM(CASE WHEN e.started_half_inning THEN 1 ELSE 0 END) AS strict_started_half_count,
            MIN(e.year) AS first_year,
            MAX(e.year) AS last_year,
            CONCAT(
                'All three outs recorded by the pitcher in a half-inning were strikeouts; ',
                'strict_started_half_count requires the pitcher to have begun the half-inning.'
            ) AS definition
        FROM retrosheet_pitcher_strikeout_side_events e
        JOIN people p ON lower(p.retroID) = lower(e.retroID)
        GROUP BY p.playerID, p.nameFirst, p.nameLast
        ORDER BY career_strikeout_side_count DESC, p.nameLast, p.nameFirst
        LIMIT ?
        """,
        [limit],
    )


def _pitcher_strikeout_side_game_log_sql(
    player_name: str,
    year: Any | None,
    opponent_team_pattern: Any | None = None,
) -> AssembledSQL:
    year_filter = "AND e.year = ?" if year is not None else ""
    params: list[object] = [player_name.lower()]
    if year is not None:
        params.append(int(year))
    opponent_filter = (
        "AND (lower(opponent.name) LIKE ? OR lower(e.opponent_team_id) = ?)"
        if opponent_team_pattern is not None
        else ""
    )
    if opponent_team_pattern is not None:
        team_pattern = str(opponent_team_pattern).lower()
        params.extend([f"%{team_pattern}%", team_pattern])
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            e.year,
            e.game_id,
            e.inning,
            CASE WHEN e.batting_home = 1 THEN 'bottom' ELSE 'top' END AS half_inning,
            e.started_half_inning,
            e.opponent_team_id,
            COALESCE(opponent.name, e.opponent_team_id) AS opponent_team,
            e.pitcher_team_id,
            COALESCE(pitcher_team.name, e.pitcher_team_id) AS pitcher_team,
            e.site,
            e.event_sequence,
            CONCAT(
                'All three outs recorded by the pitcher in a half-inning were strikeouts; ',
                'game_id is the Retrosheet game identifier.'
            ) AS definition
        FROM retrosheet_pitcher_strikeout_side_events e
        JOIN people p ON lower(p.retroID) = lower(e.retroID)
        LEFT JOIN teams opponent ON opponent.teamID = e.opponent_team_id
        LEFT JOIN teams pitcher_team ON pitcher_team.teamID = e.pitcher_team_id
        WHERE lower(p.nameFirst || ' ' || p.nameLast) = ?
            {year_filter}
            {opponent_filter}
        ORDER BY e.year, e.game_id, e.inning, e.batting_home
        """.format(year_filter=year_filter, opponent_filter=opponent_filter),
        params,
    )


def _pitcher_daily_strikeout_game_log_sql(
    player_name: str,
    threshold: int,
    year: Any | None,
    gametype: str,
) -> AssembledSQL:
    year_filter = (
        "AND TRY_CAST(SUBSTR(CAST(rp.date AS VARCHAR), 1, 4) AS INTEGER) = ?"
        if year is not None
        else ""
    )
    params: list[object] = [player_name.lower(), threshold, gametype.lower()]
    if year is not None:
        params.append(int(year))
    return AssembledSQL(
        """
        SELECT
            strftime(
                CAST(strptime(CAST(rp.date AS VARCHAR), '%Y%m%d') AS DATE),
                '%Y-%m-%d'
            ) AS game_date,
            rp.gid AS game_id,
            p.nameFirst,
            p.nameLast,
            rp.team AS team,
            rp.opp AS opponent,
            'SO' AS stat,
            TRY_CAST(rp.p_k AS INTEGER) AS stat_value,
            lower(rp.gametype) AS gametype
        FROM retrosheet_pitching rp
        JOIN people p ON lower(p.retroID) = lower(rp.id)
        WHERE lower(p.nameFirst || ' ' || p.nameLast) = ?
            AND TRY_CAST(rp.p_k AS INTEGER) >= ?
            AND lower(rp.gametype) = ?
            {year_filter}
        ORDER BY game_date, game_id
        """.format(year_filter=year_filter),
        params,
    )


def _sample_clause(
    stat: StatDefinition,
    alias: str,
    *,
    threshold: int | str,
    aggregate: bool = False,
) -> str:
    clause = stat.sample_clause(alias, aggregate=aggregate, threshold=threshold)
    if clause is None:
        raise ValueError(f"Stat {stat.canonical} has no sample clause")
    return clause
