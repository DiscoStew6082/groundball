from unittest.mock import patch

from baseball_rag.general_explanation import GeneralExplanationPolicy
from baseball_rag.generation.llm import LLMResponse
from baseball_rag.routing import GeneralExplanationCase


def test_general_explanation_policy_answers_local_stat_definition_without_llm():
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("local stat definitions must not call the LLM")

    policy = GeneralExplanationPolicy(make_request=fail_llm)

    result = policy.answer(GeneralExplanationCase(raw_question="what is OPS", stat="OPS"))

    assert result.intent == "general_explanation"
    assert result.answer.startswith("OPS means OPS.")
    assert result.sources[0].type == "corpus"
    assert result.sources[0].label == "Local stat definition: OPS"


def test_general_explanation_policy_preserves_llm_unavailable_for_open_explanations():
    def unavailable_llm(*_args, **_kwargs):
        raise ConnectionError("LM Studio is down")

    policy = GeneralExplanationPolicy(make_request=unavailable_llm)

    result = policy.answer(GeneralExplanationCase(raw_question="why do teams use a bullpen?"))

    assert result.unsupported is True
    assert result.unsupported_reason == "llm_unavailable"
    assert "General explanation questions require the local LLM" in result.answer
    assert result.warnings == ["LM Studio is down"]


def test_service_general_explanation_uses_policy_module(monkeypatch):
    seen_questions = []

    def fake_answer(self, decision, **_kwargs):
        seen_questions.append(decision.raw_question)
        from baseball_rag.provenance import StructuredAnswer

        return StructuredAnswer(answer="policy answer", intent=decision.intent)

    monkeypatch.setattr(GeneralExplanationPolicy, "answer", fake_answer)

    from baseball_rag.service import _answer_general

    result = _answer_general(
        "ignored",
        GeneralExplanationCase(raw_question="what is a sacrifice fly?"),
    )

    assert seen_questions == ["what is a sacrifice fly?"]
    assert result.answer == "policy answer"


def test_service_general_explanation_uses_routed_question_for_local_definition(monkeypatch):
    from baseball_rag.service import _answer_general

    def fail_llm(*_args, **_kwargs):
        raise AssertionError("local stat definition answers must not call the LLM")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

    result = _answer_general(
        "what is OPS",
        GeneralExplanationCase(raw_question="what is OPS", stat="OPS"),
    )

    assert result.sources[0].label == "Local stat definition: OPS"


def test_runtime_general_explanations_do_not_use_grounded_generation_helpers(monkeypatch):
    with patch("baseball_rag.generation.answer.answer") as grounded_answer:
        grounded_answer.side_effect = AssertionError("general explanations use policy answers")

        result = GeneralExplanationPolicy(make_request=lambda *_args, **_kwargs: None).answer(
            GeneralExplanationCase(raw_question="what is RBI", stat="RBI")
        )

    assert "run batted in" in result.answer.lower()


def test_general_explanation_policy_calls_open_llm_for_non_local_question():
    calls = []

    def fake_llm(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return LLMResponse(
            content="Bullpens help teams match pitchers to late innings.",
            model="m",
            done=True,
        )

    policy = GeneralExplanationPolicy(make_request=fake_llm)

    result = policy.answer(GeneralExplanationCase(raw_question="why do teams use a bullpen?"))

    assert result.answer == "Bullpens help teams match pitchers to late innings."
    assert result.sources == []
    assert calls[0][1] == {"max_tokens": 700}
