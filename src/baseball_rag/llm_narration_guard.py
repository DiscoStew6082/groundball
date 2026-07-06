"""Verified LLM narration over DuckDB-backed answers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.stat_mentions import for_narration_verification

_DIGIT_VALUE_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_NUMERIC_TOKEN_RE = re.compile(rf"(?<![A-Za-z0-9])(?:{_DIGIT_VALUE_PATTERN})(?![A-Za-z0-9])")
_NAME_TOKEN_RE = r"[A-Z][A-Za-z.'-]*"
_STAT_UNIT_ALIASES = dict(for_narration_verification().aliases)
_STAT_UNIT_PATTERN = "|".join(
    re.escape(unit) for unit in sorted(_STAT_UNIT_ALIASES, key=len, reverse=True)
)
_GENERIC_NAME_TOKENS = {
    "AB",
    "AL",
    "AVG",
    "BB",
    "DUCKDB",
    "ERA",
    "G",
    "GS",
    "H",
    "HR",
    "K",
    "L",
    "MLB",
    "NL",
    "OPS",
    "PO",
    "R",
    "RBI",
    "SB",
    "SO",
    "SV",
    "W",
    "WHIP",
}
_LOWERCASE_NAME_STOP_WORDS = {
    "a",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "base",
    "baseball",
    "bases",
    "batting",
    "batted",
    "by",
    "count",
    "crown",
    "double",
    "doubles",
    "figure",
    "for",
    "following",
    "from",
    "had",
    "has",
    "her",
    "here",
    "his",
    "hit",
    "home",
    "include",
    "included",
    "includes",
    "in",
    "is",
    "league",
    "led",
    "listed",
    "loss",
    "losses",
    "major",
    "match",
    "matched",
    "matches",
    "mark",
    "number",
    "of",
    "on",
    "player",
    "players",
    "putout",
    "putouts",
    "recorded",
    "result",
    "results",
    "roster",
    "run",
    "runs",
    "save",
    "saves",
    "stolen",
    "stat",
    "stats",
    "strikeout",
    "strikeouts",
    "that",
    "the",
    "their",
    "these",
    "season",
    "seasons",
    "to",
    "total",
    "totals",
    "below",
    "triple",
    "triples",
    "walk",
    "walks",
    "was",
    "were",
    "verified",
    "win",
    "winner",
    "winners",
    "wins",
    "with",
    "won",
    "year",
    "years",
}
_UNIT_VALUE_CONNECTOR_PATTERN = (
    r"(?:(?:[:;=-]\s*)|"
    r"(?:,\s*)?\s*(?:with|at|of|totaling|totaled|had|hit|recorded)\s+|"
    r"(?:\s+(?:total|mark|count|number|figure))?\s+(?:was|were|is|are)\s+)"
)
_DIGIT_STAT_CLAIM_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<value>{_DIGIT_VALUE_PATTERN})(?:\s*[-:;=]\s*|\s*)"
    rf"(?P<unit>{_STAT_UNIT_PATTERN})\b",
    re.IGNORECASE,
)
_UNIT_DIGIT_STAT_CLAIM_RE = re.compile(
    rf"\b(?P<unit>{_STAT_UNIT_PATTERN})\b"
    rf"{_UNIT_VALUE_CONNECTOR_PATTERN}"
    rf"(?P<value>{_DIGIT_VALUE_PATTERN})",
    re.IGNORECASE,
)
_SPELLED_NUMBER_PATTERN = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|"
    r"thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand)"
    r"(?:[-\s]+(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand))*"
)
_SPELLED_STAT_CLAIM_RE = re.compile(
    rf"\b{_SPELLED_NUMBER_PATTERN}\s+(?:{_STAT_UNIT_PATTERN})\b",
    re.IGNORECASE,
)
_SPELLED_UNIT_STAT_CLAIM_RE = re.compile(
    rf"\b(?:{_STAT_UNIT_PATTERN})\b"
    rf"{_UNIT_VALUE_CONNECTOR_PATTERN}"
    rf"{_SPELLED_NUMBER_PATTERN}\b",
    re.IGNORECASE,
)
_UNVERIFIED_ROLE_CLAIM_RE = re.compile(
    r"\b(?:(?:is|are|was|were|became|played\s+as|served\s+as)\s+"
    r"(?:an?\s+)?"
    r"(?:pitcher|catcher|infielder|outfielder|"
    r"first\s+baseman|second\s+baseman|third\s+baseman|shortstop|"
    r"manager|coach|rookie|hall\s+of\s+famer)|"
    r"(?:pitched|managed|coached|caught|injured|traded|signed|released|"
    r"drafted|suspended|retired|born))\b",
    re.IGNORECASE,
)
_BE_PREDICATE_RE = re.compile(
    r"\b(?:is|are|was|were|became)\s+(?:an?\s+|the\s+)?(?P<token>[A-Za-z][A-Za-z-]*)",
    re.IGNORECASE,
)
_ALLOWED_BE_PREDICATE_TOKENS = {
    "first",
    "following",
    "included",
    "leader",
    "leaders",
    "league",
    "listed",
    "matched",
    "mlb",
    "one",
    "only",
    "top",
    "triple",
    "winner",
    "winners",
}
_TOP_COUNT_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


@dataclass(frozen=True)
class VerifiedEvidenceClaim:
    """A verified fact bundle associated with one result row."""

    name_variants: frozenset[str]
    claims: frozenset[tuple[str, str]]
    numbers: frozenset[str]
    years: frozenset[str]
    rank: int


@dataclass(frozen=True)
class VerifiedEvidence:
    """Read model used to verify LLM narration claims."""

    claims: frozenset[tuple[str, str]]
    numbers: frozenset[str]
    name_claims: tuple[VerifiedEvidenceClaim, ...]


@dataclass(frozen=True)
class LLMNarrationResult:
    """Verified narration outcome surfaced to callers."""

    answer: str
    status: str
    message: str | None = None


def apply_llm_flavored_narration(question: str, result: StructuredAnswer) -> StructuredAnswer:
    """Apply verified LLM narration to DuckDB-backed answer results."""
    if result.unsupported:
        result.metadata["llm_narration"] = {"status": "skipped", "reason": "unsupported"}
        return result
    if result.intent not in {"stat_query", "grounded_database_question"}:
        result.metadata["llm_narration"] = {"status": "skipped", "reason": "unsupported_intent"}
        return result
    source = _primary_duckdb_source(result)
    if source is None:
        result.metadata["llm_narration"] = {"status": "skipped", "reason": "missing_duckdb_source"}
        return result
    prompt_question = str(result.metadata.get("context_question") or question)
    narration = _llm_flavored_grounded_database_answer(
        question=prompt_question,
        formatted_answer=result.answer,
        source=source,
    )
    result.answer = narration.answer
    result.metadata["llm_narration"] = {
        "status": narration.status,
        **({"message": narration.message} if narration.message else {}),
    }
    return result


def _primary_duckdb_source(result: StructuredAnswer) -> SourceRecord | None:
    for source in result.sources:
        if source.type == "duckdb":
            return source
    return None


def _llm_flavored_grounded_database_answer(
    *,
    question: str,
    formatted_answer: str,
    source: SourceRecord,
) -> LLMNarrationResult:
    from baseball_rag.generation.llm import LLMError, make_request

    evidence = _verified_evidence(formatted_answer=formatted_answer, source=source)
    try:
        response = make_request(
            _grounded_database_flavor_prompt(
                question=question,
                formatted_answer=formatted_answer,
                source=source,
            ),
            max_tokens=700,
            temperature=0.2,
        )
    except (ConnectionError, TimeoutError, LLMError):
        fallback = _verified_stat_leaderboard_prose_fallback(
            question=question,
            formatted_answer=formatted_answer,
            source=source,
        )
        message = "Gemma prose is unavailable; showing verified DuckDB answer."
        return LLMNarrationResult(
            answer=fallback or formatted_answer,
            status="unavailable",
            message=message,
        )
    answer = response.content.strip()
    if _uses_only_verified_numbers(answer, evidence=evidence):
        return LLMNarrationResult(answer=answer, status="accepted")

    try:
        repaired_response = make_request(
            _grounded_database_repair_prompt(
                question=question,
                formatted_answer=formatted_answer,
                source=source,
                rejected_answer=answer,
            ),
            max_tokens=700,
            temperature=0.1,
        )
    except (ConnectionError, TimeoutError, LLMError):
        repaired_answer = ""
    else:
        repaired_answer = repaired_response.content.strip()

    if repaired_answer and _repaired_answer_is_grounded(
        repaired_answer,
        evidence=evidence,
        source=source,
    ):
        return LLMNarrationResult(answer=repaired_answer, status="accepted_after_repair")

    fallback = _verified_stat_leaderboard_prose_fallback(
        question=question,
        formatted_answer=formatted_answer,
        source=source,
    )
    message = "Gemma prose did not pass verification; showing verified DuckDB answer."
    return LLMNarrationResult(
        answer=fallback or formatted_answer,
        status="verification_failed",
        message=message,
    )


def _verified_stat_leaderboard_prose_fallback(
    *,
    question: str,
    formatted_answer: str,
    source: SourceRecord,
) -> str | None:
    top_count = _requested_top_count(question)
    if top_count != 5:
        return None
    source_stat = _source_stat(source)
    if source_stat is None or "leaderboard" not in _normalize_claim_text(source.label):
        return None

    rows = _verified_leaderboard_rows(source.rows, source_stat=source_stat, limit=top_count)
    if len(rows) < top_count:
        return None

    leader_name, leader_value = rows[0]
    year_text = _formatted_answer_year_text(formatted_answer)
    prefix = f"In {year_text}, " if year_text else ""
    answer = (
        f"{prefix}{leader_name} led the {source_stat} leaderboard with "
        f"{leader_value} {source_stat}."
    )
    if len(rows) == 1:
        return answer

    remaining = _format_series([f"{name} ({value})" for name, value in rows[1:]])
    count_label = _top_count_label(top_count)
    return f"{answer} The rest of the top {count_label} were {remaining}."


def _requested_top_count(question: str) -> int | None:
    match = re.search(
        r"\btop\s+(?P<count>\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        question,
        re.IGNORECASE,
    )
    if match is None:
        return None
    raw_count = match.group("count").lower()
    if raw_count.isdigit():
        return int(raw_count)
    return _TOP_COUNT_WORDS.get(raw_count)


def _verified_leaderboard_rows(
    rows: list[Any],
    *,
    source_stat: str,
    limit: int,
) -> list[tuple[str, str]]:
    verified_rows = []
    for row in rows[:limit]:
        if not isinstance(row, dict):
            return []
        raw_name = row.get("name")
        raw_value = row.get("stat_value")
        if not isinstance(raw_name, str) or raw_value is None:
            return []
        normalized_value = _normalize_numeric_token(str(raw_value))
        if normalized_value is None:
            return []
        row_claims = _row_stat_claims(row, source_stat=source_stat)
        if (normalized_value, source_stat) not in row_claims:
            return []
        verified_rows.append((_display_player_name(raw_name), _display_stat_value(raw_value)))
    return verified_rows


def _display_player_name(name: str) -> str:
    if "," not in name:
        return name.strip()
    last, first = [part.strip() for part in name.split(",", 1)]
    if not first or not last:
        return name.strip()
    return f"{first} {last}"


def _display_stat_value(value: Any) -> str:
    normalized = _normalize_numeric_token(str(value))
    if normalized is None:
        return str(value)
    return normalized


def _formatted_answer_year_text(formatted_answer: str) -> str | None:
    match = re.search(r"\((?P<start>\d{4})(?:-(?P<end>\d{4}))?\)", formatted_answer)
    if match is None:
        return None
    start = match.group("start")
    end = match.group("end")
    if end is None or end == start:
        return start
    return f"{start}-{end}"


def _top_count_label(count: int) -> str:
    for word, value in _TOP_COUNT_WORDS.items():
        if value == count:
            return word
    return str(count)


def _format_series(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _grounded_database_flavor_prompt(
    *,
    question: str,
    formatted_answer: str,
    source: SourceRecord,
) -> tuple[str, str]:
    system_prompt = (
        "Answer the baseball question using only the verified DuckDB stats provided. "
        "Do not add outside numbers. If you mention a number, it must come from the "
        "verified stats."
    )
    context = {
        "question": question,
        "formatted_stats": formatted_answer,
        "duckdb_source": {
            "label": source.label,
            "detail": source.detail,
            "sql": source.sql,
            "columns": source.columns,
            "rows": source.rows,
        },
    }
    user_prompt = (
        "Use this grounded database result to answer in natural language:\n"
        f"{json.dumps(context, indent=2, default=str)}"
    )
    return system_prompt, user_prompt


def _grounded_database_repair_prompt(
    *,
    question: str,
    formatted_answer: str,
    source: SourceRecord,
    rejected_answer: str,
) -> tuple[str, str]:
    system_prompt = (
        "Rewrite the baseball answer in natural language using only the verified DuckDB "
        "stats provided. Treat the DuckDB rows as the only source of truth. Do not mention "
        "verification, failures, or rejected drafts. Do not add outside names, years, or "
        "numbers."
    )
    context = {
        "question": question,
        "rejected_answer_to_rewrite": rejected_answer,
        "formatted_stats": formatted_answer,
        "duckdb_source": {
            "label": source.label,
            "detail": source.detail,
            "sql": source.sql,
            "columns": source.columns,
            "rows": source.rows,
        },
    }
    user_prompt = (
        "Rewrite the rejected answer so every claim is supported by this verified database "
        "result:\n"
        f"{json.dumps(context, indent=2, default=str)}"
    )
    return system_prompt, user_prompt


def _uses_only_verified_numbers(
    answer: str,
    *,
    evidence: VerifiedEvidence,
) -> bool:
    if _mentions_unverified_predicate(answer, evidence=evidence):
        return False
    if _SPELLED_STAT_CLAIM_RE.search(answer) or _SPELLED_UNIT_STAT_CLAIM_RE.search(answer):
        return False
    answer_numbers = _numeric_tokens(answer)
    if not answer_numbers:
        return _uses_verified_name_stat_claims(answer, evidence=evidence)
    answer_claims = _digit_stat_claims(answer)
    return (
        answer_numbers <= evidence.numbers
        and answer_claims <= evidence.claims
        and _uses_verified_name_stat_claims(answer, evidence=evidence)
    )


def _mentions_unverified_predicate(answer: str, *, evidence: VerifiedEvidence) -> bool:
    if _UNVERIFIED_ROLE_CLAIM_RE.search(answer):
        return True

    known_name_starts = {
        variant.split()[0]
        for item in evidence.name_claims
        for variant in item.name_variants
        if variant.split()
    }
    for match in _BE_PREDICATE_RE.finditer(answer):
        token = _normalize_claim_text(match.group("token"))
        if not token or token in _ALLOWED_BE_PREDICATE_TOKENS or token in known_name_starts:
            continue
        return True
    return False


def _repaired_answer_is_grounded(
    answer: str,
    *,
    evidence: VerifiedEvidence,
    source: SourceRecord,
) -> bool:
    if not _uses_only_verified_numbers(answer, evidence=evidence):
        return False
    if _digit_stat_claims(answer):
        return True

    answer_years = _year_numbers(_numeric_tokens(answer))
    source_context = _normalize_claim_text(f"{source.label} {source.detail or ''}")
    normalized_answer = _normalize_claim_text(answer)
    if answer_years and "triple crown" in source_context and "triple crown" in normalized_answer:
        return True

    if not evidence.numbers and any(
        token in normalized_answer
        for token in ("listed", "roster", "matched", "played", "included")
    ):
        return True

    return False


def _numeric_tokens(text: str) -> set[str]:
    return {
        normalized
        for match in _NUMERIC_TOKEN_RE.finditer(text)
        if (normalized := _normalize_numeric_token(match.group(0))) is not None
    }


def _normalize_numeric_token(value: str) -> str | None:
    try:
        number = Decimal(value.replace(",", ""))
    except InvalidOperation:
        return None
    normalized = number.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f").lstrip("0") or "0"


def _digit_stat_claims(text: str) -> set[tuple[str, str]]:
    claims: set[tuple[str, str]] = set()
    for pattern in (_DIGIT_STAT_CLAIM_RE, _UNIT_DIGIT_STAT_CLAIM_RE):
        for match in pattern.finditer(text):
            value = _normalize_numeric_token(match.group("value"))
            stat = _normalize_stat_unit(match.group("unit"))
            if value is not None and stat is not None:
                claims.add((value, stat))
    return claims


def _normalize_stat_unit(value: str) -> str | None:
    return _STAT_UNIT_ALIASES.get(value.lower().strip())


def _uses_verified_name_stat_claims(
    answer: str,
    *,
    evidence: VerifiedEvidence,
) -> bool:
    if not evidence.name_claims:
        return True
    for segment in _stat_claim_segments(answer):
        segment_claims = _digit_stat_claims(segment)
        segment_numbers = _numeric_tokens(segment)
        segment_row_numbers = _non_year_numbers(segment_numbers)
        segment_years = _year_numbers(segment_numbers)
        mentions_name_like_phrase = _mentions_name_like_phrase(segment)
        if (
            not segment_claims
            and not segment_row_numbers
            and not segment_years
            and not mentions_name_like_phrase
        ):
            continue
        normalized_segment = _normalize_claim_text(segment)
        matched_items = [
            item
            for item in evidence.name_claims
            if any(variant in normalized_segment for variant in item.name_variants)
        ]
        if matched_items:
            if (
                _mentions_leadership_claim(segment)
                and not (segment_claims or segment_row_numbers)
                and (len(matched_items) != 1 or matched_items[0].rank != 1)
            ):
                return False
            if _mentions_unmatched_name(
                segment,
                matched_items,
                scan_lowercase_names=True,
            ):
                return False
            validating_items = [
                item
                for item in matched_items
                if segment_claims <= item.claims and segment_row_numbers <= item.numbers
            ]
            requires_single_name = bool(segment_claims or segment_row_numbers)
            if (
                validating_items
                and (not requires_single_name or _matched_items_share_name(matched_items))
                and _years_match_segment(
                    segment_years,
                    validating_items,
                    require_single_item=requires_single_name,
                )
            ):
                continue
            return False
        if mentions_name_like_phrase:
            return False
    return True


def _verified_evidence(
    *,
    formatted_answer: str,
    source: SourceRecord,
) -> VerifiedEvidence:
    lines = formatted_answer.splitlines()
    source_stat = _source_stat(source)
    evidence = []
    all_claims = _digit_stat_claims(formatted_answer)
    all_numbers = _numeric_tokens(formatted_answer)
    all_numbers |= _numeric_tokens(json.dumps(source.columns, default=str))
    for rank, row in enumerate(source.rows, 1):
        if not isinstance(row, dict):
            continue
        row_claims = _row_stat_claims(row, source_stat=source_stat)
        row_numbers = _non_year_numbers(_row_numbers(row))
        row_years = _row_years(row)
        all_claims |= row_claims
        all_numbers |= row_numbers
        all_numbers |= row_years
        raw_name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        variants = _name_variants(raw_name)
        claims = set(row_claims)

        def line_mentions_name(line: str) -> bool:
            normalized_line = _normalize_claim_text(line)
            return any(variant in normalized_line for variant in variants)

        normalized_lines = [line for line in lines if line_mentions_name(line)]
        for line in normalized_lines:
            claims |= _digit_stat_claims(line)
        numbers = _row_numbers(row)
        for line in normalized_lines:
            numbers |= _numeric_tokens(line)
        years = _row_years(row)
        for line in normalized_lines:
            years |= _year_numbers(_numeric_tokens(line))
        if variants:
            all_claims |= claims
            all_numbers |= years
            evidence.append(
                VerifiedEvidenceClaim(
                    name_variants=frozenset(variants),
                    claims=frozenset(claims),
                    numbers=frozenset(row_numbers),
                    years=frozenset(years),
                    rank=rank,
                )
            )
    return VerifiedEvidence(
        claims=frozenset(all_claims),
        numbers=frozenset(all_numbers),
        name_claims=tuple(evidence),
    )


def _row_stat_claims(
    row: dict[str, Any],
    *,
    source_stat: str | None,
) -> set[tuple[str, str]]:
    claims: set[tuple[str, str]] = set()
    for key, value in row.items():
        stat = _normalize_stat_unit(key)
        if stat is None:
            continue
        normalized = _normalize_numeric_token(str(value))
        if normalized is not None:
            claims.add((normalized, stat))
    if source_stat is not None and "stat_value" in row:
        normalized = _normalize_numeric_token(str(row["stat_value"]))
        if normalized is not None:
            claims.add((normalized, source_stat))
    return claims


def _source_stat(source: SourceRecord) -> str | None:
    label_stat = _unique_source_stat(source.label)
    if label_stat is not None:
        return label_stat
    return _unique_source_stat(source.detail or "")


def _unique_source_stat(text: str) -> str | None:
    normalized_text = _normalize_claim_text(text)
    aliases = sorted(_STAT_UNIT_ALIASES.items(), key=lambda item: len(item[0]), reverse=True)
    stats: set[str] = set()
    for alias, stat in aliases:
        normalized_alias = _normalize_claim_text(alias)
        if re.search(rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])", normalized_text):
            stats.add(stat)
    return next(iter(stats)) if len(stats) == 1 else None


def _row_numbers(row: dict[str, Any]) -> set[str]:
    numbers: set[str] = set()
    for value in row.values():
        if isinstance(value, int | float | str):
            normalized = _normalize_numeric_token(str(value))
            if normalized is not None:
                numbers.add(normalized)
    return numbers


def _row_years(row: dict[str, Any]) -> set[str]:
    years: set[str] = set()
    for key, value in row.items():
        if str(key).lower() not in {"year", "yearid"}:
            continue
        normalized = _normalize_numeric_token(str(value))
        if normalized is not None and _looks_like_year_number(normalized):
            years.add(normalized)
    return years


def _matched_items_share_name(items: list[VerifiedEvidenceClaim]) -> bool:
    if not items:
        return False
    shared = set(items[0].name_variants)
    for item in items[1:]:
        shared &= item.name_variants
    return bool(shared)


def _non_year_numbers(numbers: set[str]) -> set[str]:
    return {number for number in numbers if not _looks_like_year_number(number)}


def _year_numbers(numbers: set[str]) -> set[str]:
    return {number for number in numbers if _looks_like_year_number(number)}


def _years_match_segment(
    segment_years: set[str],
    items: list[VerifiedEvidenceClaim],
    *,
    require_single_item: bool,
) -> bool:
    if not segment_years:
        return True
    items_with_years = [item for item in items if item.years]
    if not items_with_years:
        return True
    if require_single_item:
        return any(segment_years <= item.years for item in items_with_years)
    matched_years = {year for item in items_with_years for year in item.years}
    return segment_years <= matched_years


def _looks_like_year_number(number: str) -> bool:
    try:
        value = int(number)
    except ValueError:
        return False
    return 1800 <= value <= 2099


def _name_variants(name: str) -> set[str]:
    normalized = _normalize_claim_text(name)
    variants = {normalized} if normalized else set()
    if "," in name:
        last, first = [part.strip() for part in name.split(",", 1)]
        display = _normalize_claim_text(f"{first} {last}")
        if display:
            variants.add(display)
    return variants


def _stat_claim_segments(text: str) -> list[str]:
    return [
        segment
        for segment in re.split(r"(?<=[.!?])\s+|;\s*|\n+|\s+and\s+(?=[A-Z])", text)
        if segment.strip()
    ]


def _normalize_claim_text(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", text.lower()).strip()


def _mentions_name_like_phrase(text: str) -> bool:
    generic_words = _GENERIC_NAME_TOKENS
    generic_lower = {token.lower() for token in generic_words}
    for match in re.finditer(rf"\b{_NAME_TOKEN_RE}\s+{_NAME_TOKEN_RE}\b", text):
        if not _is_generic_name_phrase(
            _normalize_claim_text(match.group(0)),
            generic_words=generic_lower,
        ):
            return True
    if any(
        token not in generic_words and token.lower() not in _LOWERCASE_NAME_STOP_WORDS
        for token in re.findall(rf"\b{_NAME_TOKEN_RE}\b", text)
    ):
        return True
    return _contains_lowercase_name_phrase(
        _normalize_claim_text(text),
        generic_words=generic_lower,
    )


def _mentions_leadership_claim(text: str) -> bool:
    return bool(re.search(r"\b(?:led|leader|leaders)\b", text, re.IGNORECASE))


def _mentions_unmatched_name(
    text: str,
    matched_items: list[VerifiedEvidenceClaim],
    *,
    scan_lowercase_names: bool,
) -> bool:
    known_variants = {variant for item in matched_items for variant in item.name_variants}
    generic_words = {token.lower() for token in _GENERIC_NAME_TOKENS}
    for match in re.finditer(rf"\b{_NAME_TOKEN_RE}\s+{_NAME_TOKEN_RE}\b", text):
        normalized = _normalize_claim_text(match.group(0))
        if normalized not in known_variants and not _is_generic_name_phrase(
            normalized,
            generic_words=generic_words,
        ):
            return True

    normalized_text = f" {_normalize_claim_text(text)} "
    for variant in sorted(known_variants, key=len, reverse=True):
        normalized_text = normalized_text.replace(f" {variant} ", " ")

    for token in re.findall(rf"\b{_NAME_TOKEN_RE}\b", text):
        normalized = _normalize_claim_text(token)
        if (
            normalized
            and normalized not in generic_words
            and normalized not in _LOWERCASE_NAME_STOP_WORDS
            and f" {normalized} " in normalized_text
        ):
            return True
    return scan_lowercase_names and _contains_lowercase_name_phrase(
        normalized_text,
        generic_words=generic_words,
    )


def _contains_lowercase_name_phrase(text: str, *, generic_words: set[str]) -> bool:
    tokens = re.findall(r"\b[a-z][a-z.'-]*\b", text)
    for first, second in zip(tokens, tokens[1:]):
        if _could_be_name_token(first, generic_words) and _could_be_name_token(
            second,
            generic_words,
        ):
            return True
    return False


def _is_generic_name_phrase(text: str, *, generic_words: set[str]) -> bool:
    tokens = re.findall(r"\b[a-z][a-z.'-]*\b", text)
    return bool(tokens) and all(
        token in generic_words or token in _LOWERCASE_NAME_STOP_WORDS for token in tokens
    )


def _could_be_name_token(token: str, generic_words: set[str]) -> bool:
    return token not in generic_words and token not in _LOWERCASE_NAME_STOP_WORDS
