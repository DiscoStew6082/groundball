from baseball_rag.general_explanation import GeneralExplanationPolicy
from baseball_rag.generation.llm import LLMResponse


def test_general_explanation_policy_answers_local_stat_definition_without_llm():
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("local stat definitions must not call the LLM")

    policy = GeneralExplanationPolicy(make_request=fail_llm)

    result = policy.answer("what is OPS")

    assert result.intent == "general_explanation"
    assert result.answer.startswith("OPS means OPS.")
    assert result.sources[0].type == "stat_definition"
    assert result.sources[0].label == "Local stat definition: OPS"


def test_general_explanation_policy_preserves_llm_unavailable_for_open_explanations():
    def unavailable_llm(*_args, **_kwargs):
        raise ConnectionError("LM Studio is down")

    policy = GeneralExplanationPolicy(make_request=unavailable_llm)

    result = policy.answer("why do teams use a bullpen?")

    assert result.unsupported is True
    assert result.unsupported_reason == "llm_unavailable"
    assert "General explanation questions require the local LLM" in result.answer
    assert result.warnings == ["LM Studio is down"]


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

    result = policy.answer("why do teams use a bullpen?")

    assert result.answer == "Bullpens help teams match pitchers to late innings."
    assert result.sources == []
    assert calls[0][1] == {"max_tokens": 700}
