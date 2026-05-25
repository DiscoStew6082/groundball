import pytest

from baseball_rag.ui.gradio_adapter import GradioQueryAdapter
from baseball_rag.ui.query_transaction import QueryUiUpdate


def test_gradio_adapter_maps_completed_query_update_to_query_tab_outputs():
    update = QueryUiUpdate(
        status="completed",
        chat_history=[{"role": "assistant", "content": "answer"}],
        question="what is OPS",
        answer_text="OPS is on-base plus slugging.",
        rows=[["row"]],
        sources=[{"label": "source"}],
        sql="select 1",
        visible_chat_history=[{"role": "assistant", "content": "answer"}],
        conversation=[{"question": "what is OPS", "answer": {}}],
    )

    outputs = GradioQueryAdapter().completed_outputs(update)

    assert outputs == (
        [{"role": "assistant", "content": "answer"}],
        "what is OPS",
        "OPS is on-base plus slugging.",
        [["row"]],
        [{"label": "source"}],
        "select 1",
        [{"role": "assistant", "content": "answer"}],
        [{"question": "what is OPS", "answer": {}}],
        {"interactive": True, "__type__": "update"},
    )


def test_gradio_adapter_maps_pending_and_stale_outputs():
    update = QueryUiUpdate(
        status="pending",
        chat_history=[],
        question="what is OPS",
        answer_text="",
        rows=[],
        sources=[],
        sql="",
        visible_chat_history=[],
        conversation=[],
    )
    adapter = GradioQueryAdapter()

    assert adapter.pending_outputs(
        update,
        begun="turn",
        registry={"latest_turn_id": "abc"},
        ask_interactive=False,
    ) == (
        "",
        [],
        [],
        "",
        "turn",
        {"latest_turn_id": "abc"},
        {"interactive": False, "__type__": "update"},
    )
    assert adapter.stale_outputs() == tuple({"__type__": "update"} for _ in range(9))


def test_gradio_adapter_builds_named_pending_output_payload():
    update = QueryUiUpdate(
        status="pending",
        chat_history=[{"role": "assistant", "content": "old"}],
        question="what is OPS",
        answer_text="",
        rows=[],
        sources=[],
        sql="",
        visible_chat_history=[{"role": "assistant", "content": "old"}],
        conversation=[{"question": "old", "answer": {}}],
    )
    adapter = GradioQueryAdapter()

    assert adapter.pending_named_outputs(
        update,
        begun="turn",
        registry={"latest_turn_id": "abc"},
        ask_interactive=False,
    ) == {
        "answer": "",
        "rows": [],
        "sources": [],
        "sql": "",
        "pending_query": "turn",
        "turn_registry": {"latest_turn_id": "abc"},
        "ask_button": {"interactive": False, "__type__": "update"},
    }


def test_gradio_adapter_builds_named_completed_output_payload():
    update = QueryUiUpdate(
        status="completed",
        chat_history=[{"role": "assistant", "content": "answer"}],
        question="what is OPS",
        answer_text="OPS is on-base plus slugging.",
        rows=[["row"]],
        sources=[{"label": "source"}],
        sql="select 1",
        visible_chat_history=[{"role": "assistant", "content": "answer"}],
        conversation=[{"question": "what is OPS", "answer": {}}],
    )
    adapter = GradioQueryAdapter()

    assert adapter.completed_named_outputs(update) == {
        "chat": [{"role": "assistant", "content": "answer"}],
        "question": "what is OPS",
        "answer": "OPS is on-base plus slugging.",
        "rows": [["row"]],
        "sources": [{"label": "source"}],
        "sql": "select 1",
        "chat_state": [{"role": "assistant", "content": "answer"}],
        "conversation_state": [{"question": "what is OPS", "answer": {}}],
        "ask_button": {"interactive": True, "__type__": "update"},
    }


def test_gradio_adapter_names_query_tab_outputs_for_dashboard_wiring():
    adapter = GradioQueryAdapter()

    assert adapter.pending_output_names == (
        "answer",
        "rows",
        "sources",
        "sql",
        "pending_query",
        "turn_registry",
        "ask_button",
    )
    assert adapter.completed_output_names == (
        "chat",
        "question",
        "answer",
        "rows",
        "sources",
        "sql",
        "chat_state",
        "conversation_state",
        "ask_button",
    )
    assert adapter.stale_output_names == adapter.completed_output_names


def test_gradio_adapter_maps_named_components_to_query_tab_output_order():
    adapter = GradioQueryAdapter()
    components = {name: object() for name in adapter.query_output_names}

    assert adapter.pending_components(components) == [
        components[name] for name in adapter.pending_output_names
    ]
    assert adapter.completed_components(components) == [
        components[name] for name in adapter.completed_output_names
    ]


def test_gradio_adapter_rejects_incomplete_query_tab_component_map():
    adapter = GradioQueryAdapter()
    components = {name: object() for name in adapter.query_output_names}
    components.pop("ask_button")

    with pytest.raises(KeyError, match="ask_button"):
        adapter.completed_components(components)
