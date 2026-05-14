"""Shared answer service used by CLI and API."""

from __future__ import annotations

import json
import logging
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
        response = make_request(prompt, max_tokens=900, temperature=0.2)
        biography = _parse_biography_json(response.content)
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
    warning_texts = [verification.warning for verification in verifications if verification.warning]
    answer_text = biography["answer"]
    if warning_texts:
        answer_text = (
            f"{answer_text}\n\n"
            "Note: Some stat claims in this biography could not be verified against DuckDB."
        )

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
            if isinstance(data, dict):
                return data
        raise
    if not isinstance(data, dict):
        raise ValueError("LLM biography output must be a JSON object")
    return data


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
