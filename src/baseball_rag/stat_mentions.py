"""Context-aware stat mention vocabulary views."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

StatTableHint = Literal["batting", "pitching", "fielding"]

_STAT_NORMALIZATION_ALIASES: dict[str, str] = {
    "K": "SO",
    "STRIKEOUTS": "SO",
    "HITS": "H",
    "HOMER": "HR",
    "HOMERS": "HR",
    "HOME_RUNS": "HR",
    "RBI": "RBI",
    "RBIS": "RBI",
    "RUNS_BATTED_IN": "RBI",
    "RUN_BATTED_IN": "RBI",
    "BAT_AVG": "AVG",
    "BATTING_AVERAGE": "AVG",
    "ON_BASE_PLUS_SLUGGING": "OPS",
    "PUTOUT": "PO",
    "PUTOUTS": "PO",
    "STOLEN_BASE": "SB",
    "STOLEN_BASES": "SB",
    "WINS": "W",
    "LOSSES": "L",
}

_ROUTING_STAT_ALIASES: dict[str, str] = {
    "2b": "2B",
    "3b": "3B",
    "ab": "AB",
    "avg": "AVG",
    "bat avg": "AVG",
    "batting average": "AVG",
    "bb": "BB",
    "base on balls": "BB",
    "bases on balls": "BB",
    "era": "ERA",
    "earned run average": "ERA",
    "h": "H",
    "hits": "H",
    "home run": "HR",
    "home runs": "HR",
    "homer": "HR",
    "homers": "HR",
    "hr": "HR",
    "hrs": "HR",
    "k": "SO",
    "losses": "L",
    "on-base plus slugging": "OPS",
    "ops": "OPS",
    "po": "PO",
    "putout": "PO",
    "putouts": "PO",
    "rbi": "RBI",
    "rbis": "RBI",
    "run batted in": "RBI",
    "runs": "R",
    "runs batted in": "RBI",
    "sb": "SB",
    "so": "SO",
    "stolen base": "SB",
    "stolen bases": "SB",
    "strikeouts": "SO",
    "whip": "WHIP",
    "wins": "W",
}

_BIOGRAPHY_CLAIM_STAT_ALIASES: dict[str, str] = {
    "AVG": "AVG",
    "batting average": "AVG",
    "ERA": "ERA",
    "H": "H",
    "hit": "H",
    "hits": "H",
    "home run": "HR",
    "home runs": "HR",
    "HR": "HR",
    "HRS": "HR",
    "OPS": "OPS",
    "PO": "PO",
    "putout": "PO",
    "putouts": "PO",
    "RBI": "RBI",
    "RBIs": "RBI",
    "runs batted in": "RBI",
    "SB": "SB",
    "SO": "SO",
    "stolen base": "SB",
    "stolen bases": "SB",
    "strikeout": "SO",
    "strikeouts": "SO",
    "W": "W",
    "WHIP": "WHIP",
    "win": "W",
    "wins": "W",
}

_SUPPORTED_BIOGRAPHY_CLAIM_STATS = (
    "H",
    "HR",
    "RBI",
    "SB",
    "AVG",
    "OPS",
    "W",
    "ERA",
    "WHIP",
    "SO",
    "PO",
)

_NARRATION_STAT_UNIT_ALIASES = {
    "2b": "2B",
    "3b": "3B",
    "ab": "AB",
    "at bat": "AB",
    "at bats": "AB",
    "avg": "AVG",
    "base on balls": "BB",
    "bases on balls": "BB",
    "bat avg": "AVG",
    "batting average": "AVG",
    "bb": "BB",
    "double": "2B",
    "doubles": "2B",
    "earned run average": "ERA",
    "era": "ERA",
    "g": "G",
    "game": "G",
    "game started": "GS",
    "games": "G",
    "games started": "GS",
    "gs": "GS",
    "h": "H",
    "hit": "H",
    "hits": "H",
    "home run": "HR",
    "home runs": "HR",
    "homer": "HR",
    "homers": "HR",
    "hr": "HR",
    "hrs": "HR",
    "k": "SO",
    "ks": "SO",
    "l": "L",
    "loss": "L",
    "losses": "L",
    "on-base plus slugging": "OPS",
    "ops": "OPS",
    "po": "PO",
    "putout": "PO",
    "putouts": "PO",
    "r": "R",
    "rbi": "RBI",
    "rbis": "RBI",
    "run": "R",
    "run batted in": "RBI",
    "runs": "R",
    "runs batted in": "RBI",
    "save": "SV",
    "saves": "SV",
    "sb": "SB",
    "so": "SO",
    "start": "GS",
    "starts": "GS",
    "stolen base": "SB",
    "stolen bases": "SB",
    "strike out": "SO",
    "strike outs": "SO",
    "strikeout": "SO",
    "strikeouts": "SO",
    "sv": "SV",
    "triple": "3B",
    "triples": "3B",
    "w": "W",
    "walk": "BB",
    "walks": "BB",
    "whip": "WHIP",
    "win": "W",
    "wins": "W",
}

_STAT_DEFINITION_DOC_IDS: dict[str, str] = {
    "2b": "2B",
    "2bs": "2B",
    "avg": "AVG",
    "batting average": "AVG",
    "bb": "BB",
    "bbs": "BB",
    "base on balls": "BB",
    "era": "ERA",
    "earned run average": "ERA",
    "hr": "HR",
    "hrs": "HR",
    "home run": "HR",
    "home runs": "HR",
    "ops": "OPS",
    "on-base plus slugging": "OPS",
    "po": "PO",
    "pos": "PO",
    "putout": "PO",
    "putouts": "PO",
    "rbi": "RBI",
    "rbis": "RBI",
    "run batted in": "RBI",
    "runs batted in": "RBI",
    "sb": "SB",
    "sbs": "SB",
    "stolen base": "SB",
    "stolen bases": "SB",
    "whip": "WHIP",
    "whips": "WHIP",
}

_PITCHING_SO_TERMS = (
    "as a pitcher",
    "batters",
    "on the mound",
    "pitched",
    "pitcher",
    "pitching",
)
_BATTING_SO_TERMS = (
    "as a batter",
    "as a hitter",
    "at the plate",
    "batting strikeout",
    "batting strikeouts",
)


@dataclass(frozen=True)
class StatMentionVocabulary:
    """Aliases and ambiguity policy for one stat-mention context."""

    context: str
    aliases: Mapping[str, str]
    supported_stats: tuple[str, ...] = ()

    def normalize(self, stat: str) -> str:
        """Normalize a stat token through this context and shared stat spellings."""
        raw = stat.strip()
        exact = self.aliases.get(raw)
        if exact is not None:
            return exact
        folded = raw.casefold()
        for alias, canonical in self.aliases.items():
            if alias.casefold() == folded:
                return canonical
        key = raw.upper().replace(" ", "_").replace("-", "_")
        return _STAT_NORMALIZATION_ALIASES.get(key, key)

    def find_stat(self, text: str) -> str | None:
        """Return the first stat alias mentioned in free text for this context."""
        matches = self.find_stats(text)
        return matches[0] if matches else None

    def find_stats(self, text: str) -> list[str]:
        """Return deduplicated stat aliases mentioned in free text for this context."""
        lower_text = text.lower()
        matches: list[tuple[int, int, str]] = []
        for phrase, canonical in self.aliases.items():
            pattern = rf"(?<![a-z0-9]){re.escape(phrase.lower())}(?![a-z0-9])"
            for match in re.finditer(pattern, lower_text):
                matches.append((match.start(), -len(phrase), canonical))

        stats: list[str] = []
        for _start, _length, canonical in sorted(matches):
            if canonical not in stats:
                stats.append(canonical)
        return stats

    def infer_table(self, stat: str, *, text: str | None = None) -> StatTableHint | None:
        """Infer contextual table meaning for ambiguous stat mentions."""
        return infer_stat_table_hint(self.normalize(stat), text=text)

    def regex_source(self) -> str:
        """Return a regex alternation for this context's aliases."""
        return "|".join(re.escape(alias) for alias in sorted(self.aliases, key=len, reverse=True))


def infer_stat_table_hint(stat: str, *, text: str | None = None) -> StatTableHint | None:
    """Infer the table intended by an ambiguous canonical stat mention."""
    key = stat.strip().upper().replace(" ", "_").replace("-", "_")
    canonical = _STAT_NORMALIZATION_ALIASES.get(key, key)
    if canonical != "SO" or not text:
        return None
    normalized_text = text.casefold()
    if any(term in normalized_text for term in _BATTING_SO_TERMS):
        return "batting"
    if any(term in normalized_text for term in _PITCHING_SO_TERMS):
        return "pitching"
    return None


def stat_normalization_aliases() -> Mapping[str, str]:
    return MappingProxyType(dict(_STAT_NORMALIZATION_ALIASES))


def for_routing() -> StatMentionVocabulary:
    return _vocabulary("routing", _ROUTING_STAT_ALIASES)


def for_biography_claims() -> StatMentionVocabulary:
    return _vocabulary(
        "biography_claims",
        _BIOGRAPHY_CLAIM_STAT_ALIASES,
        supported_stats=_SUPPORTED_BIOGRAPHY_CLAIM_STATS,
    )


def for_narration_verification() -> StatMentionVocabulary:
    return _vocabulary("narration_verification", _NARRATION_STAT_UNIT_ALIASES)


def for_stat_definition_lookup() -> StatMentionVocabulary:
    return _vocabulary("stat_definition_lookup", _STAT_DEFINITION_DOC_IDS)


def _vocabulary(
    context: str,
    aliases: Mapping[str, str],
    *,
    supported_stats: tuple[str, ...] | None = None,
) -> StatMentionVocabulary:
    stats = supported_stats if supported_stats is not None else tuple(sorted(set(aliases.values())))
    return StatMentionVocabulary(
        context=context,
        aliases=MappingProxyType(dict(aliases)),
        supported_stats=stats,
    )
