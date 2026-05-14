"""Deterministic SQL templates for common baseball-history questions."""

import re
from dataclasses import dataclass

from baseball_rag.db.freeform_types import AssembledSQL


@dataclass(frozen=True)
class MatchedTemplate:
    """Read model for one deterministic freeform template match."""

    assembled: AssembledSQL
    source_detail: str
    route_owner: bool = True

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
        if year is None:
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


def _detect_template(question: str) -> AssembledSQL | None:
    """Return deterministic SQL for high-value freeform baseball-history patterns."""
    matched = match_template(question)
    return matched.assembled if matched is not None else None


def can_plan_deterministically(question: str) -> bool:
    """Return whether a question is owned by a deterministic freeform template."""
    return match_template(question) is not None


def should_route_deterministic_freeform(
    question: str,
    *,
    competing_stat: str | None = None,
) -> bool:
    """Return whether deterministic freeform should win routing precedence."""
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
    if "era" in q:
        if "career" in q:
            return "Matched local career ERA leaders template with an innings qualification guard."
        return "Matched local qualified season ERA leader template with an innings guard."
    if "home run" in q or "homer" in q or re.search(r"\bhrs?\b", q):
        return "Matched local 500 HR club template: career batting home run totals."
    if "wins" in q or re.search(r"\bw\b", q):
        return "Matched local career pitching wins leaders template: career pitching W totals."
    return "Matched local deterministic freeform SQL template."


def _has_era_qualification_guard(q: str) -> bool:
    return "qualified" in q or "qualifying" in q or "enough innings" in q or " innings" in q


def _looks_like_single_season(q: str) -> bool:
    return _extract_year(q) is not None and "career" not in q and "club" not in q


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
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            ROUND(27.0 * SUM(pi.ER) / NULLIF(SUM(pi.IPouts), 0), 2) AS career_ERA,
            SUM(pi.IPouts) AS IPouts
        FROM pitching pi
        JOIN people p ON p.playerID = pi.playerID
        GROUP BY pi.playerID, p.nameFirst, p.nameLast
        HAVING SUM(pi.IPouts) >= ?
        ORDER BY career_ERA ASC, IPouts DESC, p.nameLast, p.nameFirst
        """,
        [min_ipouts],
    )


def _qualified_season_era_sql(year: int, min_ipouts: int) -> AssembledSQL:
    return AssembledSQL(
        """
        SELECT
            p.nameFirst,
            p.nameLast,
            pi.yearID,
            pi.lgID,
            pi.ERA,
            pi.IPouts
        FROM pitching pi
        JOIN people p ON p.playerID = pi.playerID
        WHERE pi.yearID = ?
            AND pi.IPouts >= ?
            AND pi.ERA IS NOT NULL
            AND pi.ERA = (
                SELECT MIN(p2.ERA)
                FROM pitching p2
                WHERE p2.yearID = pi.yearID
                    AND p2.lgID = pi.lgID
                    AND p2.IPouts >= ?
                    AND p2.ERA IS NOT NULL
            )
        ORDER BY pi.yearID, pi.lgID, pi.ERA, p.nameLast, p.nameFirst
        """,
        [year, min_ipouts, min_ipouts],
    )
