"""Gradio dashboard for Groundball query and architecture inspection."""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
from typing import TYPE_CHECKING, Any, Callable, Optional

import gradio as gr

from baseball_rag.arch.test_status import ArchitectureTestStatusResult as _TestResult
from baseball_rag.arch.test_status import collect_and_apply_test_status
from baseball_rag.arch.trace_publication import ArchitectureTracePublisher
from baseball_rag.request_execution import (
    RequestExecution,
    execute_public_demo_request,
    execute_request,
)
from baseball_rag.service import render_text
from baseball_rag.ui.gradio_adapter import GradioQueryAdapter
from baseball_rag.ui.presentation import AnswerPresenter
from baseball_rag.ui.query_session import QuerySession
from baseball_rag.ui.query_tab_wiring import GradioQueryTabWiring, request_session_key

if TYPE_CHECKING:
    from baseball_rag.arch.diagram import ArchitectureDiagram


_TTL_ENV_VAR = "GROUNDBALL_WEB_APP_TTL_SECONDS"
_LEGACY_TTL_ENV_VAR = "BASEBALL_RAG_WEB_APP_TTL_SECONDS"
_DEFAULT_SERVER_NAME = "0.0.0.0"
_DEFAULT_SERVER_PORT = 7860
_DEV_SERVER_NAME = "127.0.0.1"
_DEV_SERVER_PORT = 7861
_TTL_HARD_EXIT_GRACE_SECONDS = 5.0


# --------------------------------------------------------------------------
# Run All Tests — Phase 5: populate real test status badges in diagram
# --------------------------------------------------------------------------


def run_all_tests() -> _TestResult:
    """Run the full pytest suite and update component statuses in the registry.

    The Architecture test-status adapter owns pytest parsing and component
    mapping, while this function remains the dashboard button entry point.
    """
    from baseball_rag.arch.components import get_registry

    return collect_and_apply_test_status(get_registry())


# --------------------------------------------------------------------------
# Internal trace helper (avoids circular imports)
# --------------------------------------------------------------------------

_EXAMPLE_QUESTIONS = (
    "who had the most RBIs in 1962",
    "career home run leaders",
    "who was Babe Ruth",
    "what is OPS",
    "who played for the Braves in 1936",
)
_DEFAULT_QUESTION = _EXAMPLE_QUESTIONS[0]


def _execute_for_gradio(
    question: str,
    *,
    conversation: list[dict[str, Any]] | None = None,
) -> RequestExecution:
    """Run one Gradio request."""
    execute = execute_public_demo_request if _public_demo_enabled() else execute_request
    return execute(
        question,
        adapter_component_id="gradio",
        adapter_label="Gradio Query",
        conversation=conversation,
    )


def _public_demo_enabled() -> bool:
    return os.environ.get("GROUNDBALL_PUBLIC_DEMO", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _diagram_execution_recorder(
    diagram: "ArchitectureDiagram | None",
    *,
    animate_diagram: bool,
) -> Callable[[RequestExecution, str | None], None] | None:
    """Return the trace update policy for a UI session."""
    if diagram is None:
        return None
    return ArchitectureTracePublisher(diagram, animate=animate_diagram).publish


# --------------------------------------------------------------------------
# Respond wrappers (wired to tracing and Architecture history)
# --------------------------------------------------------------------------


def respond(
    message: str, history: list[list[str]], *, diagram: "ArchitectureDiagram | None" = None
) -> str:
    """Handle a single user message.

    When *diagram* is provided the query records an Architecture Explorer trace.
    """
    execution = _execute_for_gradio(message)
    recorder = _diagram_execution_recorder(diagram, animate_diagram=True)
    if recorder is not None:
        recorder(execution, None)
    return render_text(execution.answer)


def respond_structured(message: str, *, diagram: "ArchitectureDiagram | None" = None):
    """Return answer text, evidence rows, source metadata, and SQL for Gradio."""
    execution = _execute_for_gradio(message)
    recorder = _diagram_execution_recorder(diagram, animate_diagram=True)
    if recorder is not None:
        recorder(execution, None)
    result = execution.answer
    presentation = AnswerPresenter().present(result)
    return presentation.answer_text, presentation.rows, presentation.sources, presentation.sql


def respond_conversation(
    message: str | None,
    chat_history: list[dict[str, str]] | None,
    conversation: list[dict[str, Any]] | None,
    *,
    diagram: "ArchitectureDiagram | None" = None,
    animate_diagram: bool = True,
):
    """Handle a conversational Gradio turn and retain structured prior context."""
    session = QuerySession(
        execute=_execute_for_gradio,
        default_question=_DEFAULT_QUESTION,
        record_execution=_diagram_execution_recorder(diagram, animate_diagram=animate_diagram),
    )
    query_adapter = GradioQueryAdapter()
    begun = session.begin(message, chat_history, conversation, {}, session_key=None)
    completed = session.complete(begun.begun, begun.registry, session_key=None)
    if completed is None:
        return query_adapter.completed_outputs(begun.update)[:-1]
    return query_adapter.completed_outputs(completed.update)[:-1]


# --------------------------------------------------------------------------
# Dashboard builder
# --------------------------------------------------------------------------


def build_dashboard() -> gr.Blocks:
    """Return a two-tab gr.Blocks: Query + Architecture Explorer."""
    from baseball_rag.arch.components import get_registry

    # Import here to avoid circular imports at module level
    from baseball_rag.arch.diagram import ArchitectureDiagram

    arch_diagram = ArchitectureDiagram(registry=get_registry())

    dashboard = gr.Blocks(title="Groundball — Architecture Explorer")

    with dashboard:
        gr.Markdown("## ⚾ Groundball — Query Engine & Architecture Explorer")

        with gr.Tab("Query"):
            chat_state = gr.State([])
            conversation_state = gr.State([])
            query_turn_state = gr.State(None)
            query_turn_registry = gr.State({"latest_turn_id": None})
            chat = gr.Chatbot(label="Conversation", height=260)
            with gr.Row():
                question = gr.Textbox(
                    label="Question",
                    value=_DEFAULT_QUESTION,
                    placeholder=_DEFAULT_QUESTION,
                    scale=4,
                )
                submit = gr.Button("Ask", variant="primary", scale=1)

            with gr.Row():
                for example_question in _EXAMPLE_QUESTIONS:
                    example_button = gr.Button(example_question, size="sm")
                    example_button.click(
                        fn=None,
                        inputs=[],
                        outputs=[question],
                        js=f"() => {json.dumps(example_question)}",
                        queue=False,
                        show_progress="hidden",
                    )

            answer_box = gr.Textbox(label="Answer", lines=8)
            table = gr.Dataframe(label="Rows", interactive=False, wrap=True)
            sources = gr.JSON(label="Sources")
            sql = gr.Code(label="SQL", language="sql")

            query_session = QuerySession(
                execute=_execute_for_gradio,
                default_question=_DEFAULT_QUESTION,
                record_execution=_diagram_execution_recorder(
                    arch_diagram,
                    animate_diagram=False,
                ),
            )
            query_output_components = {
                "chat": chat,
                "question": question,
                "answer": answer_box,
                "rows": table,
                "sources": sources,
                "sql": sql,
                "pending_query": query_turn_state,
                "turn_registry": query_turn_registry,
                "chat_state": chat_state,
                "conversation_state": conversation_state,
                "ask_button": submit,
            }
            query_wiring = GradioQueryTabWiring(
                session=query_session,
                adapter=GradioQueryAdapter(),
                components=query_output_components,
            )
            dashboard.query_output_component_ids = query_wiring.component_ids()  # type: ignore[attr-defined]
            query_wiring.wire(
                submit=submit,
                question=question,
                chat_state=chat_state,
                conversation_state=conversation_state,
                query_turn_registry=query_turn_registry,
                query_turn_state=query_turn_state,
            )

        with gr.Tab("Architecture") as architecture_tab:
            gr.Markdown(
                "**Pipeline Explorer** — click any component to inspect its source. "
                "After running a query in the **Query** tab, switch here to see the latest path."
            )
            arch_diagram.render()

            def refresh_architecture_trace(request: Optional[gr.Request] = None):
                return arch_diagram.latest_trace_values(session_key=request_session_key(request))

            architecture_tab.select(
                fn=refresh_architecture_trace,
                inputs=[],
                outputs=[arch_diagram.diagram_html, arch_diagram.footer_html],
                show_progress="hidden",
                queue=False,
            )

            with gr.Accordion("Developer tools", open=False):
                run_all_tests_btn = gr.Button(
                    "\U0001f3c1 Run All Tests",
                    elem_id="run-all-tests",
                    size="sm",
                )
                run_all_tests_status = gr.Markdown("", elem_id="run-all-tests-status")

            def on_run_all_tests():
                result = run_all_tests()
                arch_diagram._update_diagram()
                status = (
                    f"Tests finished: {result.passed} passed, "
                    f"{result.failed} failed, {result.errors} errors, "
                    f"{result.skipped} skipped."
                )
                return arch_diagram.diagram_html.value, status

            run_all_tests_btn.click(
                fn=lambda: "Tests are running...",
                inputs=[],
                outputs=[run_all_tests_status],
                show_progress="hidden",
                queue=False,
            ).then(
                fn=on_run_all_tests,
                inputs=[],
                outputs=[arch_diagram.diagram_html, run_all_tests_status],
                show_progress="minimal",
            )

    # Attach for test access
    dashboard.arch_diagram = arch_diagram  # type: ignore[attr-defined]

    return dashboard


# --------------------------------------------------------------------------
# Default demo instance (used when running: python -m baseball_rag.web_app)
# --------------------------------------------------------------------------

demo = build_dashboard()


def _parse_ttl_seconds(raw: str | None) -> float | None:
    """Parse a server process TTL in seconds; ``None``/empty/zero disables it."""
    if raw is None or raw.strip() == "":
        return None

    try:
        ttl_seconds = float(raw)
    except ValueError as exc:
        raise ValueError("server TTL must be a number of seconds") from exc

    if not math.isfinite(ttl_seconds):
        raise ValueError("server TTL must be finite")
    if ttl_seconds < 0:
        raise ValueError("server TTL must be non-negative")
    if ttl_seconds == 0:
        return None
    return ttl_seconds


def _schedule_server_ttl(
    ttl_seconds: float | None,
    *,
    close_fn: Callable[[], object],
    exit_fn: Callable[[int], object] = os._exit,
    hard_exit_grace_seconds: float = _TTL_HARD_EXIT_GRACE_SECONDS,
) -> threading.Timer | None:
    """Schedule graceful server close with a hard-exit fallback."""
    if ttl_seconds is None:
        return None

    def close_then_force_exit() -> None:
        force_exit = threading.Timer(hard_exit_grace_seconds, lambda: exit_fn(0))
        force_exit.daemon = True
        force_exit.start()
        close_fn()

    timer = threading.Timer(ttl_seconds, close_then_force_exit)
    timer.daemon = True
    timer.start()
    return timer


def _launch_dashboard(
    *,
    server_name: str,
    server_port: int,
    ttl_seconds: float | None,
    exit_fn: Callable[[int], object] = os._exit,
) -> None:
    """Launch the module-level dashboard, optionally with a process TTL."""
    if ttl_seconds is not None:
        print(f"* Server TTL: closing after {ttl_seconds:g} seconds.")
        demo.launch(
            server_name=server_name,
            server_port=server_port,
            prevent_thread_lock=True,
        )
        _schedule_server_ttl(
            ttl_seconds,
            close_fn=lambda: demo.close(verbose=False),
            exit_fn=exit_fn,
        )
        demo.block_thread()
        return

    demo.launch(server_name=server_name, server_port=server_port)


def _configured_ttl(default_ttl_seconds: str | None) -> str | None:
    """Return the renamed TTL env value with legacy env-var fallback."""
    return os.environ.get(
        _TTL_ENV_VAR,
        os.environ.get(_LEGACY_TTL_ENV_VAR, default_ttl_seconds),
    )


def _main_with_defaults(
    argv: list[str] | None,
    *,
    default_server_name: str,
    default_server_port: int,
    default_ttl_seconds: str | None,
) -> None:
    """Run the web app CLI with caller-provided defaults."""
    parser = argparse.ArgumentParser(description="Launch the Groundball Gradio dashboard.")
    parser.add_argument("--server-name", default=default_server_name)
    parser.add_argument("--server-port", default=default_server_port, type=int)
    parser.add_argument(
        "--ttl-seconds",
        default=None,
        help=(
            "Optional process time to live in seconds. "
            f"May also be set with {_TTL_ENV_VAR}; {_LEGACY_TTL_ENV_VAR} is "
            "still accepted as a compatibility alias. Use 0 to disable."
        ),
    )
    args = parser.parse_args(argv)
    raw_ttl = (
        args.ttl_seconds if args.ttl_seconds is not None else _configured_ttl(default_ttl_seconds)
    )
    try:
        ttl_seconds = _parse_ttl_seconds(raw_ttl)
    except ValueError as exc:
        parser.error(str(exc))

    _launch_dashboard(
        server_name=args.server_name,
        server_port=args.server_port,
        ttl_seconds=ttl_seconds,
    )


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint for ``python -m baseball_rag.web_app``."""
    _main_with_defaults(
        argv,
        default_server_name=_DEFAULT_SERVER_NAME,
        default_server_port=_DEFAULT_SERVER_PORT,
        default_ttl_seconds=None,
    )


def dev_main(argv: list[str] | None = None) -> None:
    """Short local UI entrypoint that runs until the user exits it."""
    _main_with_defaults(
        argv,
        default_server_name=_DEV_SERVER_NAME,
        default_server_port=_DEV_SERVER_PORT,
        default_ttl_seconds=None,
    )


if __name__ == "__main__":
    main()
