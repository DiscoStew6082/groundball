"""Tests for inspectable routing decision evidence."""

import pytest

from baseball_rag.arch.tracing import finish_trace, start_trace
from baseball_rag.generation.llm import LLMResponse
from baseball_rag.routing import GroundedDatabaseQuestionCase, route, routed_case
from baseball_rag.routing.decisions import RouteDecisionChain, RouteDecisionStep


def test_decision_chain_preserves_route_and_records_step_evidence() -> None:
    selected = routed_case(intent="general_explanation", raw_question="what is OPS", stat="OPS")

    def fail_if_called():
        raise AssertionError("terminal route should not be called")

    chain = RouteDecisionChain(
        decisions=(
            RouteDecisionStep("first", lambda: None),
            RouteDecisionStep("second", lambda: selected),
        ),
        fallback=RouteDecisionStep("terminal", fail_if_called),
    )

    assert chain.decide() == selected

    outcome = chain.decide_with_evidence()

    assert outcome.route == selected
    assert outcome.winner == "second"
    assert [(step.step, step.matched, step.intent) for step in outcome.steps] == [
        ("first", False, None),
        ("second", True, "general_explanation"),
    ]


def test_router_evidence_keeps_deterministic_grounded_route_before_llm(monkeypatch) -> None:
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("LLM router should not be called")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

    from baseball_rag.routing import route_with_evidence

    question = "who won the Triple Crown and which years"
    outcome = route_with_evidence(question)

    assert isinstance(outcome.route, GroundedDatabaseQuestionCase)
    assert route(question) == outcome.route
    assert outcome.winner == "grounded_database"
    assert [(step.step, step.matched) for step in outcome.steps] == [
        ("player_bio_followup", False),
        ("claim_verification", False),
        ("player_bio_name", False),
        ("deterministic_stat_or_grounded", False),
        ("grounded_database", True),
    ]


def test_router_evidence_records_model_failure_reason(monkeypatch) -> None:
    def malformed_response(*_args, **_kwargs):
        return LLMResponse(content='["not", "a", "route"]', model="test", done=True)

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", malformed_response)

    from baseball_rag.routing import route_with_evidence

    outcome = route_with_evidence("tell me something interesting about baseball")

    assert outcome.route.intent == "general_explanation"
    assert outcome.winner == "llm_router_or_heuristic"
    assert outcome.fallback_reason is not None
    assert "not a JSON object" in outcome.fallback_reason


def test_router_evidence_keeps_model_success_separate_from_failure_reason(monkeypatch) -> None:
    def llm_response(*_args, **_kwargs):
        return LLMResponse(
            content=(
                '{"intent":"stat_query","stat":"RBI","time_period":null,'
                '"position":null,"player_name":"Hank Aaron"}'
            ),
            model="test",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", llm_response)

    from baseball_rag.routing import route_with_evidence

    outcome = route_with_evidence("compare this player across the middle years")

    assert outcome.route.intent == "stat_query"
    assert outcome.winner == "llm_router_or_heuristic"
    assert outcome.steps[-1].reason == "llm_router"
    assert outcome.fallback_reason is None


def test_route_trace_summary_includes_decision_winner() -> None:
    start_trace("who won the Triple Crown and which years")

    route("who won the Triple Crown and which years")
    trace = finish_trace(route_type="grounded_database_question")

    assert trace is not None
    router_stage = next(stage for stage in trace.stages if stage.component_id == "query-router")
    assert "grounded_database_question" in router_stage.output_summary
    assert "grounded_database" in router_stage.output_summary


def test_decision_chain_raises_when_terminal_route_declines() -> None:
    chain = RouteDecisionChain(
        decisions=(RouteDecisionStep("first", lambda: None),),
        fallback=RouteDecisionStep("terminal", lambda: None),
    )

    with pytest.raises(RuntimeError, match="terminal route returned no route"):
        chain.decide_with_evidence()
