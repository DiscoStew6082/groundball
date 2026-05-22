"""Corpus frontmatter helpers."""

from __future__ import annotations

GENERATED_PLAYER_PROFILE = "generated_player_profile"
PLAYER_BIOGRAPHY_CATEGORY = "player_biography"
STAT_DEFINITION_CATEGORY = "stat_definition"
HOF_BIO_CATEGORY = "hof_bio"
METADATA_CATEGORY = "category"
METADATA_DOC_KIND = "doc_kind"
METADATA_PLAYER_ID = "player_id"
METADATA_SOURCE_TABLES = "source_tables"
DEFAULT_PLAYER_SOURCE_TABLES = ["people", "batting", "pitching", "fielding"]


def generated_player_profile_frontmatter(player_id: str, title: str) -> list[str]:
    """Return YAML frontmatter lines for a generated player profile document."""
    lines = [
        "---",
        f"title: {title}",
        f"{METADATA_PLAYER_ID}: {player_id}",
        f"{METADATA_CATEGORY}: {PLAYER_BIOGRAPHY_CATEGORY}",
        f"{METADATA_DOC_KIND}: {GENERATED_PLAYER_PROFILE}",
        f"{METADATA_SOURCE_TABLES}:",
    ]
    lines.extend(f"  - {table}" for table in DEFAULT_PLAYER_SOURCE_TABLES)
    lines.append("---")
    return lines
