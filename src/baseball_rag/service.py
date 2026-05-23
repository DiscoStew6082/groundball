"""Shared answer service used by CLI and API."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from baseball_rag import biography_contract, player_biography
from baseball_rag.answer_mode import AnswerMode, validate_answer_mode
from baseball_rag.conversation import resolve_followup
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.general_explanation import GeneralExplanationPolicy
from baseball_rag.outcomes import unsupported_outcome
from baseball_rag.player_biography import (
    PlayerBiographyCaseAnswerer,
    duckdb_source,
    verify_player_stat_claims_consensus,
)
from baseball_rag.provenance import (
    ReviewReason,
    SourceRecord,
    StructuredAnswer,
    UnsupportedReason,
    compact_data_manifest,
)
from baseball_rag.request_dispatch import AnswerHandlers, RequestAnswerDispatcher
from baseball_rag.routing import (
    GeneralExplanationCase,
    GroundedDatabaseQuestionCase,
    PlayerBiographyCase,
    route,
)
from baseball_rag.stat_query import answer_stat_query

logger = logging.getLogger(__name__)
_DIGIT_VALUE_PATTERN = r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+"
_NUMERIC_TOKEN_RE = re.compile(rf"(?<![A-Za-z0-9])(?:{_DIGIT_VALUE_PATTERN})(?![A-Za-z0-9])")
_NAME_TOKEN_RE = r"[A-Z][A-Za-z.'-]*"
_STAT_UNIT_ALIASES = {
    "2b": "2B",
    "3b": "3B",
    "ab": "AB",
    "at bat": "AB",
    "at bats": "AB",
    "avg": "AVG",
    "base on balls": "BB",
    "bases on balls": "BB",
    "bat avg": "AVG",
    "batting average": "AVG",
    "bb": "BB",
    "double": "2B",
    "doubles": "2B",
    "earned run average": "ERA",
    "era": "ERA",
    "g": "G",
    "game": "G",
    "game started": "GS",
    "games": "G",
    "games started": "GS",
    "gs": "GS",
    "h": "H",
    "hit": "H",
    "hits": "H",
    "home run": "HR",
    "home runs": "HR",
    "homer": "HR",
    "homers": "HR",
    "hr": "HR",
    "hrs": "HR",
    "k": "SO",
    "ks": "SO",
    "l": "L",
    "loss": "L",
    "losses": "L",
    "on-base plus slugging": "OPS",
    "ops": "OPS",
    "po": "PO",
    "putout": "PO",
    "putouts": "PO",
    "r": "R",
    "rbi": "RBI",
    "rbis": "RBI",
    "run": "R",
    "run batted in": "RBI",
    "runs": "R",
    "runs batted in": "RBI",
    "save": "SV",
    "saves": "SV",
    "sb": "SB",
    "so": "SO",
    "start": "GS",
    "starts": "GS",
    "stolen base": "SB",
    "stolen bases": "SB",
    "strike out": "SO",
    "strike outs": "SO",
    "strikeout": "SO",
    "strikeouts": "SO",
    "sv": "SV",
    "triple": "3B",
    "triples": "3B",
    "w": "W",
    "walk": "BB",
    "walks": "BB",
    "whip": "WHIP",
    "win": "W",
    "wins": "W",
}
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
    "from",
    "had",
    "has",
    "her",
    "his",
    "hit",
    "home",
    "in",
    "is",
    "league",
    "led",
    "loss",
    "losses",
    "major",
    "mark",
    "number",
    "of",
    "on",
    "player",
    "players",
    "putout",
    "putouts",
    "recorded",
    "run",
    "runs",
    "save",
    "saves",
    "stolen",
    "stat",
    "stats",
    "strikeout",
    "strikeouts",
    "the",
    "their",
    "to",
    "total",
    "totals",
    "triple",
    "triples",
    "walk",
    "walks",
    "was",
    "were",
    "verified",
    "win",
    "wins",
    "with",
    "won",
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


@dataclass(frozen=True)
class _NameClaimEvidence:
    name_variants: frozenset[str]
    claims: frozenset[tuple[str, str]]
    numbers: frozenset[str]
    years: frozenset[str]


def answer(
    question: str,
    *,
    conversation: list[dict[str, Any]] | None = None,
    answer_mode: str = "stats_only",
) -> StructuredAnswer:
    """Answer a question with explicit provenance metadata."""
    validated_answer_mode: AnswerMode = validate_answer_mode(answer_mode)
    dispatcher = RequestAnswerDispatcher(
        resolve_followup=resolve_followup,
        route_question=route,
        handlers=AnswerHandlers(
            stat_query=answer_stat_query,
            player_biography=_answer_player_biography,
            grounded_database_question=_answer_grounded_database_question,
            general_explanation=_answer_general,
        ),
    )
    result = dispatcher.answer(question, conversation=conversation)
    if validated_answer_mode == "llm_flavored":
        _apply_llm_flavor(question, result)
    result.metadata["answer_mode"] = validated_answer_mode
    return result


def render_text(result: StructuredAnswer) -> str:
    """Render a structured answer for terminal/chat use."""
    lines = [result.answer]
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _answer_player_biography(question: str, decision: PlayerBiographyCase) -> StructuredAnswer:
    from baseball_rag.generation.llm import make_request

    return PlayerBiographyCaseAnswerer(
        conn_factory=get_duckdb,
        make_request=make_request,
        verify_claims_consensus=verify_player_stat_claims_consensus,
        extract_claims=player_biography.extract_supplied_stat_claims,
        request_biography=biography_contract.request_biography_json,
    ).answer(question, decision)


def _duckdb_source(
    label: str,
    *,
    tables: list[str],
    rows: list[dict[str, Any]] | None = None,
    sql: str | None = None,
    detail: str | None = None,
    data_manifest: dict[str, Any] | None = None,
) -> SourceRecord:
    return duckdb_source(
        label,
        tables=tables,
        rows=rows,
        sql=sql,
        detail=detail,
        data_manifest=data_manifest,
    )


def _answer_grounded_database_question(
    _question: str,
    decision: GroundedDatabaseQuestionCase,
) -> StructuredAnswer:
    from baseball_rag.db.grounded_database_runtime import format_result, query
    from baseball_rag.generation.llm import make_request

    conn = get_duckdb()
    query_result = query(
        decision.raw_question,
        conn,
        year=_grounded_database_single_season_year(decision),
        request_fn=make_request,
    )
    source = SourceRecord(
        type="duckdb",
        label=query_result.source_label,
        detail=query_result.source_detail,
        sql=query_result.sql,
        columns=query_result.columns,
        rows=_rows_to_dicts(query_result.columns, query_result.rows[:100]),
        data_manifest=compact_data_manifest(),
    )

    if query_result.row_count == 0:
        reason = _grounded_database_unsupported_reason(query_result)
        review_reason: ReviewReason = "ambiguous" if reason == "ambiguous" else "unsupported"
        return unsupported_outcome(
            answer=(
                f"No results found for '{decision.raw_question}'.\n"
                "Try rephrasing with a specific team, player, stat, or year."
            ),
            intent=decision.intent,
            sources=[source],
            reason=reason,
            review_reason=review_reason,
        )

    warnings = []
    if query_result.truncated:
        warnings.append("Results were truncated at the configured row limit.")
    formatted_answer = format_result(query_result, decision.raw_question)
    return StructuredAnswer(
        answer=formatted_answer,
        intent=decision.intent,
        sources=[source],
        warnings=warnings,
    )


def _grounded_database_single_season_year(
    decision: GroundedDatabaseQuestionCase,
) -> int | None:
    if decision.time_period is None:
        return None

    from baseball_rag.query_scope import QueryScope, resolve_query_scope

    scope = resolve_query_scope(
        decision.time_period,
        raw_question=decision.raw_question,
        stat="grounded database question",
        intent=decision.intent,
        validate_coverage=False,
    )
    if isinstance(scope, QueryScope) and scope.is_single_season:
        return scope.start_year
    return None


def _answer_general(question: str, decision: GeneralExplanationCase) -> StructuredAnswer:
    from baseball_rag.generation.llm import make_request

    return GeneralExplanationPolicy(make_request=make_request).answer(decision)


def _apply_llm_flavor(question: str, result: StructuredAnswer) -> None:
    if result.unsupported:
        return
    if result.intent not in {"stat_query", "grounded_database_question"}:
        return
    source = _primary_duckdb_source(result)
    if source is None:
        return
    prompt_question = str(result.metadata.get("context_question") or question)
    result.answer = _llm_flavored_grounded_database_answer(
        question=prompt_question,
        formatted_answer=result.answer,
        source=source,
    )


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
) -> str:
    from baseball_rag.generation.llm import LLMError, make_request

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
        return (
            f"{formatted_answer}\n\n"
            "Note: LLM unavailable, so this response is the verified DuckDB stats only."
        )
    answer = response.content.strip()
    if not _uses_only_verified_numbers(answer, formatted_answer=formatted_answer, source=source):
        return (
            f"{formatted_answer}\n\n"
            "Note: LLM-flavored text included unverified numbers, so this response is the "
            "verified DuckDB stats only."
        )
    return answer


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


def _uses_only_verified_numbers(
    answer: str,
    *,
    formatted_answer: str,
    source: SourceRecord,
) -> bool:
    if _SPELLED_STAT_CLAIM_RE.search(answer) or _SPELLED_UNIT_STAT_CLAIM_RE.search(answer):
        return False
    answer_numbers = _numeric_tokens(answer)
    if not answer_numbers:
        return True
    verified_context = " ".join(
        [
            formatted_answer,
            json.dumps(source.rows, default=str),
            json.dumps(source.columns, default=str),
        ]
    )
    answer_claims = _digit_stat_claims(answer)
    verified_claims = _digit_stat_claims(verified_context)
    return (
        answer_numbers <= _numeric_tokens(verified_context)
        and answer_claims <= verified_claims
        and _uses_verified_name_stat_claims(
            answer,
            formatted_answer=formatted_answer,
            source=source,
        )
    )


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
    formatted_answer: str,
    source: SourceRecord,
) -> bool:
    evidence = _name_claim_evidence(formatted_answer=formatted_answer, source=source)
    if not evidence:
        return True
    for segment in _stat_claim_segments(answer):
        segment_claims = _digit_stat_claims(segment)
        segment_numbers = _numeric_tokens(segment)
        segment_row_numbers = _non_year_numbers(segment_numbers)
        segment_years = _year_numbers(segment_numbers)
        if not segment_claims and not segment_row_numbers and not segment_years:
            continue
        normalized_segment = _normalize_claim_text(segment)
        matched_items = [
            item
            for item in evidence
            if any(variant in normalized_segment for variant in item.name_variants)
        ]
        if matched_items:
            if _mentions_unmatched_name(segment, matched_items):
                return False
            validating_items = [
                item
                for item in matched_items
                if segment_claims <= item.claims and segment_row_numbers <= item.numbers
            ]
            if (
                validating_items
                and _matched_items_share_name(matched_items)
                and _years_match_segment(
                    segment_years,
                    validating_items,
                    require_single_item=bool(segment_claims or segment_row_numbers),
                )
            ):
                continue
            return False
        if (segment_claims or segment_row_numbers or segment_years) and _mentions_name_like_phrase(
            segment
        ):
            return False
    return True


def _name_claim_evidence(
    *,
    formatted_answer: str,
    source: SourceRecord,
) -> list[_NameClaimEvidence]:
    lines = formatted_answer.splitlines()
    evidence = []
    for row in source.rows:
        raw_name = row.get("name") if isinstance(row, dict) else None
        if not isinstance(raw_name, str) or not raw_name.strip():
            continue
        variants = _name_variants(raw_name)
        claims = _row_stat_claims(row)

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
        if variants and claims:
            evidence.append(
                _NameClaimEvidence(
                    name_variants=frozenset(variants),
                    claims=frozenset(claims),
                    numbers=frozenset(_non_year_numbers(numbers)),
                    years=frozenset(years),
                )
            )
    return evidence


def _row_stat_claims(row: dict[str, Any]) -> set[tuple[str, str]]:
    claims: set[tuple[str, str]] = set()
    for key, value in row.items():
        stat = _normalize_stat_unit(key)
        if stat is None:
            continue
        normalized = _normalize_numeric_token(str(value))
        if normalized is not None:
            claims.add((normalized, stat))
    return claims


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


def _matched_items_share_name(items: list[_NameClaimEvidence]) -> bool:
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
    items: list[_NameClaimEvidence],
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
    if re.search(rf"\b{_NAME_TOKEN_RE}\s+{_NAME_TOKEN_RE}\b", text):
        return True
    generic_words = _GENERIC_NAME_TOKENS
    if any(token not in generic_words for token in re.findall(rf"\b{_NAME_TOKEN_RE}\b", text)):
        return True
    return _contains_lowercase_name_phrase(
        _normalize_claim_text(text),
        generic_words={token.lower() for token in generic_words},
    )


def _mentions_unmatched_name(text: str, matched_items: list[_NameClaimEvidence]) -> bool:
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
    return _contains_lowercase_name_phrase(normalized_text, generic_words=generic_words)


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


def _rows_to_dicts(columns: list[str], rows: list[tuple]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


def _grounded_database_unsupported_reason(query_result: Any) -> UnsupportedReason:
    reason = query_result.unsupported_reason
    if reason == "ambiguous":
        return "ambiguous"
    if reason == "unsupported":
        return "unsupported"
    if "unsupported_reason" not in query_result.columns:
        return "no_data"
    return "unsupported"
