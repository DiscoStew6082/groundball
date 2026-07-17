"""Browser-facing query contract smoke tests."""

from unittest.mock import patch

import requests

from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.web_app import build_dashboard


def test_default_query_clears_stale_panels_then_shows_final_answer():
    """The Query tab contract clears stale panels before publishing a new answer."""
    dashboard = build_dashboard()
    begin_fn = next(
        dependency.fn
        for dependency in dashboard.fns.values()
        if dependency.api_name == "begin_query"
    )
    query_fn = next(
        dependency.fn for dependency in dashboard.fns.values() if dependency.api_name == "on_query"
    )
    stale_chat = [{"role": "assistant", "content": "stale answer"}]
    stale_conversation = [{"question": "stale query", "answer": {"sources": []}}]
    turn_registry = {"latest_turn_id": None}

    answer, rows, sources, sql, begun, turn_registry, ask_button = begin_fn(
        "who had the most RBIs in 1962",
        stale_chat,
        stale_conversation,
        turn_registry,
    )

    assert answer == ""
    assert rows == []
    assert sources == []
    assert sql == ""
    assert begun.update.status == "pending"
    assert ask_button == {"interactive": False, "__type__": "update"}

    def fake_answer(question: str, **_kwargs):
        return StructuredAnswer(
            answer=f"fresh answer for {question}",
            intent="stat_query",
            sources=[
                SourceRecord(
                    type="duckdb",
                    label="Fresh RBI leaders",
                    sql="select fresh_result",
                    columns=["name", "stat_value"],
                    rows=[{"name": "Davis, Tommy", "stat_value": 153}],
                )
            ],
        )

    with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
        chat, textbox, answer, rows, sources, sql, chat_state, conversation, ask_button = query_fn(
            begun,
            turn_registry,
        )

    assert textbox == "who had the most RBIs in 1962"
    assert answer == "fresh answer for who had the most RBIs in 1962"
    assert "stale" not in answer
    assert rows["data"] == [["Davis, Tommy", 153]]
    assert sources[0]["label"] == "Fresh RBI leaders"
    assert sql == "select fresh_result"
    assert chat[-1]["content"] == "fresh answer for who had the most RBIs in 1962"
    assert chat_state == chat
    assert conversation[-1]["question"] == "who had the most RBIs in 1962"
    assert ask_button == {"interactive": True, "__type__": "update"}


def test_public_demo_callback_fails_closed_without_llm_request(monkeypatch):
    """Hosted Gradio callbacks reject LLM-only work through public mode."""
    monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")

    def deny_network(*_args, **_kwargs):
        raise AssertionError("public Gradio callback attempted outbound network access")

    monkeypatch.setattr(requests.sessions.Session, "request", deny_network)
    dashboard = build_dashboard()
    begin_fn = next(
        dependency.fn
        for dependency in dashboard.fns.values()
        if dependency.api_name == "begin_query"
    )
    query_fn = next(
        dependency.fn for dependency in dashboard.fns.values() if dependency.api_name == "on_query"
    )
    turn_registry = {"latest_turn_id": None}

    *_pending_outputs, begun, turn_registry, _ask_button = begin_fn(
        "who was Babe Ruth",
        [],
        [],
        turn_registry,
    )
    _chat, _textbox, answer, rows, sources, sql, _chat_state, conversation, ask_button = query_fn(
        begun, turn_registry
    )

    assert "disabled in the public demo" in answer
    assert rows == []
    assert sources == []
    assert sql == ""
    assert conversation[-1]["answer"]["intent"] == "player_biography"
    assert ask_button == {"interactive": True, "__type__": "update"}
