"""Deterministic templates for the separately governed Retrosheet query surface."""

# ruff: noqa: E501 -- keeping reviewed SQL and regex fragments readable is safer than splitting.

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from baseball_rag.year_parsing import extract_spelled_year


@dataclass(frozen=True)
class RetrosheetTemplateMatch:
    """One matched, parameterized, read-only Retrosheet query."""

    template_id: str
    sql: str
    params: tuple[object, ...]
    source_detail: str
    unsupported_reason: str | None = None


@dataclass(frozen=True)
class _BattingStat:
    key: str
    column: str
    streak_column: str
    total_column: str
    streak_label: str
    event_label: str
    source_label: str


@dataclass(frozen=True)
class _Template:
    template_id: str
    source_detail: str
    matcher: Callable[[str], Mapping[str, object] | None]
    assembler: Callable[[Mapping[str, object]], tuple[str, tuple[object, ...], str | None]]


_BATTING_STATS = {
    "stolen_base": _BattingStat(
        "stolen_base",
        "b_sb",
        "stolen_base_streak_games",
        "stolen_bases",
        "stolen-base streak",
        "stolen base",
        "stolen-base",
    ),
    "hit": _BattingStat(
        "hit",
        "b_h",
        "hit_streak_games",
        "hits",
        "hit streak",
        "hit",
        "hit",
    ),
    "home_run": _BattingStat(
        "home_run",
        "b_hr",
        "home_run_streak_games",
        "home_runs",
        "home-run game streak",
        "home run",
        "home-run game",
    ),
    "rbi": _BattingStat(
        "rbi",
        "b_rbi",
        "rbi_streak_games",
        "rbi",
        "RBI game streak",
        "RBI",
        "RBI game",
    ),
    "run": _BattingStat(
        "run",
        "b_r",
        "run_scored_streak_games",
        "runs_scored",
        "run-scored streak",
        "run scored",
        "run-scored",
    ),
}

_GAME_LOG_STAT_CODES = {
    "stolen_base": "SB",
    "hit": "H",
    "home_run": "HR",
    "rbi": "RBI",
    "run": "R",
}

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

PUBLISHED_RELEASE_TEMPLATE_IDS = frozenset(
    {
        "pitcher_strikeout_side_count",
        "pitcher_strikeout_side_game_log",
        "pitcher_strikeout_side_leaders",
    }
)


def match_retrosheet_template(question: str) -> RetrosheetTemplateMatch | None:
    """Match one of the six published Retrosheet template families."""
    normalized = _normalize(question)
    for template in _TEMPLATES:
        facts = template.matcher(normalized)
        if facts is None:
            continue
        sql, params, unsupported_reason = template.assembler(facts)
        return RetrosheetTemplateMatch(
            template_id=template.template_id,
            sql=sql,
            params=params,
            source_detail=template.source_detail,
            unsupported_reason=unsupported_reason,
        )
    return None


def match_published_retrosheet_template(question: str) -> RetrosheetTemplateMatch | None:
    """Match only a template backed by the immutable public Release Bundle."""
    matched = match_retrosheet_template(question)
    if matched is None or matched.template_id not in PUBLISHED_RELEASE_TEMPLATE_IDS:
        return None
    return matched


def _normalize(question: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", question.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _year(question: str) -> int | None:
    matched = re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b", question)
    return int(matched.group(1)) if matched else extract_spelled_year(question)


def _postseason(question: str) -> bool:
    return bool(re.search(r"\b(?:postseason|playoffs?|world series)\b", question))


def _strikeout_side(question: str) -> bool:
    return bool(re.search(r"\b(?:strike|struck) out the side\b|\bstrikeout side\b", question))


def _opponent(question: str) -> tuple[str | None, bool]:
    if not re.search(r"\b(?:against|versus|vs)\b", question):
        return None, False
    for nickname in _TEAM_NICKNAMES:
        if re.search(rf"\b{re.escape(nickname)}\b", question):
            return nickname, False
    matched = re.search(
        r"\b(?:against|versus|vs)\s+(?:the\s+)?(?P<team_id>[a-z0-9]{2,3})\b",
        question,
    )
    return (matched.group("team_id"), False) if matched else (None, True)


def _unsupported(reason: str) -> tuple[str, tuple[object, ...], str]:
    return "SELECT ? AS unsupported_reason WHERE FALSE", (reason,), reason


def _match_pitcher_daily(question: str) -> Mapping[str, object] | None:
    if not re.search(r"\b(?:strikeout|strikeouts|struck out|strike out)\b", question):
        return None
    if not re.search(r"\b(?:games?|game log|game by game)\b", question) or _strikeout_side(
        question
    ):
        return None
    reason = None
    if re.search(r"\b(?:team|teams)\b", question):
        reason = "Team pitching game logs are not modeled by this player game-log template."
    elif re.search(r"\b(?:pitch by pitch|pitch level|pitch counts?|pitches)\b", question):
        reason = "Pitch-level details are not modeled in Retrosheet daily pitching logs."
    elif re.search(r"\b(?:inning by inning|inning level|innings?)\b", question):
        reason = "Inning-level pitching events are not modeled in Retrosheet daily pitching logs."
    player = None
    for pattern in (
        r"\b(?:show|list)\s+(?P<player>[a-z][a-z .'\\-]+?)\s+(?:(?:postseason|playoff|regular season)\s+)?games?\s+with\b",
        r"\bwhat games did\s+(?P<player>[a-z][a-z .'\\-]+?)\s+(?:strike|struck) out\b",
        r"\b(?P<player>[a-z][a-z .'\\-]+?)\s+strikeout\s+game log\b",
    ):
        matched = re.search(pattern, question)
        if matched:
            candidate = re.sub(r"^(?:show|list)\s+", "", matched.group("player").strip())
            if candidate not in {"what", "who", "which pitchers"}:
                player = candidate
                break
    if reason is None and player is None:
        return None
    threshold_match = re.search(
        r"\b(?:at least|minimum|min|with|>=)\s+(\d{1,2})\s+(?:strikeouts?|ks?|batters)\b",
        question,
    ) or re.search(r"\b(?:strike|struck) out\s+(\d{1,2})\s+(?:batters|hitters)\b", question)
    return {
        "player": player,
        "threshold": int(threshold_match.group(1)) if threshold_match else 0,
        "year": _year(question),
        "gametype": "playoff" if _postseason(question) else "regular",
        "reason": reason,
    }


def _assemble_pitcher_daily(
    facts: Mapping[str, object],
) -> tuple[str, tuple[object, ...], str | None]:
    if facts["reason"]:
        return _unsupported(str(facts["reason"]))
    if facts["player"] is None:
        return _unsupported("Pitcher game-log queries need a player full name.")
    year_filter = (
        "AND TRY_CAST(SUBSTR(CAST(rp.date AS VARCHAR), 1, 4) AS INTEGER) = ?"
        if facts["year"] is not None
        else ""
    )
    params: list[object] = [str(facts["player"]).lower(), facts["threshold"], facts["gametype"]]
    if facts["year"] is not None:
        params.append(facts["year"])
    return (
        f"""
        SELECT
            strftime(CAST(strptime(CAST(rp.date AS VARCHAR), '%Y%m%d') AS DATE), '%Y-%m-%d') AS game_date,
            rp.gid AS game_id, p.nameFirst, p.nameLast,
            team.name AS team, opponent.name AS opponent,
            'SO' AS stat, TRY_CAST(rp.p_k AS INTEGER) AS stat_value, lower(rp.gametype) AS gametype
        FROM retrosheet_pitching rp
        JOIN people p ON lower(p.retroID) = lower(rp.id)
        JOIN retrosheet_team_reference team
          ON team.retrosheetTeamID = rp.team
         AND team.yearID = TRY_CAST(SUBSTR(CAST(rp.date AS VARCHAR), 1, 4) AS INTEGER)
        JOIN retrosheet_team_reference opponent
          ON opponent.retrosheetTeamID = rp.opp
         AND opponent.yearID = TRY_CAST(SUBSTR(CAST(rp.date AS VARCHAR), 1, 4) AS INTEGER)
        WHERE lower(p.nameFirst || ' ' || p.nameLast) = ?
          AND TRY_CAST(rp.p_k AS INTEGER) >= ?
          AND lower(rp.gametype) = ?
          {year_filter}
        ORDER BY game_date, game_id
    """,
        tuple(params),
        None,
    )


def _match_side_leaders(question: str) -> Mapping[str, object] | None:
    if not _strikeout_side(question) or _postseason(question) or _year(question) is not None:
        return None
    if not re.search(r"\bcareers?\b", question) or "pitcher" not in question:
        return None
    if not re.search(r"\b(?:most|leaders?|leaderboard|top)\b", question):
        return None
    return {"limit": 10}


def _assemble_side_leaders(facts: Mapping[str, object]) -> tuple[str, tuple[object, ...], None]:
    return (
        """
        SELECT p.nameFirst, p.nameLast,
            COUNT(*) AS career_strikeout_side_count,
            SUM(CASE WHEN e.started_half_inning THEN 1 ELSE 0 END) AS strict_started_half_count,
            MIN(e.year) AS first_year, MAX(e.year) AS last_year,
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
        (facts["limit"],),
        None,
    )


def _match_side_count(question: str) -> Mapping[str, object] | None:
    if _postseason(question):
        return None
    year = _year(question)
    if year is None and "career" not in question:
        return None
    matched = re.search(
        r"\b(?:how many times\s+)?(?:did|has)\s+(?P<player>[a-z][a-z .'\\-]+?)\s+(?:strike|struck) out the side\b",
        question,
    )
    if not matched or matched.group("player").strip() in {"which pitchers", "who"}:
        return None
    opponent, unknown = _opponent(question)
    return {
        "player": matched.group("player").strip(),
        "year": year,
        "opponent": opponent,
        "unknown": unknown,
    }


def _assemble_side_count(facts: Mapping[str, object]) -> tuple[str, tuple[object, ...], str | None]:
    if facts["unknown"]:
        return _unsupported(
            "Opponent filters need a recognized team nickname or Retrosheet team code."
        )
    opponent = facts["opponent"]
    join = (
        "LEFT JOIN retrosheet_team_reference opponent "
        "ON opponent.retrosheetTeamID = e.opponent_team_id AND opponent.yearID = e.year"
        if opponent
        else ""
    )
    where = "AND (lower(opponent.name) LIKE ? OR lower(e.opponent_team_id) = ?)" if opponent else ""
    select = "opponent.name AS opponent_team," if opponent else "NULL AS opponent_team,"
    group = ", opponent.name" if opponent else ""
    params: list[object] = [str(facts["player"]).lower()]
    if facts["year"] is not None:
        params.append(facts["year"])
    if opponent:
        pattern = str(opponent).lower()
        params.extend([f"%{pattern}%", pattern])
    if facts["year"] is not None:
        return (
            f"""
            SELECT p.nameFirst, p.nameLast, e.year, {select}
                COUNT(*) AS strikeout_side_count,
                SUM(CASE WHEN e.started_half_inning THEN 1 ELSE 0 END) AS strict_started_half_count,
                CONCAT(
                    'All three outs recorded by the pitcher in a half-inning were strikeouts; ',
                    'strict_started_half_count requires the pitcher to have begun the half-inning.'
                ) AS definition
            FROM retrosheet_pitcher_strikeout_side_events e
            JOIN people p ON lower(p.retroID) = lower(e.retroID)
            {join}
            WHERE lower(p.nameFirst || ' ' || p.nameLast) = ? AND e.year = ? {where}
            GROUP BY p.playerID, p.nameFirst, p.nameLast, e.year{group}
        """,
            tuple(params),
            None,
        )
    return (
        f"""
        SELECT p.nameFirst, p.nameLast, {select}
            COUNT(*) AS career_strikeout_side_count,
            SUM(CASE WHEN e.started_half_inning THEN 1 ELSE 0 END) AS strict_started_half_count,
            MIN(e.year) AS first_year, MAX(e.year) AS last_year,
            CONCAT(
                'All three outs recorded by the pitcher in a half-inning were strikeouts; ',
                'strict_started_half_count requires the pitcher to have begun the half-inning.'
            ) AS definition
        FROM retrosheet_pitcher_strikeout_side_events e
        JOIN people p ON lower(p.retroID) = lower(e.retroID)
        {join}
        WHERE lower(p.nameFirst || ' ' || p.nameLast) = ? {where}
        GROUP BY p.playerID, p.nameFirst, p.nameLast{group}
    """,
        tuple(params),
        None,
    )


def _match_side_log(question: str) -> Mapping[str, object] | None:
    if _postseason(question) or not _strikeout_side(question):
        return None
    if re.search(r"\b(?:how many|how often|count)\b", question):
        return None
    if not re.search(r"\b(?:when|show|list|games?|game log|game by game)\b", question):
        return None
    matched = re.search(
        r"\b(?:when did|show|list|which games did|what games did)?\s*(?P<player>[a-z][a-z .'\\-]+?)\s+(?:(?:strike|struck) out the side|strikeout side)\b",
        question,
    )
    if not matched or matched.group("player").strip() in {"which pitchers", "who"}:
        return None
    opponent, unknown = _opponent(question)
    return {
        "player": matched.group("player").strip(),
        "year": _year(question),
        "opponent": opponent,
        "unknown": unknown,
    }


def _assemble_side_log(facts: Mapping[str, object]) -> tuple[str, tuple[object, ...], str | None]:
    if facts["unknown"]:
        return _unsupported(
            "Opponent filters need a recognized team nickname or Retrosheet team code."
        )
    year_filter = "AND e.year = ?" if facts["year"] is not None else ""
    opponent_filter = (
        "AND (lower(opponent.name) LIKE ? OR lower(e.opponent_team_id) = ?)"
        if facts["opponent"]
        else ""
    )
    params: list[object] = [str(facts["player"]).lower()]
    if facts["year"] is not None:
        params.append(facts["year"])
    if facts["opponent"]:
        pattern = str(facts["opponent"]).lower()
        params.extend([f"%{pattern}%", pattern])
    return (
        f"""
        SELECT p.nameFirst, p.nameLast, e.year, e.game_id, e.inning,
            CASE WHEN e.batting_home = 1 THEN 'bottom' ELSE 'top' END AS half_inning,
            e.started_half_inning, e.opponent_team_id,
            opponent.name AS opponent_team,
            e.pitcher_team_id, pitcher_team.name AS pitcher_team,
            e.site, e.event_sequence,
            CONCAT(
                'All three outs recorded by the pitcher in a half-inning were strikeouts; ',
                'game_id is the Retrosheet game identifier.'
            ) AS definition
        FROM retrosheet_pitcher_strikeout_side_events e
        JOIN people p ON lower(p.retroID) = lower(e.retroID)
        LEFT JOIN retrosheet_team_reference opponent
          ON opponent.retrosheetTeamID = e.opponent_team_id AND opponent.yearID = e.year
        LEFT JOIN retrosheet_team_reference pitcher_team
          ON pitcher_team.retrosheetTeamID = e.pitcher_team_id AND pitcher_team.yearID = e.year
        WHERE lower(p.nameFirst || ' ' || p.nameLast) = ? {year_filter} {opponent_filter}
        ORDER BY e.year, e.game_id, e.inning, e.batting_home
    """,
        tuple(params),
        None,
    )


def _detect_batting_stats(question: str) -> list[_BattingStat]:
    patterns = {
        "stolen_base": r"\bstolen bases?\b|\bsteal(?:s|ing)?\b|\bstole\b",
        "hit": r"\bhits\b|\bhitting streak\b|\bhit streak\b|\bhit\s+game log\b|\bhit\s+games\b|\bwith\s+(?:at least\s+)?\d{1,2}\s+hits?\b",
        "home_run": r"\bhome runs?\b|\bhomers?\b|\bhrs?\b",
        "rbi": r"\brbis?\b|\bruns? batted in\b",
        "run": r"\bruns?[- ]scored\b|\bscored runs?\b",
    }
    return [stat for key, stat in _BATTING_STATS.items() if re.search(patterns[key], question)]


def _stat_phrase(stat: _BattingStat) -> str:
    return {
        "stolen_base": r"(?:stolen bases?|steals?|stole)",
        "hit": r"(?:hitting|hits?)",
        "home_run": r"(?:home runs?|homers?|hrs?)",
        "rbi": r"(?:rbis?|runs? batted in)",
        "run": r"(?:runs?[- ]scored|runs? scored|scored runs?)",
    }[stat.key]


def _batting_reason(question: str, stat: _BattingStat, *, streak: bool) -> str | None:
    if re.search(r"\b(?:team|teams)\b", question):
        return (
            f"Team {stat.source_label} {'streaks' if streak else 'game logs'} are not modeled yet."
        )
    if len({item.key for item in _detect_batting_stats(question)}) > 1:
        return f"Multi-stat batting {'streaks' if streak else 'game logs'} are not modeled yet."
    if re.search(r"\b(?:play|plays|plate appearance|at bat|inning|innings)\b", question):
        return f"Play-level or inning-level batting {'streaks' if streak else 'details'} are not modeled yet."
    if stat.key == "stolen_base" and re.search(
        r"\b(?:caught stealing|without being caught|without getting caught)\b", question
    ):
        return "Caught-stealing-aware stolen-base attempts need play-level modeling."
    if stat.key == "stolen_base" and re.search(
        r"\b(?:stealing|steal|stolen)\s+(?:second|third|home)\b", question
    ):
        return "Base-specific stolen-base details are not modeled yet."
    return None


def _match_batting_streak(question: str) -> Mapping[str, object] | None:
    stats = _detect_batting_stats(question)
    if len({stat.key for stat in stats}) != 1 or "streak" not in question:
        return None
    if not re.search(r"\b(?:longest|best|record|most|leader)\b", question):
        return None
    stat = stats[0]
    player = None
    phrase = _stat_phrase(stat)
    for pattern in (
        rf"\b(?:what (?:was|is) )?(?P<player>[a-z][a-z .'\\-]+?)(?: s)?\s+(?:longest|best)\s+(?:postseason\s+)?{phrase}\s+streak\b",
        rf"\b(?:longest|best|record|most|leader)\s+(?:postseason\s+)?{phrase}\s+streak\s+(?:for|by)\s+(?P<player>[a-z][a-z .'\\-]+?)\b",
    ):
        matched = re.search(pattern, question)
        if matched and not re.match(r"^(?:what|who|which|the)\b", matched.group("player")):
            player = matched.group("player").strip()
            break
    return {
        "stat": stat,
        "player": player,
        "gametype": "playoff" if _postseason(question) else "regular",
        "reason": _batting_reason(question, stat, streak=True),
    }


def _assemble_batting_streak(
    facts: Mapping[str, object],
) -> tuple[str, tuple[object, ...], str | None]:
    if facts["reason"]:
        return _unsupported(str(facts["reason"]))
    stat = facts["stat"]
    assert isinstance(stat, _BattingStat)
    player_filter = "AND lower(p.nameFirst || ' ' || p.nameLast) = ?" if facts["player"] else ""
    params: list[object] = [facts["gametype"]]
    if facts["player"]:
        params.append(str(facts["player"]).lower())
    params.extend(
        [
            facts["gametype"],
            stat.key,
            stat.event_label,
            stat.streak_label,
            stat.event_label,
            f"Consecutive player games appeared in with at least one {stat.event_label}.",
        ]
    )
    return (
        f"""
        WITH player_games AS (
            SELECT p.playerID, p.nameFirst, p.nameLast, team.name AS team_name,
                rb.gid AS game_id, CAST(strptime(CAST(rb.date AS VARCHAR), '%Y%m%d') AS DATE) AS game_date,
                COALESCE(TRY_CAST(rb.{stat.column} AS INTEGER), 0) AS stat_value,
                ROW_NUMBER() OVER (PARTITION BY p.playerID ORDER BY CAST(strptime(CAST(rb.date AS VARCHAR), '%Y%m%d') AS DATE), rb.gid) AS player_game_number
            FROM retrosheet_batting rb
            JOIN people p ON lower(p.retroID) = lower(rb.id)
            LEFT JOIN retrosheet_team_reference team
              ON team.retrosheetTeamID = rb.team
             AND team.yearID = date_part('year', CAST(strptime(CAST(rb.date AS VARCHAR), '%Y%m%d') AS DATE))
            WHERE lower(rb.gametype) = ? {player_filter}
        ), qualifying_games AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY playerID ORDER BY player_game_number) AS qualifying_number
            FROM player_games WHERE stat_value >= 1
        ), streak_games AS (
            SELECT *, player_game_number - qualifying_number AS streak_group FROM qualifying_games
        ), streaks AS (
            SELECT playerID, nameFirst, nameLast, streak_group, COUNT(*) AS {stat.streak_column},
                MIN(game_date) AS start_date, MAX(game_date) AS end_date, MIN(team_name) AS team,
                SUM(stat_value) AS {stat.total_column}, STRING_AGG(game_id, ', ' ORDER BY game_date, game_id) AS game_ids
            FROM streak_games GROUP BY playerID, nameFirst, nameLast, streak_group
        )
        SELECT nameFirst, nameLast, {stat.streak_column} AS streak_games,
            strftime(start_date, '%Y-%m-%d') AS start_date, strftime(end_date, '%Y-%m-%d') AS end_date,
            team, ? AS gametype, ? AS stat, {stat.total_column} AS stat_total, ? AS stat_label,
            ? AS streak_label, ? AS event_label, game_ids, ? AS definition,
            {stat.streak_column} AS {stat.streak_column}
        FROM streaks
        ORDER BY {stat.streak_column} DESC, end_date ASC, nameLast, nameFirst
        LIMIT 1
    """,
        tuple(params),
        None,
    )


def _match_batting_log(question: str) -> Mapping[str, object] | None:
    stats = _detect_batting_stats(question)
    if (
        not stats
        or "streak" in question
        or not re.search(
            r"\b(?:show|list|what games|which games|games?|game log|game by game)\b", question
        )
    ):
        return None
    stat = stats[0]
    phrase = _stat_phrase(stat)
    player = None
    for pattern in (
        r"\b(?:show|list)\s+(?P<player>[a-z][a-z .'\\-]+?)(?: s)?\s+games?\s+with\b",
        r"\bwhat games did\s+(?P<player>[a-z][a-z .'\\-]+?)\s+hit\s+\d{1,2}\s+(?:home runs?|homers?|hrs?)\b",
        rf"\b(?:what|which) games did\s+(?P<player>[a-z][a-z .'\\-]+?)\s+{phrase}\b",
        rf"\b(?P<player>[a-z][a-z .'\\-]+?)\s+{phrase}\s+game log\b",
    ):
        matched = re.search(pattern, question)
        if matched:
            player = re.sub(r"^(?:show|list)\s+", "", matched.group("player").strip())
            break
    reason = _batting_reason(question, stat, streak=False)
    if reason is None and player is None:
        return None
    threshold = 1
    matched = re.search(rf"\b(?:at least|minimum|min|with|>=)\s+(\d{{1,2}})\s+{phrase}\b", question)
    if not matched and stat.key == "stolen_base":
        matched = re.search(r"\b(?:steal|stole)\s+(\d{1,2})\s+bases?\b", question)
    if not matched and stat.key == "home_run":
        matched = re.search(r"\bhit\s+(\d{1,2})\s+(?:home runs?|homers?|hrs?)\b", question)
    if matched:
        threshold = int(matched.group(1))
    return {
        "stat": stat,
        "player": player,
        "threshold": threshold,
        "year": _year(question),
        "gametype": "playoff" if _postseason(question) else "regular",
        "reason": reason,
    }


def _assemble_batting_log(
    facts: Mapping[str, object],
) -> tuple[str, tuple[object, ...], str | None]:
    if facts["reason"]:
        return _unsupported(str(facts["reason"]))
    if facts["player"] is None:
        return _unsupported("Player batting game logs need a player full name.")
    stat = facts["stat"]
    assert isinstance(stat, _BattingStat)
    year_filter = "AND date_part('year', game_date) = ?" if facts["year"] is not None else ""
    params: list[object] = [str(facts["player"]).lower(), facts["gametype"]]
    if facts["year"] is not None:
        params.append(facts["year"])
    params.append(facts["threshold"])
    date_expr = "CAST(COALESCE(try_strptime(CAST(rb.date AS VARCHAR), '%Y%m%d'), try_strptime(CAST(rb.date AS VARCHAR), '%Y-%m-%d')) AS DATE)"
    return (
        f"""
        WITH player_games AS (
            SELECT {date_expr} AS game_date, rb.gid AS game_id, p.nameFirst, p.nameLast,
                team.name AS team,
                COALESCE(NULLIF(upper(rb.opp), ''), CASE WHEN upper(rb.team) <> upper(substr(rb.gid, 1, 3)) THEN upper(substr(rb.gid, 1, 3)) ELSE NULL END) AS opponent_team_id,
                TRY_CAST(rb.{stat.column} AS INTEGER) AS stat_value, lower(rb.gametype) AS gametype
            FROM retrosheet_batting rb
            JOIN people p ON lower(p.retroID) = lower(rb.id)
            LEFT JOIN retrosheet_team_reference team
              ON team.retrosheetTeamID = rb.team
             AND team.yearID = date_part('year', {date_expr})
            WHERE lower(p.nameFirst || ' ' || p.nameLast) = ? AND lower(rb.gametype) = ?
        )
        SELECT strftime(game_date, '%Y-%m-%d') AS date, game_id, nameFirst, nameLast, team,
            opponent.name AS opponent_team,
            '{_GAME_LOG_STAT_CODES[stat.key]}' AS stat, stat_value, gametype
        FROM player_games
        LEFT JOIN retrosheet_team_reference opponent
          ON opponent.retrosheetTeamID = opponent_team_id
         AND opponent.yearID = date_part('year', game_date)
        WHERE TRUE {year_filter} AND stat_value >= ?
        ORDER BY game_date, game_id
    """,
        tuple(params),
        None,
    )


_TEMPLATES = (
    _Template(
        "batting_stat_streak",
        "Retrosheet game-level batting streak template.",
        _match_batting_streak,
        _assemble_batting_streak,
    ),
    _Template(
        "player_batting_game_log",
        "Retrosheet daily batting player game-log template.",
        _match_batting_log,
        _assemble_batting_log,
    ),
    _Template(
        "pitcher_daily_strikeout_game_log",
        "Retrosheet daily pitching strikeout game-log template.",
        _match_pitcher_daily,
        _assemble_pitcher_daily,
    ),
    _Template(
        "pitcher_strikeout_side_leaders",
        "Retrosheet event-derived strikeout-side leaderboard template.",
        _match_side_leaders,
        _assemble_side_leaders,
    ),
    _Template(
        "pitcher_strikeout_side_game_log",
        "Retrosheet event-derived strikeout-side game-log template.",
        _match_side_log,
        _assemble_side_log,
    ),
    _Template(
        "pitcher_strikeout_side_count",
        "Retrosheet event-derived strikeout-side count template.",
        _match_side_count,
        _assemble_side_count,
    ),
)
