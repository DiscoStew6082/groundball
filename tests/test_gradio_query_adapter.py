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
