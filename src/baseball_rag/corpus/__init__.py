from pathlib import Path

STAT_DEFS_DIR = Path(__file__).parent / "stat_definitions"


def get_stat_defs() -> list[Path]:
    return list(STAT_DEFS_DIR.glob("*.md"))
