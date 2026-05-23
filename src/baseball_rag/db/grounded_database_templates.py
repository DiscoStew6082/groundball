"""Deterministic SQL templates for common baseball-history questions."""

import re
from dataclasses import dataclass

from baseball_rag.db.grounded_database_types import AssembledSQL, QuerySpec, TeamIdentity
from baseball_rag.db.stat_registry import StatDefinition, get_stat
from baseball_rag.db.team_history import resolve_team_identity


@dataclass(frozen=True)
class MatchedTemplate:
    """Read model for one deterministic grounded database template match."""

    assembled: AssembledSQL
    source_detail: str
    route_owner: bool = True
    query_spec: QuerySpec | None = None

    @property
    def unsupported_reason(self) -> str | None:
        return self.assembled.unsupported_reason


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
    return int(match.group(1)) if match else None


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

    if "500 club" in q and "home run" not in q and "hr" not in q:
        return MatchedTemplate(
            assembled=_unsupported_sql(
                "The question says 500 club but does not specify home runs or pitching wins.",
                code="ambiguous",
            ),
            source_detail=_template_source_detail(q),
        )

    if "triple crown" in q:
        return MatchedTemplate(_triple_crown_sql(), _template_source_detail(q))

    if re.search(r"\b30\s*30\b", q) or "30 30 club" in q or "thirty thirty" in q:
        return MatchedTemplate(_thirty_thirty_sql(), _template_source_detail(q))

    roster_template = _match_roster_template(q)
    if roster_template is not None:
        return roster_template

    if _looks_like_batting_average_leader(q):
        year = _extract_year(q)
        if year is None and "qualified" not in q:
            return MatchedTemplate(
                _unsupported_sql("Batting average leader questions need a specific year."),
                _template_source_detail(q),
            )
        return MatchedTemplate(
            _qualified_season_avg_sql(year, _extract_min_ab(q, default=100)),
            _template_source_detail(q),
        )

    if (
        ("home run" in q or "homer" in q or re.search(r"\bhrs?\b", q))
        and ("500" in q or "club" in q or "career" in q)
        and not _looks_like_single_season(q)
    ):
        return MatchedTemplate(
            _career_home_run_sql(_extract_threshold(q, default=500)),
            _template_source_detail(q),
        )

    if (
        ("wins" in q or re.search(r"\bw\b", q))
        and ("pitcher" in q or "pitching" in q or "career" in q or "500" in q)
        and not _looks_like_single_season(q)
    ):
        return MatchedTemplate(
            _career_pitching_wins_sql(_extract_explicit_wins_threshold(q)),
            _template_source_detail(q),
        )

    if "era" in q and "career" in q:
        if not _has_era_qualification_guard(q):
            return MatchedTemplate(
                _unsupported_sql(
                    "Career ERA leader questions need an explicit qualification guard."
                ),
                _template_source_detail(q),
            )
        return MatchedTemplate(
            _career_era_sql(_extract_min_ipouts(q, default=3000)),
            _template_source_detail(q),
        )

    if "era" in q and ("lowest" in q or "best" in q or "leader" in q or "leaders" in q):
        year = _extract_year(q)
        if year is None and not _has_era_qualification_guard(q):
            return MatchedTemplate(
                _unsupported_sql(
                    "Season ERA leader questions need a specific year and innings qualification."
                ),
                _template_source_detail(q),
            )
        if not _has_era_qualification_guard(q):
            return MatchedTemplate(
                _unsupported_sql(
                    "Season ERA leader questions need an innings qualification guard."
                ),
                _template_source_detail(q),
            )
        return MatchedTemplate(
            _qualified_season_era_sql(year, _extract_min_ipouts(q, default=300)),
            _template_source_detail(q),
        )

    return None


def _match_roster_template(q: str) -> MatchedTemplate | None:
    if not _looks_like_roster_question(q):
        return None
    year = _extract_year(q)
    if year is None:
        return MatchedTemplate(
            _unsupported_sql("Roster questions need a specific year."),
            _template_source_detail(q),
        )
    nickname = _extract_team_nickname(q)
    if nickname is None:
        return None
    identity = resolve_team_identity(q, team_name_pattern=nickname, year=year)
    return MatchedTemplate(
        _roster_sql(nickname, year, q, identity=identity),
        _template_source_detail(q),
        query_spec=QuerySpec(
            stat_tables=["batting"],
            team_name_pattern=nickname.title(),
            year_value=year,
            team_identity=identity,
        ),
    )


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
    if not matched.route_owner:
        return False
    if competing_stat is None:
        return True

    q = _normalize_question(question)
    if competing_stat == "HR" and _is_plain_career_home_run_leaderboard(q):
        return False
    if competing_stat == "ERA" and _is_plain_season_era_leaderboard(q):
        return False
    return True


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


def _template_source_detail(question: str) -> str:
    """Return portfolio-facing provenance detail for matched templates."""
    q = _normalize_question(question)
    if "triple crown" in q:
        return (
            "Matched local Triple Crown template: batting HR, RBI, and AVG "
            "league leaders by season."
        )
    if re.search(r"\b30\s*30\b", q) or "30 30 club" in q or "thirty thirty" in q:
        return "Matched local 30-30 club template: player seasons with at least 30 HR and 30 SB."
    if _looks_like_batting_average_leader(q):
        return "Matched local qualified season batting average leader template with an AB guard."
    if "era" in q:
        if "career" in q:
            return "Matched local career ERA leaders template with an innings qualification guard."
        return "Matched local qualified season ERA leader template with an innings guard."
    if _looks_like_roster_question(q):
        return "Matched local team-season roster template."
    if "home run" in q or "homer" in q or re.search(r"\bhrs?\b", q):
        return "Matched local 500 HR club template: career batting home run totals."
    if "wins" in q or re.search(r"\bw\b", q):
        return "Matched local career pitching wins leaders template: career pitching W totals."
    return "Matched local deterministic grounded database SQL template."


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
