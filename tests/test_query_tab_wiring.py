from __future__ import annotations

import gradio as gr

from baseball_rag.arch.tracing import PipelineTrace
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.request_execution import RequestExecution
from baseball_rag.ui.gradio_adapter import GradioQueryAdapter
from baseball_rag.ui.query_session import QuerySession
from baseball_rag.ui.query_tab_wiring import GradioQueryTabWiring, request_session_key


def _execution(question: str) -> RequestExecution:
    return RequestExecution(
        answer=StructuredAnswer(answer=f"answered {question}", intent="general_explanation"),
        trace=PipelineTrace(query=question),
    )


def test_query_tab_wiring_exposes_pending_and_completed_component_ids():
    adapter = GradioQueryAdapter()
    components = {name: gr.State(None) for name in adapter.query_output_names}
    wiring = GradioQueryTabWiring(
        session=QuerySession(
            execute=lambda question, *, conversation: _execution(question),
            default_question="default",
        ),
        adapter=adapter,
        components=components,
    )

    assert tuple(component._id for component in wiring.pending_components()) == tuple(
        components[name]._id for name in adapter.pending_output_names
    )
    assert tuple(component._id for component in wiring.completed_components()) == tuple(
        components[name]._id for name in adapter.completed_output_names
    )


def test_query_tab_wiring_uses_gradio_request_session_hash_for_turns_and_recording():
    recorded: list[str | None] = []
    wiring = GradioQueryTabWiring(
        session=QuerySession(
            execute=lambda question, *, conversation: _execution(question),
            default_question="default",
            record_execution=lambda execution, session_key: recorded.append(session_key),
        ),
        adapter=GradioQueryAdapter(),
        components={name: object() for name in GradioQueryAdapter().query_output_names},
    )
    request = gr.Request(None, {}, session_hash="browser-a")

    pending = wiring.begin("what is OPS", [], [], {}, request=request)
    completed = wiring.complete(pending[4], pending[5], request=request)

    assert pending[5]["session_key"] == "browser-a"
    assert completed[2] == "answered what is OPS"
    assert recorded == ["browser-a"]
    assert request_session_key(request) == "browser-a"


def test_query_tab_wiring_returns_stale_noops_without_executing_backend():
    calls: list[str] = []
    wiring = GradioQueryTabWiring(
        session=QuerySession(
            execute=lambda question, *, conversation: calls.append(question)
            or _execution(question),
            default_question="default",
        ),
        adapter=GradioQueryAdapter(),
        components={name: object() for name in GradioQueryAdapter().query_output_names},
    )

    first = wiring.begin(
        "what is OPS",
        [],
        [],
        {},
        request=gr.Request(None, {}, session_hash="browser-a"),
    )
    wiring.begin(
        "career home run leaders",
        [],
        [],
        first[5],
        request=gr.Request(None, {}, session_hash="browser-a"),
    )

    assert (
        wiring.complete(
            first[4],
            first[5],
            request=gr.Request(None, {}, session_hash="browser-a"),
        )
        == ({"__type__": "update"},) * 9
    )
    assert calls == []
