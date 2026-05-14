"""Player biography route-case answering."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from baseball_rag import biography_contract as _biography_contract
from baseball_rag.biography_contract import BiographyContractError
from baseball_rag.db.duckdb_schema import get_duckdb
from baseball_rag.db.player_stat_claims import (
    PlayerStatClaim,
    shape_biography_stat_claim_consensus,
    verify_player_stat_claims,
)
from baseball_rag.outcomes import ambiguous_outcome, llm_unavailable_outcome, no_data_outcome
from baseball_rag.provenance import SourceRecord, StructuredAnswer, compact_data_manifest

_db_verify_player_stat_claims_consensus: Any | None
try:
    from baseball_rag.db.player_stat_claims import (
        verify_player_stat_claims_consensus as _db_verify_player_stat_claims_consensus,
    )
except ImportError:  # pragma: no cover - removed when the DB consensus slice lands
    _db_verify_player_stat_claims_consensus = None

build_biography_json_repair_prompt = _biography_contract.build_biography_json_repair_prompt
is_biography_json_contract = _biography_contract.is_biography_json_contract
loads_json_object = _biography_contract.loads_json_object
parse_biography_json = _biography_contract.parse_biography_json
request_biography_json = _biography_contract.request_biography_json


def verify_player_stat_claims_consensus(
    player_id: str,
    claims: list[PlayerStatClaim],
    *,
    conn: Any,
) -> list[Any]:
    """Verify biography stat claims with the Retrosheet consensus API when present."""
    if _db_verify_player_stat_claims_consensus is not None:
        return _db_verify_player_stat_claims_consensus(player_id, claims, conn=conn)
    return verify_player_stat_claims(player_id, claims, conn=conn)


@dataclass
class PlayerBiographyCaseAnswerer:
    """Answer a routed player biography case."""

    conn_factory: Callable[[], Any] = get_duckdb
    make_request: Callable[..., Any] | None = None
    verify_claims_consensus: Callable[..., list[Any]] = verify_player_stat_claims_consensus
    extract_claims: Callable[[str], list[PlayerStatClaim]] | None = None
    request_biography: Callable[[Any, tuple[str, str]], dict[str, Any]] | None = None

    def answer(self, question: str, decision: Any) -> StructuredAnswer:
        player_name = getattr(decision, "player_name", None)
        if not player_name:
            return ambiguous_outcome(
                answer="I need a specific player name before I can generate a biography.",
                intent=decision.intent,
                warnings=["No biography was generated because no player name was resolved."],
            )

        from baseball_rag.corpus.player_bios import resolve_player_by_name

        conn = self.conn_factory()
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
                    f"No player named '{player_name}' was found in the local DuckDB player "
                    "registry."
                ),
                intent=decision.intent,
                warnings=["No biography was generated because the player was not found in DuckDB."],
            )

        player = resolution.candidates[0]
        extract_claims = self.extract_claims or extract_supplied_stat_claims
        supplied_claims = extract_claims(decision.raw_question or question)
        if supplied_claims:
            return self._answer_supplied_claims(
                player_id=player.player_id,
                player_name=player.full_name,
                claims=supplied_claims,
                intent=decision.intent,
                conn=conn,
            )

        try:
            from baseball_rag.generation.llm import LLMError, make_request
            from baseball_rag.generation.prompt import build_player_biography_json_prompt

            request = self.make_request or make_request
            prompt = build_player_biography_json_prompt(
                question=decision.raw_question or question,
                player_name=player.full_name,
                player_id=player.player_id,
                debut=player.debut,
                final_game=player.final_game,
            )
            request_biography = self.request_biography or request_biography_json
            biography = request_biography(request, prompt)
        except (ConnectionError, TimeoutError) as exc:
            return llm_unavailable_outcome(
                answer=(
                    "LM Studio was unavailable, so no player biography was generated. "
                    "Player biographies require the local LLM."
                ),
                intent=decision.intent,
                warnings=[str(exc)],
            )
        except (LLMError, BiographyContractError, ValueError, TypeError) as exc:
            return llm_unavailable_outcome(
                answer=(
                    "The local LLM did not return the structured biography JSON contract, "
                    "so no player biography was generated."
                ),
                intent=decision.intent,
                warnings=[str(exc)],
            )

        return self._answer_generated_biography(
            player=player,
            biography=biography,
            intent=decision.intent,
            conn=conn,
        )

    def _answer_generated_biography(
        self,
        *,
        player: Any,
        biography: dict[str, Any],
        intent: str,
        conn: Any,
    ) -> StructuredAnswer:
        verifications = self.verify_claims_consensus(
            player.player_id,
            biography["claims"],
            conn=conn,
        )
        claim_presentation = shape_biography_stat_claim_consensus(verifications)
        answer_text = biography["answer"]
        if verifications:
            answer_text = f"{answer_text}\n\n{claim_presentation.note}"

        source_rows = (
            claim_presentation.rows
            if verifications
            else [
                {
                    "player_id": player.player_id,
                    "name": player.full_name,
                    "status": "resolved",
                }
            ]
        )
        source = duckdb_source(
            "DuckDB Lahman + Retrosheet biography stat consensus",
            tables=claim_presentation.tables,
            rows=source_rows,
            sql=claim_presentation.sql,
            detail=claim_presentation.source_detail,
            data_manifest=claim_presentation.data_manifest,
        )
        return StructuredAnswer(
            answer=answer_text,
            intent=intent,
            sources=[source],
            warnings=claim_presentation.warnings,
            metadata={
                "resolved_player": {
                    "player_id": player.player_id,
                    "name": player.full_name,
                    "debut": player.debut,
                    "final_game": player.final_game,
                },
                "stat_claims": claim_presentation.rows,
                "stat_claim_summary": claim_presentation.summary,
            },
        )

    def _answer_supplied_claims(
        self,
        *,
        player_id: str,
        player_name: str,
        claims: list[PlayerStatClaim],
        intent: str,
        conn: Any,
    ) -> StructuredAnswer:
        verifications = self.verify_claims_consensus(player_id, claims, conn=conn)
        claim_presentation = shape_biography_stat_claim_consensus(verifications)
        source = duckdb_source(
            "DuckDB Lahman + Retrosheet supplied biography stat consensus",
            tables=claim_presentation.tables,
            rows=claim_presentation.rows,
            sql=claim_presentation.sql,
            detail=claim_presentation.source_detail,
            data_manifest=claim_presentation.data_manifest,
        )
        return StructuredAnswer(
            answer=(
                f"I checked the stat claims in the supplied biography for {player_name}.\n\n"
                f"{claim_presentation.note}"
            ),
            intent=intent,
            sources=[source],
            warnings=claim_presentation.warnings,
            metadata={
                "stat_claims": claim_presentation.rows,
                "stat_claim_summary": claim_presentation.summary,
                "context_player_name": player_name,
            },
        )


def extract_supplied_stat_claims(question: str) -> list[PlayerStatClaim]:
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


def duckdb_source(
    label: str,
    *,
    tables: list[str],
    rows: list[dict[str, Any]] | None = None,
    sql: str | None = None,
    detail: str | None = None,
    data_manifest: dict[str, Any] | None = None,
) -> SourceRecord:
    return SourceRecord(
        type="duckdb",
        label=label,
        detail=detail
        or f"Tables: {', '.join(tables)}. Dataset: local Hugging Face NeuML/baseballdata CSVs.",
        sql=sql,
        rows=rows or [],
        data_manifest=data_manifest or compact_data_manifest(),
    )


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
