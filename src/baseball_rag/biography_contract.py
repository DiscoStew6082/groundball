"""LLM JSON contract for generated player biographies."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from baseball_rag.db.biography_stat_vocabulary import (
    biography_claim_prompt_stat_list,
    biography_claim_stat_aliases,
    biography_claim_stat_regex_source,
    normalize_biography_claim_stat,
)
from baseball_rag.db.player_stat_claims import PlayerStatClaim
from baseball_rag.generation.json_parsing import extract_json_blocks, strip_markdown_fence


class BiographyContractError(ValueError):
    """Raised when the biography LLM contract cannot be parsed or repaired."""


def parse_biography_json(content: str) -> dict[str, Any]:
    """Parse and validate the player biography JSON contract."""
    data = loads_json_object(content)
    answer_text = data.get("answer")
    if not isinstance(answer_text, str) or not answer_text.strip():
        raise BiographyContractError("biography JSON requires a non-empty answer string")
    raw_claims = data.get("stat_claims")
    if not isinstance(raw_claims, list):
        raise BiographyContractError("biography JSON stat_claims must be a list")
    try:
        claims = [PlayerStatClaim.from_payload(claim) for claim in raw_claims]
    except ValueError as exc:
        raise BiographyContractError(str(exc)) from exc
    validate_biography_claim_completeness(answer_text, claims)
    return {"answer": answer_text.strip(), "claims": claims}


def validate_biography_claim_completeness(
    answer_text: str,
    claims: list[PlayerStatClaim],
) -> None:
    """Reject generated prose that omits explicit supported stat claims."""
    missing_claims = [
        mention
        for mention in find_supported_stat_mentions(answer_text)
        if not _mention_has_claim(mention, claims)
    ]
    if missing_claims:
        sample = missing_claims[0]
        raise BiographyContractError(
            "biography answer includes an explicit supported stat claim missing from "
            f"stat_claims: {sample['text']}"
        )


def find_supported_stat_mentions(answer_text: str) -> list[dict[str, object]]:
    """Find explicit value-plus-supported-stat mentions in biography prose."""
    stat_pattern = biography_claim_stat_regex_source()
    stat_before_value_pattern = _stat_before_value_regex_source()
    value_before_stat = re.compile(
        r"(?P<value>(?:\d[\d,]*(?:\.\d+)?|\.\d+))\s+"
        r"(?:(?:career|season|regular-season|major-league|MLB)\s+)?"
        rf"(?P<stat>{stat_pattern})\b",
        re.IGNORECASE,
    )
    stat_before_value = re.compile(
        rf"\b(?P<stat>{stat_before_value_pattern})\b\s+"
        r"(?:was|were|of|at|to|is|:)?\s*"
        r"(?P<value>(?:\d[\d,]*(?:\.\d+)?|\.\d+))",
        re.IGNORECASE,
    )
    mentions: list[dict[str, object]] = []
    seen: set[tuple[int, int, str, str]] = set()
    for pattern in (value_before_stat, stat_before_value):
        for match in pattern.finditer(answer_text):
            key = (
                match.start(),
                match.end(),
                normalize_biography_claim_stat(match.group("stat")),
                _normalize_claim_value(match.group("value")),
            )
            if key in seen:
                continue
            seen.add(key)
            scope = _nearby_scope(answer_text, match.start(), match.end(), match.group(0))
            year = _nearby_year(answer_text, match.start(), match.end())
            if year is not None and scope != "career":
                scope = "season"
            mentions.append(
                {
                    "stat": key[2],
                    "value": key[3],
                    "scope": scope,
                    "year": year,
                    "text": match.group(0),
                }
            )
    return mentions


def _mention_has_claim(mention: dict[str, object], claims: list[PlayerStatClaim]) -> bool:
    for claim in claims:
        if normalize_biography_claim_stat(claim.stat) != mention["stat"]:
            continue
        if _normalize_claim_value(claim.value) == mention["value"]:
            year = mention.get("year")
            if mention.get("scope") == "career" and claim.resolved_scope != "career":
                continue
            if (
                mention.get("scope") != "career"
                and year is not None
                and (claim.resolved_scope != "season" or claim.year != year)
            ):
                continue
            return True
    return False


def _normalize_claim_value(value: object) -> str:
    text = str(value).replace(",", "").strip()
    if text.startswith("."):
        text = f"0{text}"
    try:
        decimal_value = Decimal(text)
    except InvalidOperation:
        return text
    normalized = decimal_value.normalize()
    if normalized == normalized.to_integral():
        return str(int(normalized))
    return format(normalized, "f").rstrip("0").rstrip(".")


def _same_sentence_after(text: str, end: int, max_chars: int) -> str:
    segment = text[end : end + max_chars]
    stop = re.search(r"[.?!;]", segment)
    return segment[: stop.start()] if stop else segment


def _same_sentence_before(text: str, start: int, max_chars: int) -> str:
    segment = text[max(0, start - max_chars) : start]
    stop_positions = [segment.rfind(mark) for mark in ".?!;"]
    last_stop = max(stop_positions)
    if last_stop >= 0:
        return segment[last_stop + 1 :]
    return segment


def _nearby_year(text: str, start: int, end: int) -> int | None:
    before = _same_sentence_before(text, start, 40)
    after = _same_sentence_after(text, end, 40)
    patterns = (
        re.search(r"\b(?:in|during)\s+(18\d{2}|19\d{2}|20\d{2})\b", after, re.IGNORECASE),
        re.search(r"\b(?:in|during)\s+(18\d{2}|19\d{2}|20\d{2})\b", before, re.IGNORECASE),
        re.search(r"\b(18\d{2}|19\d{2}|20\d{2})\b[^.?!]{0,30}$", before),
    )
    for match in patterns:
        if match:
            return int(match.group(1))
    return None


def _nearby_scope(text: str, start: int, end: int, matched_text: str) -> str | None:
    before = text[max(0, start - 20) : start]
    after = text[end : end + 20]
    context = f"{before} {matched_text} {after}"
    if re.search(r"\bcareer\b", context, re.IGNORECASE):
        return "career"
    return None


def _stat_before_value_regex_source() -> str:
    verb_like_aliases = {"hit", "hits", "win", "wins"}
    aliases = [
        alias
        for alias in biography_claim_stat_aliases()
        if alias.casefold() not in verb_like_aliases
    ]
    return "|".join(re.escape(alias) for alias in sorted(aliases, key=len, reverse=True))


def request_biography_json(make_request_func: Any, prompt: tuple[str, str]) -> dict[str, Any]:
    """Call the local LLM for a biography JSON contract, retrying once for shape errors."""
    response = make_request_func(prompt, max_tokens=1400, temperature=0.0)
    try:
        return parse_biography_json(response.content)
    except (BiographyContractError, TypeError, json.JSONDecodeError) as first_exc:
        repair_response = make_request_func(
            build_biography_json_repair_prompt(response.content),
            max_tokens=1400,
            temperature=0.0,
        )
        try:
            return parse_biography_json(repair_response.content)
        except (BiographyContractError, TypeError, json.JSONDecodeError) as second_exc:
            raise BiographyContractError(
                f"{first_exc}; retry did not return the biography JSON contract: {second_exc}"
            ) from second_exc


def build_biography_json_repair_prompt(invalid_content: str) -> tuple[str, str]:
    """Prompt the LLM to repair a malformed biography response into the JSON contract."""
    return (
        "You repair malformed baseball biography responses into valid JSON.\n"
        "Return ONLY compact valid JSON with this exact shape:\n"
        '{"answer": string, "stat_claims": ['
        '{"stat": string, "value": number|string, "scope": "career"|"season", '
        '"year": number|null, "text": string, '
        '"table": "batting"|"pitching"|"fielding"|null}'
        "]}\n"
        "Do not include markdown, bullets, notes, analysis, or examples. "
        "Only include stat_claims for supported DuckDB-verifiable stats: "
        f"{biography_claim_prompt_stat_list()}. "
        "The first character must be { and the last character must be }.",
        (
            "Repair this invalid response into the final JSON contract. "
            "Preserve only supported, explicit stat claims:\n\n"
            f"{invalid_content[:4000]}"
        ),
    )


def loads_json_object(content: str) -> dict[str, Any]:
    """Load the final biography JSON object from plain, fenced, or chattery content."""
    text = strip_markdown_fence(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        contract: dict[str, Any] | None = None
        for start, end in extract_json_blocks(text):
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and is_biography_json_contract(data):
                contract = data
        if contract is not None:
            return contract
        raise
    if not isinstance(data, dict):
        raise BiographyContractError("LLM biography output must be a JSON object")
    return data


def is_biography_json_contract(data: dict[str, Any]) -> bool:
    """Return True when a parsed object has the biography response contract shape."""
    answer_text = data.get("answer")
    return (
        isinstance(answer_text, str)
        and bool(answer_text.strip())
        and isinstance(data.get("stat_claims"), list)
    )
