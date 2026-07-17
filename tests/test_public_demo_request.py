"""Public deterministic demo request behavior."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from baseball_rag.provenance import StructuredAnswer
from baseball_rag.request_execution import execute_public_demo_request


def _deny_network(*_args, **_kwargs):
    raise AssertionError("public demo request attempted outbound network access")


def test_public_demo_default_query_uses_grounded_data_without_network(monkeypatch):
    """The hosted public seam answers the default query without any outbound request."""
    monkeypatch.setattr(requests.sessions.Session, "request", _deny_network)

    execution = execute_public_demo_request("who had the most RBIs in 1962")

    answer = execution.answer
    assert answer.unsupported is False
    assert answer.intent == "stat_query"
    assert "Davis, Tommy: 153 RBI" in answer.answer
    assert answer.sources[0].type == "duckdb"
    assert answer.sources[0].rows[0]["name"] == "Davis, Tommy"
    assert answer.sources[0].rows[0]["stat_value"] == 153
    assert answer.sources[0].sql
    assert answer.metadata["answer_mode"] == "stats_only"
    assert answer.metadata["public_demo"] is True
    assert answer.metadata["llm_access"] == "disabled"


def test_public_demo_biography_fails_closed_without_network(monkeypatch):
    """An LLM-dependent biography is rejected before model or Mac access."""
    monkeypatch.setattr(requests.sessions.Session, "request", _deny_network)

    execution = execute_public_demo_request("who was Babe Ruth")

    answer = execution.answer
    assert answer.unsupported is True
    assert answer.unsupported_reason == "llm_unavailable"
    assert answer.intent == "player_biography"
    assert "public demo" in answer.answer.lower()
    assert "deterministic" in answer.answer.lower()
    assert answer.sources == []
    assert answer.metadata["public_demo"] is True
    assert answer.metadata["llm_access"] == "disabled"


def test_public_demo_unmatched_question_fails_closed_before_llm_routing(monkeypatch):
    """An unmatched question never reaches the LLM-backed router in public mode."""
    monkeypatch.setattr(requests.sessions.Session, "request", _deny_network)

    execution = execute_public_demo_request("why do teams use a bullpen?")

    answer = execution.answer
    assert answer.unsupported is True
    assert answer.unsupported_reason == "llm_unavailable"
    assert answer.intent == "general_explanation"
    assert "public demo" in answer.answer.lower()
    assert answer.sources == []
    assert answer.metadata["public_demo"] is True
    assert answer.metadata["llm_access"] == "disabled"


def test_public_demo_deterministic_grounded_query_uses_no_network(monkeypatch):
    """A known grounded template remains available without model-backed planning."""
    monkeypatch.setattr(requests.sessions.Session, "request", _deny_network)

    execution = execute_public_demo_request("who won the Triple Crown and which years")

    answer = execution.answer
    assert answer.unsupported is False
    assert answer.intent == "grounded_database_question"
    assert "Triple Crown" in answer.answer
    assert answer.sources[0].type == "duckdb"
    assert answer.sources[0].sql
    assert answer.metadata["public_demo"] is True
    assert answer.metadata["llm_access"] == "disabled"


def test_public_demo_policy_rejection_uses_no_network(monkeypatch):
    """Existing unsupported policy remains visible before deterministic routing."""
    monkeypatch.setattr(requests.sessions.Session, "request", _deny_network)

    execution = execute_public_demo_request("what are today's betting odds?")

    answer = execution.answer
    assert answer.unsupported is True
    assert answer.unsupported_reason == "unsupported"
    assert answer.intent == "unsupported"
    assert answer.sources[0].label == "Unsupported question policy"
    assert answer.metadata["public_demo"] is True
    assert answer.metadata["llm_access"] == "disabled"


def test_public_demo_serializes_shared_duckdb_requests(monkeypatch):
    """Concurrent visitors cannot execute against the shared connection together."""
    counter_lock = threading.Lock()
    start = threading.Barrier(4)
    active = 0
    max_active = 0

    def instrumented_answer(question, **_kwargs):
        nonlocal active, max_active
        with counter_lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with counter_lock:
            active -= 1
        return StructuredAnswer(answer=question, intent="stat_query")

    monkeypatch.setattr(
        "baseball_rag.request_execution.answer_public_demo",
        instrumented_answer,
    )

    def execute(question):
        start.wait()
        return execute_public_demo_request(question)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(execute, ["one", "two", "three", "four"]))

    assert [result.answer.answer for result in results] == ["one", "two", "three", "four"]
    assert max_active == 1
