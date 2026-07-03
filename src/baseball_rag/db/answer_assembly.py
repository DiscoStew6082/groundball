"""Public answer assembly for DuckDB-backed query results."""

from __future__ import annotations

from typing import Any

from baseball_rag.db.grounded_database_types import GroundedDatabaseResult
from baseball_rag.db.queries import StatQueryPlan, StatQueryResult
from baseball_rag.outcomes import no_data_outcome, unsupported_outcome
from baseball_rag.provenance import (
    ReviewReason,
    SourceRecord,
    StructuredAnswer,
    UnsupportedReason,
    compact_data_manifest,
    compact_secondary_data_manifest,
    source_authority_catalog,
)


def answer_stat_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    """Build the public answer and provenance from an executed stat result."""
    if plan.kind == "player":
        return _answer_player_stat_result(plan, query_result)
    if plan.kind == "leaderboard":
        return _answer_leaderboard_result(plan, query_result)
    return _answer_career_leaderboard_result(plan, query_result)


def answer_grounded_database_result(
    *,
    raw_question: str,
    intent: str,
    query_result: GroundedDatabaseResult,
) -> StructuredAnswer:
    """Build the public answer and provenance from an executed grounded DB result."""
    source = SourceRecord(
        type="duckdb",
        label=query_result.source_label,
        detail=query_result.source_detail,
        sql=query_result.sql,
        columns=query_result.columns,
        rows=_rows_to_dicts(query_result.columns, query_result.rows[:100]),
        data_manifest=_grounded_database_data_manifest(query_result),
    )

    if query_result.row_count == 0:
        reason = _grounded_database_unsupported_reason(query_result)
        review_reason: ReviewReason = "ambiguous" if reason == "ambiguous" else "unsupported"
        unsupported_detail = _grounded_database_unsupported_detail(query_result)
        answer = (
            f"I can't answer that from the grounded local baseball data. {unsupported_detail}"
            if unsupported_detail
            else (
                f"No results found for '{raw_question}'.\n"
                "Try rephrasing with a specific team, player, stat, or year."
            )
        )
        return unsupported_outcome(
            answer=answer,
            intent=intent,
            sources=[source],
            reason=reason,
            review_reason=review_reason,
        )

    warnings = []
    if query_result.truncated:
        warnings.append("Results were truncated at the configured row limit.")
    from baseball_rag.db.grounded_database_runtime import format_result

    return StructuredAnswer(
        answer=format_result(query_result, raw_question),
        intent=intent,
        sources=[source],
        warnings=warnings,
    )


def _answer_player_stat_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    if not query_result.rows:
        qualifier = f" in {plan.year}" if plan.year else ""
        return no_data_outcome(
            answer=(
                f"No {plan.stat} result found for {plan.player_name}{qualifier} "
                f"in the local Lahman-derived {plan.table} data."
            ),
            intent=plan.intent,
            sources=[_source_from_stat_result(query_result)],
            warnings=["No alternate leaderboard was returned because the question named a player."],
        )

    result = query_result.rows[0]
    team_str = f" ({result['team']})" if result["team"] else ""
    return StructuredAnswer(
        answer=f"{result['name']}{team_str} ({result['year']}): {result['stat_value']} {plan.stat}",
        intent=plan.intent,
        sources=[_source_from_stat_result(query_result)],
    )


def _answer_leaderboard_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    rows = query_result.rows
    if not rows:
        return no_data_outcome(
            answer=(
                f"No {plan.stat} results found for {plan.start_year}-{plan.end_year} "
                "in the local Lahman-derived data."
            ),
            intent=plan.intent,
            sources=[_source_from_stat_result(query_result)],
            warnings=[
                "No alternate leaderboard was returned because the question specified a year."
            ],
        )

    lines = [f"Top {plan.stat} leaders ({plan.start_year}-{plan.end_year}):"]
    for i, row in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {row['name']}: {row['stat_value']} {plan.stat}")
    return StructuredAnswer(
        answer="\n".join(lines),
        intent=plan.intent,
        sources=[_source_from_stat_result(query_result)],
    )


def _answer_career_leaderboard_result(
    plan: StatQueryPlan,
    query_result: StatQueryResult,
) -> StructuredAnswer:
    rows = query_result.rows
    lines = [f"All-time career {plan.stat} leaders:"]
    for i, row in enumerate(rows[:10], 1):
        lines.append(f"  {i}. {row['name']}: {row['stat_value']} {plan.stat}")
    return StructuredAnswer(
        answer="\n".join(lines),
        intent=plan.intent,
        sources=[_source_from_stat_result(query_result)],
    )


def _source_from_stat_result(query_result: Any) -> SourceRecord:
    return SourceRecord(
        type="duckdb",
        label=query_result.label,
        detail=(
            f"Tables: {', '.join(query_result.tables)}. "
            "Dataset: local Hugging Face NeuML/baseballdata CSVs."
        ),
        sql=query_result.executed_sql,
        rows=query_result.rows,
        data_manifest=compact_data_manifest(),
    )


def _rows_to_dicts(columns: list[str], rows: list[tuple]) -> list[dict[str, Any]]:
    return [dict(zip(columns, row)) for row in rows]


def _grounded_database_data_manifest(query_result: GroundedDatabaseResult) -> dict[str, Any]:
    manifest = compact_data_manifest()
    source_text = " ".join(
        (
            query_result.source_label,
            query_result.source_detail,
            query_result.sql,
        )
    ).lower()
    if "retrosheet" not in source_text:
        return manifest

    required_tables = []
    if "retrosheet_pitcher_strikeout_side_events" in source_text:
        required_tables.append("retrosheet_pitcher_strikeout_side_events")
    if "retrosheet_batting" in source_text:
        required_tables.append("retrosheet_batting")
    if not required_tables:
        required_tables.append("retrosheet_pitcher_strikeout_side_events")

    manifest["secondary_manifests"] = {
        "retrosheet": compact_secondary_data_manifest(
            "retrosheet",
            required_tables=required_tables,
        ),
    }
    manifest["source_authorities"] = _retrosheet_event_authorities()
    return manifest


def _retrosheet_event_authorities() -> list[dict[str, Any]]:
    authorities = source_authority_catalog(include_retrosheet=True)
    for authority in authorities:
        if authority.get("name") != "Retrosheet":
            continue
        scopes = list(authority.get("scopes", []))
        if "event_derived_grounded_database_answers" not in scopes:
            scopes.append("event_derived_grounded_database_answers")
        if "game_level_grounded_database_answers" not in scopes:
            scopes.append("game_level_grounded_database_answers")
        authority["scopes"] = scopes
    return authorities


def _grounded_database_unsupported_reason(
    query_result: GroundedDatabaseResult,
) -> UnsupportedReason:
    reason = query_result.unsupported_reason
    if reason == "ambiguous":
        return "ambiguous"
    if reason == "unsupported":
        return "unsupported"
    if "unsupported_reason" not in query_result.columns:
        return "no_data"
    return "unsupported"


def _grounded_database_unsupported_detail(
    query_result: GroundedDatabaseResult,
) -> str | None:
    if "unsupported_reason" not in query_result.columns:
        return None
    if not query_result.params:
        return None
    detail = str(query_result.params[0]).strip()
    return detail or None
