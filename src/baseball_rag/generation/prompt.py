"""Prompt templates for local LLM requests."""

PROMPT_VERSION = "grounded-answer-v1"


def build_player_biography_json_prompt(
    *,
    question: str,
    player_name: str,
    player_id: str,
    debut: str | None,
    final_game: str | None,
) -> tuple[str, str]:
    """Render the structured contract prompt for LLM-generated biographies."""
    return (
        "You are a knowledgeable baseball historian. Generate a concise player biography.\n"
        "Return ONLY valid JSON with this exact shape:\n"
        '{"answer": string, "stat_claims": ['
        '{"stat": string, "value": number|string, "scope": "career"|"season", '
        '"year": number|null, "text": string, '
        '"table": "batting"|"pitching"|"fielding"|null}'
        "]}\n"
        "The answer should be readable prose. Put every explicit career total or "
        "specific-season statistic from the answer into stat_claims. Use canonical "
        "stat names such as HR, RBI, H, SB, AVG, OPS, W, ERA, WHIP, SO, or PO. "
        "For ambiguous stats such as SO, identify whether the claim is batting or "
        "pitching in the table field or in the claim text. "
        "Only include stat_claims for supported DuckDB-verifiable stats: HR, RBI, H, "
        "SB, AVG, OPS, W, ERA, WHIP, SO, or PO. "
        "If the biography includes no explicit stat totals, return an empty "
        "stat_claims array. Do not include markdown, bullets, notes, analysis, or "
        "examples. The first character must be { and the last character must be }.",
        (
            "Resolved player identity from DuckDB:\n"
            f"- name: {player_name}\n"
            f"- player_id: {player_id}\n"
            f"- debut: {debut or 'unknown'}\n"
            f"- final_game: {final_game or 'unknown'}\n\n"
            f"Question: {question}\n"
            "Return the final compact JSON object now."
        ),
    )


def build_open_prompt(question: str) -> tuple[str, str]:
    """Render a prompt for ungrounded open prose from the LLM's own knowledge.

    Use for open prose questions that are not grounded database questions.
    The LLM should answer directly and honestly note if stats/data are involved.
    """
    return (
        "You are a knowledgeable baseball historian. Answer the question directly "
        "using your own knowledge.\n"
        "Do not include planning notes, internal monologue, or any structured reasoning markup "
        "(no lines starting with *, -, or bullet points) in your response.\n"
        "If the question asks for specific statistics or data from a database, "
        "say you don't have access to that information.",
        f"Question: {question}",
    )
