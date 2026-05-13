"""Tests for adapter-neutral query UI session policy."""

from baseball_rag.arch.tracing import PipelineTrace
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.request_execution import RequestExecution
from baseball_rag.ui.query_session import QuerySession


def _execution(answer: str, *, query: str = "what is OPS") -> RequestExecution:
    return RequestExecution(
        answer=StructuredAnswer(answer=answer, intent="general_explanation"),
        trace=PipelineTrace(query=query),
    )


def test_latest_query_wins_when_two_submissions_overlap():
    calls: list[str] = []

    def execute(question, *, conversation):
        calls.append(question)
        return _execution(f"answered {question}", query=question)

    session = QuerySession(
        execute=execute,
        default_question="who had the most RBIs in 1962",
    )

    first = session.begin("what is OPS", [], [], {}, session_key="browser-a")
    second = session.begin(
        "career home run leaders",
        [],
        [],
        first.registry,
        session_key="browser-a",
    )

    assert session.complete(first.begun, first.registry, session_key="browser-a") is None
    completed = session.complete(second.begun, second.registry, session_key="browser-a")

    assert completed is not None
    assert completed.update.answer_text == "answered career home run leaders"
    assert calls == ["career home run leaders"]


def test_query_session_scopes_latest_turns_by_browser_session():
    calls: list[str] = []

    def execute(question, *, conversation):
        calls.append(question)
        return _execution(f"answered {question}", query=question)

    session = QuerySession(
        execute=execute,
        default_question="who had the most RBIs in 1962",
    )

    first = session.begin("what is OPS", [], [], {}, session_key="browser-a")
    session.begin("career home run leaders", [], [], {}, session_key="browser-b")

    completed = session.complete(first.begun, first.registry, session_key="browser-a")

    assert completed is not None
    assert completed.update.answer_text == "answered what is OPS"
    assert calls == ["what is OPS"]


def test_query_session_records_completed_traces_once():
    recorded: list[PipelineTrace] = []

    def execute(question, *, conversation):
        return _execution(f"answered {question}", query=question)

    def record(execution):
        assert execution.trace is not None
        recorded.append(execution.trace)

    session = QuerySession(
        execute=execute,
        default_question="who had the most RBIs in 1962",
        record_execution=record,
    )

    begun = session.begin("what is OPS", [], [], {}, session_key="browser-a")
    completed = session.complete(begun.begun, begun.registry, session_key="browser-a")

    assert completed is not None
    assert completed.update.answer_text == "answered what is OPS"
    assert [trace.query for trace in recorded] == ["what is OPS"]


def test_query_session_empty_input_restores_default_without_executing():
    calls: list[str] = []
    session = QuerySession(
        execute=lambda question, *, conversation: calls.append(question),
        default_question="who had the most RBIs in 1962",
    )

    begun = session.begin(
        "   ",
        [{"role": "assistant", "content": "old"}],
        [{"question": "old", "answer": {}}],
        {},
        session_key="browser-a",
    )
    completed = session.complete(begun.begun, begun.registry, session_key="browser-a")

    assert begun.begun.pending is None
    assert completed is not None
    assert completed.update.question == "who had the most RBIs in 1962"
    assert completed.update.answer_text == ""
    assert calls == []
