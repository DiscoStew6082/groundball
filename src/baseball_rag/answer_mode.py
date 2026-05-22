"""Answer mode selection for grounded responses."""

from typing import Literal

AnswerMode = Literal["stats_only", "llm_flavored"]

_SUPPORTED_ANSWER_MODES: set[str] = {"llm_flavored", "stats_only"}


def validate_answer_mode(value: str) -> AnswerMode:
    """Return a supported answer mode or raise for unknown values."""
    if value == "stats_only":
        return "stats_only"
    if value == "llm_flavored":
        return "llm_flavored"
    supported = ", ".join(sorted(_SUPPORTED_ANSWER_MODES))
    raise ValueError(f"Unsupported answer_mode '{value}'. Supported values: {supported}.")
