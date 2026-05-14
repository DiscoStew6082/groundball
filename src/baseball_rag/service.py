"""Shared answer service used by CLI and API."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from baseball_rag.conversation import resolve_followup
from baseball_rag.db import init_db
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.player_stat_claims import (
    PlayerStatClaim,
    PlayerStatVerification,
    verify_player_stat_claims,
)
from baseball_rag.generation.json_parsing import extract_json_blocks, strip_markdown_fence
from baseball_rag.outcomes import (
    ambiguous_outcome,
    llm_unavailable_outcome,
    no_data_outcome,
    unsupported_outcome,
)
from baseball_rag.provenance import (
    ReviewReason,
    SourceRecord,
    StructuredAnswer,
    UnsupportedReason,
    compact_data_manifest,
)
from baseball_rag.request_dispatch import AnswerHandlers, RequestAnswerDispatcher
from baseball_rag.routing import route
from baseball_rag.stat_query import answer_stat_query

logger = logging.getLogger(__name__)


def answer(
    question: str,
    *,
    conversation: list[dict[str, Any]] | None = None,
) -> StructuredAnswer:
    """Answer a question with explicit provenance metadata."""
    dispatcher = RequestAnswerDispatcher(
        initialize=init_db,
        resolve_followup=resolve_followup,
        route_question=route,
        handlers=AnswerHandlers(
            stat_query=answer_stat_query,
            player_biography=_answer_player_biography,
            freeform_query=_answer_freeform,
            general_explanation=_answer_general,
        ),
    )
    return dispatcher.answer(question, conversation=conversation)


def render_text(result: StructuredAnswer) -> str:
    """Render a structured answer for terminal/chat use."""
    lines = [result.answer]
    if result.warnings:
        lines.append("")
        lines.extend(f"Warning: {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _answer_player_biography(question: str, decision: Any) -> StructuredAnswer:
    player_name = getattr(decision, "player_name", None)
    if not player_name:
        return ambiguous_outcome(
            answer="I need a specific player name before I can generate a biography.",
            intent=decision.intent,
            warnings=["No biography was generated because no player name was resolved."],
        )

    from baseball_rag.corpus.player_bios import resolve_player_by_name

    conn = get_duckdb()
    resolution = resolve_player_by_name(player_name, conn)
    if resolution.ambiguous:
        choices = ", ".join(
            f"{c.full_name} ({c.debut or '?'}-{c.final_game or '?'})"
            for c in resolution.candidates[:5]
        )
        return ambiguous_outcome(
            answer=(
                f"'{player_name}' is ambiguous in the local player registry. "
                f"Try a fuller name. Possible matches: {choices}."
            ),
            intent=decision.intent,
            warnings=["No biography was generated because the player name was ambiguous."],
        )
    if resolution.player_id is None:
        return no_data_outcome(
            answer=(
                f"No player named '{player_name}' was found in the local DuckDB player registry."
            ),
            intent=decision.intent,
            warnings=["No biography was generated because the player was not found in DuckDB."],
        )

    player = resolution.candidates[0]
    supplied_claims = _extract_supplied_stat_claims(decision.raw_question or question)
    if supplied_claims:
        return _answer_supplied_biography_claims(
            player_id=player.player_id,
            player_name=player.full_name,
            claims=supplied_claims,
            intent=decision.intent,
            conn=conn,
        )

    try:
        from baseball_rag.generation.llm import LLMError, make_request
        from baseball_rag.generation.prompt import build_player_biography_json_prompt

        prompt = build_player_biography_json_prompt(
            question=decision.raw_question or question,
            player_name=player.full_name,
            player_id=player.player_id,
            debut=player.debut,
            final_game=player.final_game,
        )
        biography = _request_biography_json(make_request, prompt)
    except (ConnectionError, TimeoutError) as exc:
        return llm_unavailable_outcome(
            answer=(
                "LM Studio was unavailable, so no player biography was generated. "
                "Player biographies require the local LLM."
            ),
            intent=decision.intent,
            warnings=[str(exc)],
        )
    except (LLMError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return llm_unavailable_outcome(
            answer=(
                "The local LLM did not return the structured biography JSON contract, "
                "so no player biography was generated."
            ),
            intent=decision.intent,
            warnings=[str(exc)],
        )

    verifications = verify_player_stat_claims(player.player_id, biography["claims"], conn=conn)
    answer_text = biography["answer"]
    if verifications:
        answer_text = f"{answer_text}\n\n{_biography_verification_note(verifications)}"
    warning_texts = [verification.warning for verification in verifications if verification.warning]

    source_rows = (
        [verification.to_row() for verification in verifications]
        if verifications
        else [
            {
                "player_id": player.player_id,
                "name": player.full_name,
                "status": "resolved",
            }
        ]
    )
    source_sql = _single_verification_sql(verifications)
    source = _duckdb_source(
        "DuckDB player identity and biography stat verification",
        tables=_verification_tables(verifications),
        rows=source_rows,
        sql=source_sql,
    )
    return StructuredAnswer(
        answer=answer_text,
        intent=decision.intent,
        sources=[source],
        warnings=warning_texts,
        metadata={
            "resolved_player": {
                "player_id": player.player_id,
                "name": player.full_name,
                "debut": player.debut,
                "final_game": player.final_game,
            },
            "stat_claims": [verification.to_row() for verification in verifications],
        },
    )


def _biography_verification_note(verifications: list[PlayerStatVerification]) -> str:
    contradicted = [
        verification for verification in verifications if verification.status == "contradicted"
    ]
    unresolved = [
        verification
        for verification in verifications
        if verification.warning and verification.status != "contradicted"
    ]
    verified_count = sum(1 for verification in verifications if verification.verified)
    invalid_count = len(verifications) - verified_count

    parts = [_verification_scorecard(len(verifications), verified_count, invalid_count)]
    if contradicted:
        prefix = (
            "Most stat claims were verified. " if verified_count > len(verifications) / 2 else ""
        )
        parts.append(f"{prefix}{_contradiction_sentence(contradicted)}")
    if unresolved:
        parts.append(_unverifiable_sentence(unresolved))
    return " ".join(parts)


def _answer_supplied_biography_claims(
    *,
    player_id: str,
    player_name: str,
    claims: list[PlayerStatClaim],
    intent: str,
    conn: Any,
) -> StructuredAnswer:
    verifications = verify_player_stat_claims(player_id, claims, conn=conn)
    warning_texts = [verification.warning for verification in verifications if verification.warning]
    source = _duckdb_source(
        "DuckDB supplied biography stat verification",
        tables=_verification_tables(verifications),
        rows=[verification.to_row() for verification in verifications],
        sql=_single_verification_sql(verifications),
    )
    return StructuredAnswer(
        answer=(
            f"I checked the stat claims in the supplied biography for {player_name}.\n\n"
            f"{_biography_verification_note(verifications)}"
        ),
        intent=intent,
        sources=[source],
        warnings=warning_texts,
        metadata={"stat_claims": [verification.to_row() for verification in verifications]},
    )


def _extract_supplied_stat_claims(question: str) -> list[PlayerStatClaim]:
    if not _looks_like_supplied_claim_verification(question):
        return []

    claims: list[tuple[int, PlayerStatClaim]] = []
    stat_pattern = re.compile(
        r"(?P<value>(?:\d[\d,]*(?:\.\d+)?|\.\d+))\s*"
        r"(?P<stat>HR|HRS|home runs?|RBI|RBIs|runs batted in|H|hits?|SB|stolen bases?|"
        r"AVG|batting average|OPS|W|wins?|ERA|WHIP|SO|strikeouts?|PO|putouts?)\b",
        re.IGNORECASE,
    )
    for match in stat_pattern.finditer(question):
        year = _extract_claim_year(question, match.end())
        claims.append(
            (
                match.start(),
                PlayerStatClaim(
                    stat=match.group("stat"),
                    value=match.group("value").replace(",", ""),
                    scope="season" if year is not None else "career",
                    year=year,
                    text=match.group(0),
                ),
            )
        )

    mvp_pattern = re.compile(
        r"\b(?P<value>\d+|one|two|three|four|five|six|seven|eight|nine|ten)"
        r"[-\s]*time\s+(?:[A-Za-z]+\s+League\s+)?MVP\b",
        re.IGNORECASE,
    )
    for match in mvp_pattern.finditer(question):
        claims.append(
            (
                match.start(),
                PlayerStatClaim(
                    stat="MVP",
                    value=_claim_number_value(match.group("value")),
                    scope="career",
                    text=match.group(0),
                ),
            )
        )

    return [claim for _, claim in sorted(claims, key=lambda item: item[0])]


def _extract_claim_year(question: str, claim_end: int) -> int | None:
    nearby = question[claim_end : claim_end + 40]
    match = re.search(r"\b(?:in|during)\s+(18\d{2}|19\d{2}|20\d{2})\b", nearby)
    if match:
        return int(match.group(1))
    return None


def _looks_like_supplied_claim_verification(question: str) -> bool:
    lower_q = question.lower()
    return (
        "duckdb" in lower_q
        and "claim" in lower_q
        and any(term in lower_q for term in ("verified", "verify", "verifiable"))
    )


def _claim_number_value(value: str) -> int:
    word_values = {
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
    normalized = value.lower()
    if normalized in word_values:
        return word_values[normalized]
    return int(value)


def _verification_scorecard(total: int, verified_count: int, invalid_count: int) -> str:
    status = "passing" if invalid_count == 0 else "failing"
    return (
        f"Stat claim verification: total claims {total}, valid claims {verified_count}, "
        f"invalid claims {invalid_count}. Score: {status} ({verified_count}/{total} verified)."
    )


def _contradiction_sentence(verifications: list[PlayerStatVerification]) -> str:
    count_label = (
        "One stat claim was"
        if len(verifications) == 1
        else f"{len(verifications)} stat claims were"
    )
    details = "; ".join(_contradiction_detail(verification) for verification in verifications)
    return f"{count_label} contradicted by DuckDB: {details}."


def _contradiction_detail(verification: PlayerStatVerification) -> str:
    claim = verification.claim
    scope = claim.resolved_scope if claim.year is None else f"{claim.resolved_scope} {claim.year}"
    return (
        f"{claim.stat} was claimed as {_format_claim_value(claim.value)}, "
        f"but DuckDB has {_format_claim_value(verification.actual_value)} for {scope}"
    )


def _unverifiable_sentence(verifications: list[PlayerStatVerification]) -> str:
    details = "; ".join(_unverifiable_detail(verification) for verification in verifications)
    if len(verifications) == 1:
        return f"One stat claim was not verifiable against DuckDB: {details}."
    return f"{len(verifications)} stat claims were not verifiable against DuckDB: {details}."


def _unverifiable_detail(verification: PlayerStatVerification) -> str:
    claim = verification.claim
    value = _format_claim_value(claim.value)
    if verification.status == "unsupported_stat":
        return (
            f"{claim.stat} was claimed as {value}, "
            "but DuckDB verification does not support that stat"
        )
    if verification.status == "invalid_value":
        return f"{claim.stat} value {value} could not be interpreted as a number"
    if verification.status == "no_data":
        scope = (
            claim.resolved_scope if claim.year is None else f"{claim.resolved_scope} {claim.year}"
        )
        return f"{claim.stat} was claimed as {value}, but DuckDB had no {scope} row to verify it"
    return f"{claim.stat} was claimed as {value}, but DuckDB could not verify it"


def _format_claim_value(value: object) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _answer_freeform(question: str, decision: Any) -> StructuredAnswer:
    from baseball_rag.db.freeform import format_result, query

    conn = get_duckdb()
    query_result = query(decision.raw_question, conn, year=getattr(decision, "year", None))
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
        reason = _freeform_unsupported_reason(query_result)
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
    return StructuredAnswer(
        answer=format_result(query_result, decision.raw_question),
        intent=decision.intent,
        sources=[source],
        warnings=warnings,
    )


def _answer_general(question: str, decision: Any) -> StructuredAnswer:
    from baseball_rag.generation.prompt import build_open_prompt

    try:
        from baseball_rag.generation.llm import LLMError, make_request

        response = make_request(
            build_open_prompt(decision.raw_question or question),
            max_tokens=700,
        )
    except (ConnectionError, TimeoutError, LLMError) as exc:
        return llm_unavailable_outcome(
            answer=(
                "LM Studio was unavailable, so no open explanation was generated. "
                "General explanation questions require the local LLM."
            ),
            intent=decision.intent,
            warnings=[str(exc)],
        )
    return StructuredAnswer(answer=response.content, intent=decision.intent)


def _parse_biography_json(content: str) -> dict[str, Any]:
    data = _loads_json_object(content)
    answer_text = data.get("answer")
    if not isinstance(answer_text, str) or not answer_text.strip():
        raise ValueError("biography JSON requires a non-empty answer string")
    raw_claims = data.get("stat_claims", [])
    if raw_claims is None:
        raw_claims = []
    if not isinstance(raw_claims, list):
        raise ValueError("biography JSON stat_claims must be a list")
    claims = [PlayerStatClaim.from_payload(claim) for claim in raw_claims]
    return {"answer": answer_text.strip(), "claims": claims}


def _request_biography_json(make_request_func: Any, prompt: tuple[str, str]) -> dict[str, Any]:
    """Call the local LLM for a biography JSON contract, retrying once for shape errors."""
    response = make_request_func(prompt, max_tokens=1400, temperature=0.0)
    try:
        return _parse_biography_json(response.content)
    except (ValueError, TypeError, json.JSONDecodeError) as first_exc:
        repair_response = make_request_func(
            _build_biography_json_repair_prompt(response.content),
            max_tokens=1400,
            temperature=0.0,
        )
        try:
            return _parse_biography_json(repair_response.content)
        except (ValueError, TypeError, json.JSONDecodeError) as second_exc:
            raise ValueError(
                f"{first_exc}; retry did not return the biography JSON contract: {second_exc}"
            ) from second_exc


def _build_biography_json_repair_prompt(invalid_content: str) -> tuple[str, str]:
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


def _loads_json_object(content: str) -> dict[str, Any]:
    text = strip_markdown_fence(content)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        for start, end in extract_json_blocks(text):
            try:
                data = json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and _is_biography_json_contract(data):
                return data
        raise
    if not isinstance(data, dict):
        raise ValueError("LLM biography output must be a JSON object")
    return data


def _is_biography_json_contract(data: dict[str, Any]) -> bool:
    """Return True when a parsed object has the biography response contract shape."""
    answer_text = data.get("answer")
    return (
        isinstance(answer_text, str)
        and bool(answer_text.strip())
        and isinstance(data.get("stat_claims"), list)
    )


def _duckdb_source(
    label: str,
    *,
    tables: list[str],
    rows: list[dict[str, Any]] | None = None,
    sql: str | None = None,
) -> SourceRecord:
    return SourceRecord(
        type="duckdb",
        label=label,
        detail=f"Tables: {', '.join(tables)}. Dataset: local Hugging Face NeuML/baseballdata CSVs.",
        sql=sql,
        rows=rows or [],
        data_manifest=compact_data_manifest(),
    )


def _single_verification_sql(verifications: list[PlayerStatVerification]) -> str | None:
    sql_values = {verification.sql for verification in verifications if verification.sql}
    if len(sql_values) == 1:
        return next(iter(sql_values))
    return None


def _verification_tables(verifications: list[PlayerStatVerification]) -> list[str]:
    tables = sorted({verification.table for verification in verifications if verification.table})
    return tables or ["people"]


def _rows_to_dicts(columns: list[str], rows: list[tuple]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


def _freeform_unsupported_reason(query_result: Any) -> UnsupportedReason:
    reason = query_result.unsupported_reason
    if reason == "ambiguous":
        return "ambiguous"
    if reason == "unsupported":
        return "unsupported"
    if "unsupported_reason" not in query_result.columns:
        return "no_data"
    return "unsupported"
