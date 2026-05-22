"""LLM JSON contract for generated player biographies."""

from __future__ import annotations

import json
from typing import Any

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
    raw_claims = data.get("stat_claims", [])
    if raw_claims is None:
        raw_claims = []
    if not isinstance(raw_claims, list):
        raise BiographyContractError("biography JSON stat_claims must be a list")
    try:
        claims = [PlayerStatClaim.from_payload(claim) for claim in raw_claims]
    except ValueError as exc:
        raise BiographyContractError(str(exc)) from exc
    return {"answer": answer_text.strip(), "claims": claims}


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
        "Only include stat_claims for supported DuckDB-verifiable stats: HR, RBI, H, "
        "SB, AVG, OPS, W, ERA, WHIP, SO, or PO. "
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
