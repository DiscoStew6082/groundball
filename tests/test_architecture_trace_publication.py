from __future__ import annotations

import logging

from baseball_rag.arch.trace_publication import ArchitectureTracePublisher
from baseball_rag.arch.tracing import PipelineTrace
from baseball_rag.provenance import StructuredAnswer
from baseball_rag.request_execution import RequestExecution


def _execution(question: str = "what is OPS") -> RequestExecution:
    return RequestExecution(
        answer=StructuredAnswer(answer="answered", intent="general_explanation"),
        trace=PipelineTrace(query=question),
    )


class RecordingDiagram:
    def __init__(self) -> None:
        self.animated: list[str] = []
        self.recorded: list[tuple[str, str | None]] = []

    def animate_trace(self, trace: PipelineTrace) -> None:
        self.animated.append(trace.query)

    def record_execution(
        self,
        execution: RequestExecution,
        *,
        session_key: str | None = None,
    ) -> None:
        assert execution.trace is not None
        self.recorded.append((execution.trace.query, session_key))


def test_trace_publisher_records_execution_for_session_key():
    diagram = RecordingDiagram()

    ArchitectureTracePublisher(diagram, animate=False).publish(_execution(), "browser-a")

    assert diagram.recorded == [("what is OPS", "browser-a")]
    assert diagram.animated == []


def test_trace_publisher_uses_animation_mode():
    diagram = RecordingDiagram()

    ArchitectureTracePublisher(diagram, animate=True).publish(_execution("career HR leaders"), None)

    assert diagram.animated == ["career HR leaders"]
    assert diagram.recorded == []


def test_trace_publisher_logs_and_isolates_diagram_failures(caplog):
    class BrokenDiagram(RecordingDiagram):
        def record_execution(
            self,
            execution: RequestExecution,
            *,
            session_key: str | None = None,
        ) -> None:
            raise RuntimeError("diagram failed")

    caplog.set_level(logging.ERROR)

    ArchitectureTracePublisher(BrokenDiagram(), animate=False).publish(
        _execution("what is OPS"),
        "browser-a",
    )

    assert "Gradio diagram trace update failed for 'what is OPS'" in caplog.text
