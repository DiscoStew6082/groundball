import pytest

from baseball_rag.service import answer


def test_answer_surfaces_stats_only_answer_mode_metadata():
    result = answer("who had the most RBIs in 1962", answer_mode="stats_only")

    assert result.metadata["answer_mode"] == "stats_only"


def test_answer_rejects_unknown_answer_mode_before_dispatch():
    with pytest.raises(ValueError, match="Unsupported answer_mode"):
        answer(
            "who had the most RBIs in 1962",
            answer_mode="llm_flavored",  # type: ignore[arg-type]
        )
