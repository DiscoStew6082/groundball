"""Shared parsing helpers for natural-language year mentions."""

import re


def extract_spelled_year(text: str) -> int | None:
    """Extract common spoken years such as ``nineteen twenty-five``."""
    normalized = text.lower().replace("-", " ")
    century_prefixes = {
        "eighteen": 1800,
        "nineteen": 1900,
        "twenty": 2000,
    }
    tens = {
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    units = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
    }
    digit_units = {"0": 0} | {str(value): value for value in units.values()}
    unit_tokens = units | digit_units
    teens = {
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
    }
    suffix_words = set(tens) | set(unit_tokens) | set(teens) | {"oh", "zero"}
    pattern = re.compile(
        rf"\b({'|'.join(century_prefixes)})\s+"
        rf"({'|'.join(suffix_words)})(?:\s+({'|'.join(unit_tokens)}))?\b"
    )
    for match in pattern.finditer(normalized):
        century = century_prefixes[match.group(1)]
        first = match.group(2)
        second = match.group(3)
        if first in digit_units and second in unit_tokens:
            return century + (digit_units[first] * 10) + unit_tokens[second]
        if first in {"oh", "zero"} and second is not None:
            return century + unit_tokens[second]
        if first in teens and second is None:
            return century + teens[first]
        if first in tens:
            return century + tens[first] + (unit_tokens.get(second or "", 0))
    return None
