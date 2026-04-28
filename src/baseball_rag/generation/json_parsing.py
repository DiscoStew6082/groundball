"""Helpers for parsing JSON-ish LLM responses."""

import re


def strip_markdown_fence(text: str) -> str:
    """Remove a surrounding markdown code fence from text if present."""
    stripped = text.strip()
    match = re.match(r"^```[\w-]*\s*\n?(.*?)\n?```$", stripped, flags=re.DOTALL)
    if match:
        return match.group(1).strip()
    return stripped


def extract_json_blocks(text: str) -> list[tuple[int, int]]:
    """Find candidate JSON objects in text using balanced curly braces.

    Returns list of (start, end) positions for each {...} block found.
    Braces inside JSON strings are ignored.
    """
    blocks: list[tuple[int, int]] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False

    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = i
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                blocks.append((start, i + 1))
                start = -1

    return blocks
