"""Gradio dashboard for Baseball RAG — Architecture Explorer + Query Interface.

Phase 4 of the Architecture Explorer plan:
- Tab "Query": ChatInterface with existing answer() functionality
- Tab "Architecture": Interactive architecture diagram that visualizes pipeline traces

The two tabs share state: each query in the Query tab produces a PipelineTrace
that is appended to the ArchitectureDiagram's trace history and animated.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import gradio as gr

from baseball_rag.request_execution import RequestExecution, execute_request
from baseball_rag.service import render_text

if TYPE_CHECKING:
    from baseball_rag.arch.diagram import ArchitectureDiagram


_TTL_ENV_VAR = "BASEBALL_RAG_WEB_APP_TTL_SECONDS"
_DEFAULT_SERVER_NAME = "0.0.0.0"
_DEFAULT_SERVER_PORT = 7860
_DEV_SERVER_NAME = "127.0.0.1"
_DEV_SERVER_PORT = 7861
_TTL_HARD_EXIT_GRACE_SECONDS = 5.0


# --------------------------------------------------------------------------
# Run All Tests — Phase 5: populate real test status badges in diagram
# --------------------------------------------------------------------------


@dataclass
class _TestResult:
    passed: int
    failed: int
    skipped: int = 0


def run_all_tests() -> _TestResult:
    """Run the full pytest suite and update component statuses in the registry.

    Parses ``pytest -q`` output to identify which test files covered which
    components, then sets TestStatus.PASS / FAIL on each DiagramComponent.
    Unmapped components (no known test file) get TestStatus.UNKNOWN.
    """
    from baseball_rag.arch.components import TestStatus, get_registry

    result = subprocess.run(
        ["uv", "run", "pytest", "-q", "--tb=no"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    output = result.stdout + result.stderr

    # Parse pytest -q summary line: handles "153 passed" and "150 passed, 3 failed"
    # The numbers always appear BEFORE their labels
    passed = failed = skipped = 0
    for line in output.splitlines():
        m = re.search(r"(\d+)\s+passed", line)
        if m:
            passed = int(m.group(1))
        m = re.search(r"(\d+)\s+failed", line)
        if m:
            failed = int(m.group(1))
        m = re.search(r"(\d+)\s+skipped", line)
        if m:
            skipped = int(m.group(1))

    # Map component ids to their test file globs
    component_test_map: dict[str, list[str]] = {
        "cli": ["tests/test_cli_player_query.py"],
        "query-router": [
            "tests/test_router.py",
            "tests/test_router_player_detection.py",
            "tests/test_router_this_year.py",
        ],
        "chroma-store": ["tests/test_chroma_store.py"],
        "duckdb": ["tests/test_queries.py"],
        "llm": ["tests/test_llm.py", "tests/test_generation.py"],
        "prompt": ["tests/test_prompts.py"],
    }

    registry = get_registry()
    overall_pass = failed == 0

    for comp_id in component_test_map:
        if overall_pass:
            status = TestStatus.PASS
        else:
            status = TestStatus.FAIL
        registry.set_test_status(comp_id, status)

    # Set UNKNOWN for components without test file mappings
    mapped_ids = set(component_test_map.keys())
    for comp in registry.all():
        if comp.id not in mapped_ids:
            registry.set_test_status(comp.id, TestStatus.UNKNOWN)

    return _TestResult(passed=passed, failed=failed, skipped=skipped)


# --------------------------------------------------------------------------
# Internal trace helper (avoids circular imports)
# --------------------------------------------------------------------------

_anim_lock = threading.Lock()

_EXAMPLE_QUESTIONS = (
    "who had the most RBIs in 1962",
    "career home run leaders",
    "who was Babe Ruth",
    "what is OPS",
    "who played for the Braves in 1936",
)
_DEFAULT_QUESTION = _EXAMPLE_QUESTIONS[0]


def _animate_execution(diagram: "ArchitectureDiagram", execution: RequestExecution) -> None:
    """Animate the diagram with the trace from a completed request."""
    trace = execution.trace
    if trace is not None and hasattr(diagram, "animate_trace"):
        with _anim_lock:
            diagram.animate_trace(trace)


def _execute_for_gradio(
    query: str,
    *,
    diagram: "ArchitectureDiagram | None" = None,
    conversation: list[dict[str, Any]] | None = None,
) -> RequestExecution:
    """Run one Gradio request and optionally animate its trace."""
    execution = execute_request(
        query,
        adapter_component_id="gradio",
        adapter_label="Gradio Query",
        conversation=conversation,
    )
    if diagram is not None:
        _animate_execution(diagram, execution)
    return execution


# --------------------------------------------------------------------------
# Respond wrapper (wired to tracing + animation)
# --------------------------------------------------------------------------


def respond(
    message: str, history: list[list[str]], *, diagram: "ArchitectureDiagram | None" = None
) -> str:
    """Handle a single user message.

    When *diagram* is provided the query is traced and animated through the
    Architecture Explorer.  Otherwise falls back to plain answer().
    """
    return render_text(_execute_for_gradio(message, diagram=diagram).answer)


def respond_structured(message: str, *, diagram: "ArchitectureDiagram | None" = None):
    """Return answer text, evidence rows, source metadata, and SQL for Gradio."""
    result = _execute_for_gradio(message, diagram=diagram).answer
    return _display_payload(result)


def respond_conversation(
    message: str | None,
    chat_history: list[dict[str, str]] | None,
    conversation: list[dict[str, Any]] | None,
    *,
    diagram: "ArchitectureDiagram | None" = None,
):
    """Handle a conversational Gradio turn and retain structured prior context."""
    chat_history = list(chat_history or [])
    conversation = list(conversation or [])
    message = (message or "").strip()
    if not message:
        return chat_history, _DEFAULT_QUESTION, "", [], [], "", chat_history, conversation

    execution = _execute_for_gradio(message, diagram=diagram, conversation=conversation)
    result = execution.answer
    chat_history.extend(
        [
            {"role": "user", "content": message},
            {"role": "assistant", "content": render_text(result)},
        ]
    )
    conversation.append(_conversation_turn(message, result))
    answer_text, rows, sources, sql = _display_payload(result)
    return (
        chat_history,
        message,
        answer_text,
        rows,
        sources,
        sql,
        chat_history,
        conversation,
    )


def _conversation_turn(question: str, result) -> dict[str, Any]:
    """Store only the answer fields needed to resolve future follow-ups."""
    payload = result.to_dict()
    metadata = payload.get("metadata") or {}
    answer_payload = {
        "answer": payload.get("answer"),
        "intent": payload.get("intent"),
        "metadata": {
            key: metadata[key]
            for key in (
                "original_question",
                "context_question",
                "context_source",
                "context_player_name",
            )
            if key in metadata
        },
        "sources": [_conversation_source(source) for source in payload.get("sources", [])],
    }
    return {"question": question, "answer": answer_payload}


def _conversation_source(source: dict[str, Any]) -> dict[str, Any]:
    rows = source.get("rows") or []
    compact_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        compact_row = {
            key: row[key]
            for key in ("name", "player_name", "full_name", "year", "team", "stat_value")
            if key in row
        }
        if compact_row:
            compact_rows.append(compact_row)
    return {
        "type": source.get("type"),
        "label": source.get("label"),
        "rows": compact_rows,
    }


def _display_payload(result):
    """Return answer text, table rows, source metadata, and SQL for Gradio panels."""
    payload = result.to_dict()
    sources = _json_safe_for_gradio(payload["sources"])
    primary_source = sources[0] if sources else {}
    rows = _rows_for_dataframe(primary_source)
    sql = primary_source.get("sql") or ""
    return payload["answer"], rows, sources, sql


def _json_safe_for_gradio(value: Any) -> Any:
    """Avoid file-shaped JSON objects that Gradio tries to download."""
    if isinstance(value, list):
        return [_json_safe_for_gradio(item) for item in value]
    if isinstance(value, dict):
        return {
            ("file_path" if key == "path" else key): _json_safe_for_gradio(item)
            for key, item in value.items()
        }
    return value


def _rows_for_dataframe(source: dict[str, Any]) -> list[Any] | dict[str, list[Any]]:
    """Return source rows in a shape Gradio Dataframe renders as scalar cells."""
    rows = source.get("rows") or []
    if not rows or not all(isinstance(row, dict) for row in rows):
        return rows

    columns = source.get("columns") or list(rows[0])
    return {
        "headers": columns,
        "data": [[row.get(column) for column in columns] for row in rows],
    }


# --------------------------------------------------------------------------
# Dashboard builder
# --------------------------------------------------------------------------


def build_dashboard() -> gr.Blocks:
    """Return a two-tab gr.Blocks: Query + Architecture Explorer."""
    from baseball_rag.arch.components import get_registry

    # Import here to avoid circular imports at module level
    from baseball_rag.arch.diagram import ArchitectureDiagram

    arch_diagram = ArchitectureDiagram(registry=get_registry())

    dashboard = gr.Blocks(title="Baseball RAG — Architecture Explorer")

    with dashboard:
        gr.Markdown("## ⚾ Baseball RAG — Query Engine & Architecture Explorer")

        with gr.Tab("Query"):
            chat_state = gr.State([])
            conversation_state = gr.State([])
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

            def on_query(msg, chat_history, conversation):
                return respond_conversation(
                    msg,
                    chat_history,
                    conversation,
                    diagram=arch_diagram,
                )

            gr.on(
                triggers=[submit.click, question.submit],
                fn=on_query,
                inputs=[question, chat_state, conversation_state],
                outputs=[
                    chat,
                    question,
                    answer_box,
                    table,
                    sources,
                    sql,
                    chat_state,
                    conversation_state,
                ],
                trigger_mode="once",
                show_progress="hidden",
                concurrency_limit=1,
                concurrency_id="query",
            )

        with gr.Tab("Architecture"):
            gr.Markdown(
                "**Pipeline Explorer** — click any component to inspect its source. "
                "After running a query in the **Query** tab, switch here to see it animate."
            )
            arch_diagram.render()

            # Run All Tests button (Phase 5) — added directly inside this
            # with-gr.Tab block so btn.click() has an active Blocks context.
            run_all_tests_btn = gr.Button(
                "\U0001f3c1 Run All Tests",
                elem_id="run-all-tests",
                size="sm",
            )

            def on_run_all_tests():
                run_all_tests()
                arch_diagram._update_diagram()
                return arch_diagram.diagram_html.value

            run_all_tests_btn.click(
                fn=on_run_all_tests,
                inputs=[],
                outputs=[arch_diagram.diagram_html],
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


def _main_with_defaults(
    argv: list[str] | None,
    *,
    default_server_name: str,
    default_server_port: int,
    default_ttl_seconds: str | None,
) -> None:
    """Run the web app CLI with caller-provided defaults."""
    parser = argparse.ArgumentParser(description="Launch the Baseball RAG Gradio dashboard.")
    parser.add_argument("--server-name", default=default_server_name)
    parser.add_argument("--server-port", default=default_server_port, type=int)
    parser.add_argument(
        "--ttl-seconds",
        default=None,
        help=(
            "Optional process time to live in seconds. "
            f"May also be set with {_TTL_ENV_VAR}. Use 0 to disable."
        ),
    )
    args = parser.parse_args(argv)
    raw_ttl = (
        args.ttl_seconds
        if args.ttl_seconds is not None
        else os.environ.get(_TTL_ENV_VAR, default_ttl_seconds)
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
