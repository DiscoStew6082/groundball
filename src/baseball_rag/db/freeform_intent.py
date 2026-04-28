"""Intent parsing and LLM-backed intent generation for freeform queries."""

import json
from collections.abc import Callable
from typing import Any, cast

from baseball_rag.db.freeform_assembler import _assemble_sql
from baseball_rag.db.freeform_types import QuerySpec
from baseball_rag.db.stat_registry import StatTable, get_stat, supported_stats, supported_tables
from baseball_rag.generation.json_parsing import extract_json_blocks, strip_markdown_fence
from baseball_rag.generation.llm import make_request as default_make_request

RequestFn = Callable[..., Any]

_INTENT_SYSTEM = (
    "You are a query planner. Given the user question, produce ONLY valid JSON "
    "-- no markdown fences, no explanation.\n"
    "\n"
    "Output format:\n"
    "{\n"
    '  "stat_tables": ["batting"],   -- list of: batting, pitching, fielding\n'
    '  "team_name_pattern": "Braves",  -- team nickname (omit if not about a team)\n'
    '  "year_value": 1936,           -- year ID filter (omit if no year mentioned)\n'
    '  "leader_stats": ["HR", "RBI"]  -- stats to find league-wide leaders for\n'
    "}\n"
    "\n"
    "Rules:\n"
    "- stat_tables: include ONLY the tables actually needed. "
    'Batting-only questions (HRs, RBIs, AVG) use ["batting"] only; '
    'pitching-only (wins, ERA) use ["pitching"] only.\n'
    "- team_name_pattern: extract nickname from question ('Yankees', 'Braves').\n"
    "- year_value: integer year when a specific year is mentioned.\n"
    '- leader_stats: stats to find league-wide leaders for -- e.g. ["HR","RBI","AVG"] '
    "for Triple Crown. Use canonical names (HR, RBI, AVG, ERA, W, etc.).\n"
    "- Omit any field entirely if it does not apply -- do not guess.\n"
)


def _parse_intent(raw: str) -> QuerySpec:
    """Parse LLM JSON output into a typed QuerySpec."""

    def _from_data(data: dict) -> QuerySpec | None:
        tables = data.get("stat_tables")
        if (
            not isinstance(tables, list)
            or not tables
            or any(str(t).lower() not in supported_tables() for t in tables)
        ):
            return None
        typed_tables = cast(list[StatTable], [str(t).lower() for t in tables])

        team_name_pattern = data.get("team_name_pattern")
        if team_name_pattern is not None and not isinstance(team_name_pattern, str):
            team_name_pattern = None

        year_value = data.get("year_value")
        if not isinstance(year_value, int):
            year_value = None

        leader_stats: list[str] = []
        for raw_stat in data.get("leader_stats") or []:
            if not isinstance(raw_stat, str):
                continue
            try:
                stat_def = get_stat(raw_stat)
            except ValueError:
                continue
            if stat_def.table in typed_tables:
                leader_stats.append(stat_def.canonical)

        return QuerySpec(
            stat_tables=typed_tables,
            team_name_pattern=team_name_pattern,
            year_value=year_value,
            leader_stats=leader_stats,
        )

    candidates = [
        raw,
        strip_markdown_fence(raw),
    ]

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            result = _from_data(data)
            if result is not None:
                return result
        except json.JSONDecodeError:
            pass

    for start, end in _extract_json_blocks(raw):
        try:
            data = json.loads(raw[start:end])
            result = _from_data(data)
            if result is not None:
                return result
        except json.JSONDecodeError:
            continue

    raise ValueError(f"Could not determine stat_tables from LLM response: {raw[:200]}")


def _generate_sql(
    question: str,
    schema: str,
    *,
    request_fn: RequestFn = default_make_request,
) -> str:
    """Convert question to SQL via structured intent extraction."""
    return _assemble_sql(_generate_query_spec(question, schema, request_fn=request_fn)).sql


def _generate_query_spec(
    question: str,
    schema: str,
    *,
    request_fn: RequestFn = default_make_request,
) -> QuerySpec:
    """Convert question to a typed query spec; SQL assembly happens separately."""
    prompt = (
        _INTENT_SYSTEM
        + "\n\nSupported stats:\n"
        + ", ".join(supported_stats())
        + "\n\nSchema:\n"
        + schema,
        question,
    )
    response = request_fn(prompt, max_tokens=1000, temperature=0.1)

    try:
        intent = _parse_intent(response.content.strip())
    except ValueError:
        retry_prompt = (
            _INTENT_SYSTEM
            + "\n\nCRITICAL: Only use stat_tables values from {'batting', 'pitching', 'fielding'}. "
            + "Do NOT use 'people'. Supported stats:\n"
            + ", ".join(supported_stats())
            + "\nSchema:\n"
            + schema,
            question,
        )
        response = request_fn(retry_prompt, max_tokens=1000, temperature=0.1)
        try:
            intent = _parse_intent(response.content.strip())
        except ValueError:
            recovered = _recover_roster_intent(question, response.content.strip())
            if recovered is None:
                raise
            intent = recovered

    return intent


def _recover_roster_intent(question: str, raw: str) -> QuerySpec | None:
    """Recover from LLM roster intents that omit stat_tables."""
    q = question.lower()
    if not any(token in q for token in ("played", "players", "roster")):
        return None

    for candidate in (raw, strip_markdown_fence(raw)):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        team_name_pattern = data.get("team_name_pattern")
        year_value = data.get("year_value")
        if not isinstance(team_name_pattern, str):
            continue
        if not isinstance(year_value, int):
            year_value = None
        return QuerySpec(
            stat_tables=cast(list[StatTable], ["batting", "pitching", "fielding"]),
            team_name_pattern=team_name_pattern,
            year_value=year_value,
        )

    return None


def _extract_json_blocks(text: str) -> list[tuple[int, int]]:
    """Backward-compatible wrapper for tests importing the private helper."""
    return extract_json_blocks(text)
