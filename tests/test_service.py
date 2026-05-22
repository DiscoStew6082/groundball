import pytest

from baseball_rag.generation.llm import LLMResponse, LLMUnavailableError
from baseball_rag.service import answer


def test_answer_surfaces_stats_only_answer_mode_metadata():
    result = answer("who had the most RBIs in 1962", answer_mode="stats_only")

    assert result.metadata["answer_mode"] == "stats_only"


def test_answer_rejects_unknown_answer_mode_before_dispatch():
    with pytest.raises(ValueError, match="Unsupported answer_mode"):
        answer(
            "who had the most RBIs in 1962",
            answer_mode="box_score_poetry",  # type: ignore[arg-type]
        )


def test_llm_flavored_stat_query_uses_verified_stats(monkeypatch):
    seen_prompts = []

    def fake_llm(prompt, **_kwargs):
        seen_prompts.append(prompt)
        return LLMResponse(
            content="Tommy Davis led MLB with 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert result.answer == "Tommy Davis led MLB with 153 RBI in 1962."
    assert result.metadata["answer_mode"] == "llm_flavored"
    assert result.sources[0].type == "duckdb"
    assert "Davis, Tommy" in str(seen_prompts[0])
    assert "153" in str(seen_prompts[0])


def test_llm_flavored_unsupported_answer_skips_final_narration(monkeypatch):
    def fail_narration(**_kwargs):
        raise AssertionError("unsupported answers must not call final narration")

    monkeypatch.setattr(
        "baseball_rag.service._llm_flavored_grounded_database_answer",
        fail_narration,
    )

    result = answer("who is in the 500 club", answer_mode="llm_flavored")

    assert result.unsupported is True
    assert result.unsupported_reason == "ambiguous"
    assert result.metadata["answer_mode"] == "llm_flavored"


def test_llm_flavored_falls_back_to_stats_when_llm_unavailable(monkeypatch):
    def unavailable_llm(_prompt, **_kwargs):
        raise LLMUnavailableError("local LLM unavailable")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", unavailable_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "LLM unavailable" in result.answer
    assert result.metadata["answer_mode"] == "llm_flavored"
    assert result.sources[0].type == "duckdb"
