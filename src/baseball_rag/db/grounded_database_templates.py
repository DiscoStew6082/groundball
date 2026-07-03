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
    "marlins",
    "mets",
    "phillies",
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


def _match_pitcher_strikeout_side_count(q: str) -> Mapping[str, Any] | None:
    if "career" not in q:
        return None
    if _extract_year(q) is not None or "postseason" in q or "playoff" in q:
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
    }


def _assemble_pitcher_strikeout_side_count(
    facts: Mapping[str, Any],
    _question: str,
) -> AssembledSQL:
    return _pitcher_strikeout_side_count_sql(str(facts["player_name"]))


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
        template_id="pitcher_strikeout_side_count",
        description="Retrosheet event-derived pitcher strikeout-side career counts",
        matcher=_match_pitcher_strikeout_side_count,
        assemble=_assemble_pitcher_strikeout_side_count,
        source_detail=_source_detail(
            "Matched local Retrosheet event-derived strikeout-side count template."
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


def _pitcher_strikeout_side_count_sql(player_name: str) -> AssembledSQL:
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
        WHERE lower(p.nameFirst || ' ' || p.nameLast) = ?
        GROUP BY p.playerID, p.nameFirst, p.nameLast
        """,
        [player_name.lower()],
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
