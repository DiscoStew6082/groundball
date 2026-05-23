"""Tests for Dashboard integration — Phase 4.

Replaces web_app.py ChatInterface with a tabbed dashboard:
- Tab "Query": existing Q&A functionality (ChatInterface)
- Tab "Architecture": ArchitectureDiagram with full pipeline visualization

The dashboard wires the Query tab's answer() calls through the tracing
instrumentation so the Architecture Explorer shows every query execution.
"""

from unittest.mock import patch

import gradio as gr

from baseball_rag.arch.diagram import ArchitectureDiagram
from baseball_rag.provenance import SourceRecord, StructuredAnswer

# --------------------------------------------------------------------------
# Phase 4.1 — Dashboard structure
# --------------------------------------------------------------------------


class TestDashboardTabs:
    """Dashboard must expose two tabs: Query and Architecture."""

    def setup_method(self):
        from baseball_rag.web_app import build_dashboard

        self.dash = build_dashboard()

    def test_dashboard_has_query_and_arch_components(self):
        """Dashboard exposes arch_diagram and a respond function."""
        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        # Dashboard is a gr.Blocks with an attached arch_diagram
        assert hasattr(dash, "arch_diagram")
        # The diagram has the expected interface
        diag = dash.arch_diagram
        assert hasattr(diag, "registry")
        assert hasattr(diag, "animate_trace")

    def test_query_tab_uses_chat_interface(self):
        """Query tab contains a ChatInterface-compatible respond function."""
        from baseball_rag.web_app import respond

        result = respond("who had the most RBIs in 1962", [])
        assert isinstance(result, str)
        assert len(result) > 0

    def test_architecture_tab_has_diagram(self):
        """Architecture tab exposes an ArchitectureDiagram instance."""
        diagram = getattr(self.dash, "arch_diagram", None)
        assert diagram is not None
        # Check it has the expected registry-based structure
        assert hasattr(diagram, "registry")
        assert hasattr(diagram, "highlight")
        assert hasattr(diagram, "animate_trace")

    def test_query_examples_use_plain_buttons(self):
        """Query examples render as buttons without the Dataset examples widget."""
        config = self.dash.get_config_file()
        component_types = {component["type"] for component in config["components"]}
        button_values = {
            component.get("props", {}).get("value")
            for component in config["components"]
            if component["type"] == "button"
        }

        assert "dataset" not in component_types
        assert "who had the most RBIs in 1962" in button_values
        assert "what is OPS" in button_values

    def test_query_examples_fill_question_client_side(self):
        """Example question buttons fill the textbox without backend progress."""
        config = self.dash.get_config_file()
        question_component = next(
            component
            for component in config["components"]
            if component["type"] == "textbox"
            and component.get("props", {}).get("label") == "Question"
        )
        example_dependencies = [
            dependency
            for dependency in config["dependencies"]
            if dependency.get("outputs") == [question_component["id"]]
        ]

        assert len(example_dependencies) == 5
        assert all(dependency["backend_fn"] is False for dependency in example_dependencies)
        assert all(dependency["js"] for dependency in example_dependencies)
        assert all(dependency["show_progress"] == "hidden" for dependency in example_dependencies)

    def test_architecture_refresh_is_not_queued(self):
        """Switching to Architecture should not start a queued progress timer."""
        config = self.dash.get_config_file()
        dependency = next(
            dependency
            for dependency in config["dependencies"]
            if dependency["api_name"] == "refresh_architecture_trace"
        )

        assert dependency["queue"] is False
        assert dependency["show_progress"] == "hidden"

    def test_architecture_component_selection_is_not_queued(self):
        """Clicking Architecture components should not start a queued progress timer."""
        config = self.dash.get_config_file()
        dependency = next(
            dependency
            for dependency in config["dependencies"]
            if dependency["api_name"] == "handle_js_select"
        )

        assert dependency["queue"] is False
        assert dependency["show_progress"] == "hidden"

    def test_run_all_tests_lives_in_collapsed_developer_drawer(self):
        """Long-running Architecture tooling is available but not the main experience."""
        config = self.dash.get_config_file()
        accordions = [
            component for component in config["components"] if component["type"] == "accordion"
        ]
        developer_drawers = [
            component
            for component in accordions
            if "Developer" in component.get("props", {}).get("label", "")
        ]
        run_button = next(
            component
            for component in config["components"]
            if component.get("props", {}).get("elem_id") == "run-all-tests"
        )

        assert developer_drawers
        assert developer_drawers[0]["props"]["open"] is False
        assert run_button["props"]["value"] == "\U0001f3c1 Run All Tests"

    def test_architecture_tab_copy_does_not_mention_animation(self):
        """Architecture copy describes latest traces without stale animation language."""
        config = self.dash.get_config_file()
        markdown_values = [
            component.get("props", {}).get("value", "")
            for component in config["components"]
            if component["type"] == "markdown"
        ]
        architecture_copy = "\n".join(markdown_values)

        assert "animate" not in architecture_copy.lower()
        assert "chroma" not in architecture_copy.lower()
        assert "corpus" not in architecture_copy.lower()

    def test_query_textbox_starts_with_clickable_default_question(self):
        """The first Ask click should run the visible default question."""
        config = self.dash.get_config_file()
        question_component = next(
            component
            for component in config["components"]
            if component["type"] == "textbox"
            and component.get("props", {}).get("label") == "Question"
        )

        assert question_component["props"]["value"] == "who had the most RBIs in 1962"

    def test_query_events_do_not_read_visible_chatbot(self):
        """Ask handlers keep rendered chat output out of the event input graph."""
        config = self.dash.get_config_file()
        components = config["components"]
        component_types = {component["id"]: component["type"] for component in components}
        chatbot_id = next(
            component["id"] for component in components if component["type"] == "chatbot"
        )
        question_id = next(
            component["id"]
            for component in components
            if component["type"] == "textbox"
            and component.get("props", {}).get("label") == "Question"
        )
        begin_dependency = next(
            dependency
            for dependency in config["dependencies"]
            if dependency["api_name"] == "begin_query"
        )
        query_dependency = next(
            dependency
            for dependency in config["dependencies"]
            if dependency["api_name"] == "on_query"
        )

        assert query_dependency["queue"] is False
        assert question_id in begin_dependency["inputs"]
        assert chatbot_id not in begin_dependency["inputs"]
        assert chatbot_id not in query_dependency["inputs"]
        assert chatbot_id in query_dependency["outputs"]
        state_inputs = [
            component_id
            for component_id in query_dependency["inputs"]
            if component_types[component_id] == "state"
        ]
        assert len(state_inputs) == 2

    def test_query_adapter_clears_then_completes_transaction(self):
        """The dashboard adapter exposes the query transaction pending/completed contract."""
        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )

        def fake_answer(question: str, **_kwargs):
            return StructuredAnswer(answer=f"answered {question}", intent="general_explanation")

        turn_registry = {"latest_turn_id": None}
        answer, rows, sources, sql, begun, turn_registry, ask_button = begin_fn(
            "what is OPS",
            [],
            [],
            turn_registry,
        )

        assert answer == ""
        assert rows == []
        assert sources == []
        assert sql == ""
        assert begun.update.status == "pending"
        assert ask_button == {"interactive": False, "__type__": "update"}

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            chat, textbox, answer, rows, sources, sql, chat_state, conversation, ask_button = (
                query_fn(
                    begun,
                    turn_registry,
                )
            )

        assert textbox == "what is OPS"
        assert answer == "answered what is OPS"
        assert chat[-1]["content"] == "answered what is OPS"
        assert chat_state == chat
        assert conversation[-1]["question"] == "what is OPS"
        assert rows == []
        assert sources == []
        assert sql == ""
        assert ask_button == {"interactive": True, "__type__": "update"}

    def test_stale_query_completion_does_not_overwrite_newer_pending_turn(self):
        """An older in-flight completion must not replace a newer cleared UI state."""
        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )
        turn_registry = {"latest_turn_id": None}
        _, _, _, _, old_begun, turn_registry, _ = begin_fn("what is OPS", [], [], turn_registry)

        def fake_answer(question: str, **_kwargs):
            begin_fn("career home run leaders", [], [], turn_registry)
            return StructuredAnswer(
                answer=f"stale answer for {question}",
                intent="general_explanation",
            )

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            outputs = query_fn(old_begun, turn_registry)

        assert all(
            isinstance(value, dict) and value.get("__type__") == "update" for value in outputs
        )
        assert len(outputs) == 9

    def test_stale_query_completion_uses_latest_turn_after_state_snapshot(self):
        """A copied Gradio state snapshot must not let an older answer overwrite newer UI."""
        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )
        turn_registry = {"latest_turn_id": None}
        _, _, _, _, old_begun, turn_registry, _ = begin_fn("what is OPS", [], [], turn_registry)
        old_registry_snapshot = dict(turn_registry)
        begin_fn("career home run leaders", [], [], turn_registry)
        calls = []

        def fake_answer(question: str, **_kwargs):
            calls.append(question)
            return StructuredAnswer(
                answer=f"stale answer for {question}",
                intent="general_explanation",
            )

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            outputs = query_fn(old_begun, old_registry_snapshot)

        assert all(
            isinstance(value, dict) and value.get("__type__") == "update" for value in outputs
        )
        assert len(outputs) == 9
        assert calls == []

    def test_same_session_stale_snapshot_does_not_execute_backend(self):
        """A stale copied state in one browser session no-ops before backend execution."""
        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )
        session = gr.Request(session_hash="session-a")
        turn_registry = {"latest_turn_id": None}
        _, _, _, _, old_begun, turn_registry, _ = begin_fn(
            "what is OPS", [], [], turn_registry, session
        )
        old_registry_snapshot = dict(turn_registry)
        begin_fn("career home run leaders", [], [], turn_registry, session)
        calls = []

        def fake_answer(question: str, **_kwargs):
            calls.append(question)
            return StructuredAnswer(
                answer=f"stale answer for {question}",
                intent="general_explanation",
            )

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            outputs = query_fn(old_begun, old_registry_snapshot, session)

        assert all(
            isinstance(value, dict) and value.get("__type__") == "update" for value in outputs
        )
        assert len(outputs) == 9
        assert calls == []

    def test_query_adapter_reenables_ask_after_runtime_failure(self):
        """A backend runtime failure still returns a visible error and enables Ask."""
        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )

        turn_registry = {"latest_turn_id": None}
        _, _, _, _, begun, turn_registry, ask_button = begin_fn(
            "who played for the Braves in 1936", [], [], turn_registry
        )
        assert ask_button == {"interactive": False, "__type__": "update"}

        def fail_answer(_question: str, **_kwargs):
            raise RuntimeError("query failed")

        with patch("baseball_rag.request_execution.answer", side_effect=fail_answer):
            chat, textbox, answer, rows, sources, sql, chat_state, conversation, ask_button = (
                query_fn(
                    begun,
                    turn_registry,
                )
            )

        assert textbox == "who played for the Braves in 1936"
        assert "could not return an answer" in answer
        assert chat[-1]["content"] == f"{answer}\n\nWarning: query failed"
        assert chat_state == chat
        assert conversation[-1]["question"] == "who played for the Braves in 1936"
        assert rows == []
        assert sources == []
        assert sql == ""
        assert ask_button == {"interactive": True, "__type__": "update"}

    def test_stale_query_guard_is_scoped_to_gradio_session(self):
        """A newer query in another browser session must not suppress this session."""
        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )
        session_a = gr.Request(session_hash="session-a")
        session_b = gr.Request(session_hash="session-b")
        registry_a = {"latest_turn_id": None}
        registry_b = {"latest_turn_id": None}
        _, _, _, _, begun_a, registry_a, _ = begin_fn("what is OPS", [], [], registry_a, session_a)
        begin_fn("career home run leaders", [], [], registry_b, session_b)

        def fake_answer(question: str, **_kwargs):
            return StructuredAnswer(
                answer=f"answer for {question}",
                intent="general_explanation",
            )

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            chat, textbox, answer, rows, sources, sql, chat_state, conversation, ask_button = (
                query_fn(
                    begun_a,
                    registry_a,
                    session_a,
                )
            )

        assert textbox == "what is OPS"
        assert answer == "answer for what is OPS"
        assert chat[-1]["content"] == "answer for what is OPS"
        assert chat_state == chat
        assert conversation[-1]["question"] == "what is OPS"
        assert rows == []
        assert sources == []
        assert sql == ""
        assert ask_button == {"interactive": True, "__type__": "update"}

    def test_query_handler_records_trace_without_animating_architecture_components(self):
        """Ask records Architecture history without side-effecting Architecture UI outputs."""
        before_html = self.dash.arch_diagram.diagram_html.value
        before_footer = self.dash.arch_diagram.footer_html.value
        self.dash.arch_diagram.trace_history.clear()

        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )

        def fake_answer(question: str, **_kwargs):
            return StructuredAnswer(answer=f"answered {question}", intent="general_explanation")

        turn_registry = {"latest_turn_id": None}
        _, _, _, _, begun, turn_registry, _ = begin_fn("what is OPS", [], [], turn_registry)
        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            chat, textbox, answer, rows, sources, sql, chat_state, conversation, _ = query_fn(
                begun, turn_registry
            )

        assert textbox == "what is OPS"
        assert answer == "answered what is OPS"
        assert chat[-1]["content"] == "answered what is OPS"
        assert chat_state == chat
        assert conversation[-1]["question"] == "what is OPS"
        assert rows == []
        assert sources == []
        assert sql == ""
        assert len(self.dash.arch_diagram.trace_history) == 1
        assert self.dash.arch_diagram.trace_history[0].query == "what is OPS"
        assert self.dash.arch_diagram.diagram_html.value == before_html
        assert self.dash.arch_diagram.footer_html.value == before_footer

    def test_architecture_refresh_shows_latest_query_trace(self):
        """Refreshing the Architecture tab renders the last completed Query trace."""
        self.dash.arch_diagram.trace_history.clear()

        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )
        refresh_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "refresh_architecture_trace"
        )

        def fake_answer(question: str, **_kwargs):
            from baseball_rag.arch.tracing import traced

            with traced(component_id="query-router", label="Query Router"):
                pass
            return StructuredAnswer(answer=f"answered {question}", intent="general_explanation")

        turn_registry = {"latest_turn_id": None}
        _, _, _, _, begun, turn_registry, _ = begin_fn("what is OPS", [], [], turn_registry)
        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            query_fn(begun, turn_registry)

        html, footer = refresh_fn()

        assert "highlighted" in html
        assert "card-query-router" in html
        assert "general_explanation" in footer
        assert "completed in" in footer

    def test_architecture_refresh_uses_latest_answer_diagnostics(self):
        """Architecture combines the completed answer metadata with the latest trace."""
        self.dash.arch_diagram.trace_history.clear()
        self.dash.arch_diagram.clear_latest_runs()

        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )
        refresh_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "refresh_architecture_trace"
        )

        def fake_answer(question: str, **_kwargs):
            from baseball_rag.arch.tracing import traced

            with traced(component_id="query-router", label="Query Router"):
                pass
            return StructuredAnswer(
                answer=f"warning answer for {question}",
                intent="stat_query",
                warnings=["No matching rows found."],
                unsupported=True,
                unsupported_reason="no_data",
            )

        turn_registry = {"latest_turn_id": None}
        _, _, _, _, begun, turn_registry, _ = begin_fn(
            "who won the 1901 Mars league", [], [], turn_registry
        )
        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            query_fn(begun, turn_registry)

        html, _footer = refresh_fn()

        assert "who won the 1901 Mars league" in html
        assert "No matching rows found." in html
        assert "Unsupported outcome: no_data" in html
        assert "run-status warning" in html

    def test_architecture_refresh_is_scoped_to_browser_session(self):
        """A second browser session does not overwrite this session's Architecture view."""
        self.dash.arch_diagram.trace_history.clear()
        self.dash.arch_diagram.clear_latest_runs()

        begin_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "begin_query"
        )
        query_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "on_query"
        )
        refresh_fn = next(
            dependency.fn
            for dependency in self.dash.fns.values()
            if dependency.api_name == "refresh_architecture_trace"
        )

        def fake_answer(question: str, **_kwargs):
            from baseball_rag.arch.tracing import traced

            with traced(component_id="query-router", label="Query Router"):
                pass
            return StructuredAnswer(answer=f"answer for {question}", intent="general_explanation")

        session_a = gr.Request(session_hash="session-a")
        session_b = gr.Request(session_hash="session-b")
        registry_a = {"latest_turn_id": None}
        registry_b = {"latest_turn_id": None}
        _, _, _, _, begun_a, registry_a, _ = begin_fn(
            "what is OPS",
            [],
            [],
            registry_a,
            session_a,
        )
        _, _, _, _, begun_b, registry_b, _ = begin_fn(
            "career home run leaders",
            [],
            [],
            registry_b,
            session_b,
        )
        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            query_fn(begun_a, registry_a, session_a)
            query_fn(begun_b, registry_b, session_b)

        html_a, _ = refresh_fn(session_a)
        html_b, _ = refresh_fn(session_b)

        assert "what is OPS" in html_a
        assert "career home run leaders" not in html_a
        assert "career home run leaders" in html_b

    def test_query_handler_keeps_answer_when_diagram_recording_fails(self):
        """A trace-display failure should not replace a successful query answer."""
        from baseball_rag.web_app import respond_conversation

        class BrokenDiagram:
            def __init__(self):
                self.trace_history = []
                self.max_history = 10

            def animate_trace(self, _trace):
                raise RuntimeError("diagram failed")

        def fake_answer(question: str, **_kwargs):
            return StructuredAnswer(answer=f"answered {question}", intent="general_explanation")

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            chat, textbox, answer, rows, sources, sql, chat_state, conversation = (
                respond_conversation("what is OPS", [], [], diagram=BrokenDiagram())
            )

        assert textbox == "what is OPS"
        assert answer == "answered what is OPS"
        assert chat[-1]["content"] == "answered what is OPS"
        assert chat_state == chat
        assert conversation[-1]["answer"]["intent"] == "general_explanation"
        assert rows == []
        assert sources == []
        assert sql == ""


# --------------------------------------------------------------------------
# Phase 4.2 — Trace wiring: query tab → arch diagram
# --------------------------------------------------------------------------


class TestTraceWiring:
    """answer() call in the Query tab is traced and visible in Architecture tab."""

    def setup_method(self):
        from baseball_rag.web_app import build_dashboard

        self.dash = build_dashboard()

    def test_query_produces_trace_in_diagram_history(self):
        """A real query via respond() produces a trace in the diagram history.

        This exercises the full wiring: start_trace → @traced pipeline functions →
        finish_trace → animate_trace(trace) called on the diagram.
        """
        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        diagram = dash.arch_diagram
        # Clear any prior history
        diagram.trace_history.clear()

        from baseball_rag.web_app import respond

        respond("who had the most RBIs in 1962", [], diagram=diagram)

        assert len(diagram.trace_history) >= 1
        trace = diagram.trace_history[-1]
        assert trace.query == "who had the most RBIs in 1962"
        assert len(trace.stages) >= 1

    def test_structured_query_answers_once_and_animates_trace(self):
        """Structured Gradio responses reuse the traced answer execution."""
        from baseball_rag.web_app import build_dashboard, respond_structured

        dash = build_dashboard()
        diagram = dash.arch_diagram
        diagram.trace_history.clear()

        calls = 0

        def fake_answer(question: str, **_kwargs):
            nonlocal calls
            calls += 1
            return StructuredAnswer(answer=f"answered {question}", intent="general_explanation")

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            answer, rows, sources, sql = respond_structured("what is OPS", diagram=diagram)

        assert calls == 1
        assert answer == "answered what is OPS"
        assert rows == []
        assert sources == []
        assert sql == ""
        assert len(diagram.trace_history) == 1
        assert diagram.trace_history[0].query == "what is OPS"

    def test_structured_query_animates_with_real_dashboard_diagram(self):
        """Runtime Gradio requests can animate without rewiring component events."""
        from baseball_rag.web_app import build_dashboard, respond_structured

        dash = build_dashboard()
        diagram = dash.arch_diagram
        diagram.trace_history.clear()

        def fake_answer(question: str, **_kwargs):
            return StructuredAnswer(answer=f"answered {question}", intent="general_explanation")

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            answer, rows, sources, sql = respond_structured("what is OPS", diagram=diagram)

        assert answer == "answered what is OPS"
        assert rows == []
        assert sources == []
        assert sql == ""
        assert len(diagram.trace_history) == 1
        assert diagram.trace_history[0].query == "what is OPS"

    def test_structured_query_returns_dataframe_ready_rows(self):
        """Structured Gradio table rows are shaped for Dataframe, not object cells."""
        from baseball_rag.web_app import build_dashboard, respond_structured

        dash = build_dashboard()
        diagram = dash.arch_diagram

        def fake_answer(question: str, **_kwargs):
            return StructuredAnswer(
                answer=f"answered {question}",
                intent="stat_query",
                sources=[
                    SourceRecord(
                        type="duckdb",
                        label="RBI leaders",
                        columns=["name", "stat_value"],
                        rows=[
                            {"name": "Davis, Tommy", "stat_value": 153},
                            {"name": "Mays, Willie", "stat_value": 141},
                        ],
                    )
                ],
            )

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            _, rows, _, _ = respond_structured("who had the most RBIs in 1962", diagram=diagram)

        assert rows == {
            "headers": ["name", "stat_value"],
            "data": [["Davis, Tommy", 153], ["Mays, Willie", 141]],
        }

    def test_structured_query_sources_do_not_expose_gradio_file_paths(self):
        """Source JSON must not contain file-shaped `path` values Gradio fetches."""
        from baseball_rag.web_app import build_dashboard, respond_structured

        dash = build_dashboard()
        diagram = dash.arch_diagram

        def fake_answer(question: str, **_kwargs):
            return StructuredAnswer(
                answer=f"answered {question}",
                intent="stat_query",
                sources=[
                    SourceRecord(
                        type="duckdb",
                        label="RBI leaders",
                        data_manifest={
                            "files": [
                                {
                                    "path": "data/Batting.csv",
                                    "table": "batting",
                                }
                            ]
                        },
                    )
                ],
            )

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            _, _, sources, _ = respond_structured(
                "who had the most RBIs in 1962",
                diagram=diagram,
            )

        assert sources[0]["data_manifest"]["files"] == [
            {"file_path": "data/Batting.csv", "table": "batting"}
        ]

    def test_conversation_query_appends_turn_and_passes_prior_context(self):
        """The Query tab can run follow-ups with prior grounded answer context."""
        from baseball_rag.web_app import build_dashboard, respond_conversation

        dash = build_dashboard()
        diagram = dash.arch_diagram
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [{"name": "Bonds, Barry"}, {"name": "Aaron, Hank"}],
                        }
                    ],
                },
            }
        ]
        chat_history = [{"role": "user", "content": "career home run leaders"}]

        def fake_answer(question: str, **kwargs):
            assert question == "tell me about the second player"
            assert kwargs["conversation"] == prior_turns
            return StructuredAnswer(answer="Hank Aaron bio", intent="player_biography")

        with patch("baseball_rag.request_execution.answer", side_effect=fake_answer):
            (
                chat,
                textbox,
                answer,
                rows,
                sources,
                sql,
                chat_state,
                conversation,
            ) = respond_conversation(
                "tell me about the second player",
                chat_history,
                prior_turns,
                diagram=diagram,
            )

        assert textbox == "tell me about the second player"
        assert chat[-2:] == [
            {"role": "user", "content": "tell me about the second player"},
            {"role": "assistant", "content": "Hank Aaron bio"},
        ]
        assert chat_state == chat
        assert chat_state is not chat
        assert conversation[-1]["question"] == "tell me about the second player"
        assert conversation[-1]["answer"]["intent"] == "player_biography"
        assert answer == "Hank Aaron bio"
        assert rows == []
        assert sources == []
        assert sql == ""

    def test_conversation_query_answers_pronoun_followup_with_spelled_year(self):
        """The submitted follow-up stays visible and answers the resolved player-year stat."""
        from baseball_rag.web_app import respond_conversation

        question = "How many homers did he have in nineteen twenty-five?"
        chat_history = [
            {"role": "user", "content": "who was Babe Ruth"},
            {"role": "assistant", "content": "Babe Ruth biography"},
        ]
        prior_turns = [
            {
                "question": "who was Babe Ruth",
                "answer": {
                    "answer": "Babe Ruth biography",
                    "intent": "player_biography",
                    "metadata": {"context_player_name": "Babe Ruth"},
                    "sources": [{"type": "system", "label": "LLM memory", "rows": []}],
                },
            }
        ]

        chat, textbox, answer, rows, sources, sql, chat_state, conversation = respond_conversation(
            question, chat_history, prior_turns
        )

        assert chat[-2]["content"] == question
        assert textbox == question
        assert chat_state == chat
        assert conversation[-1]["question"] == question
        assert "Ruth, Babe" in answer
        assert "(1925)" in answer
        assert "25 HR" in answer
        assert rows["data"][0][1] == 1925
        assert rows["data"][0][3] == 25
        assert sources[0]["rows"][0]["year"] == 1925
        assert sql

    def test_conversation_query_ignores_blank_messages(self):
        """Blank messages must not run a query and should restore a runnable default."""
        from baseball_rag.web_app import respond_conversation

        chat_history = [{"role": "user", "content": "career home run leaders"}]
        prior_turns = [{"question": "career home run leaders", "answer": {"sources": []}}]

        with patch("baseball_rag.web_app._execute_for_gradio") as execute:
            chat, textbox, answer, rows, sources, sql, chat_state, conversation = (
                respond_conversation("   ", chat_history, prior_turns)
            )

        execute.assert_not_called()
        assert chat == chat_history
        assert chat_state == chat_history
        assert conversation == prior_turns
        assert textbox == "who had the most RBIs in 1962"
        assert answer == ""
        assert rows == []
        assert sources == []
        assert sql == ""

    def test_conversation_query_ignores_none_message(self):
        """Missing textbox input should restore a runnable default."""
        from baseball_rag.web_app import respond_conversation

        with patch("baseball_rag.web_app._execute_for_gradio") as execute:
            chat, textbox, answer, rows, sources, sql, chat_state, conversation = (
                respond_conversation(None, [], [])
            )

        execute.assert_not_called()
        assert chat == []
        assert chat_state == []
        assert conversation == []
        assert textbox == "who had the most RBIs in 1962"
        assert answer == ""
        assert rows == []
        assert sources == []
        assert sql == ""

    def test_conversation_query_returns_visible_timeout_message(self):
        """LLM timeouts should become chat output instead of wedging the Ask event."""
        from baseball_rag.web_app import respond_conversation

        with patch("baseball_rag.web_app._execute_for_gradio", side_effect=TimeoutError("slow")):
            chat, textbox, answer, rows, sources, sql, chat_state, conversation = (
                respond_conversation("what is slugging percentage", [], [])
            )

        assert textbox == "what is slugging percentage"
        assert "timed out" in answer.lower()
        assert chat == [
            {"role": "user", "content": "what is slugging percentage"},
            {"role": "assistant", "content": f"{answer}\n\nWarning: slow"},
        ]
        assert chat_state == chat
        assert conversation[-1]["question"] == "what is slugging percentage"
        assert conversation[-1]["answer"]["intent"] == "error"
        assert rows == []
        assert sources == []
        assert sql == ""

    def test_conversation_query_returns_visible_failure_message(self):
        """Post-LM failures should become chat output instead of wedging the Ask event."""
        from baseball_rag.web_app import respond_conversation

        with patch(
            "baseball_rag.web_app._execute_for_gradio",
            side_effect=ValueError("missing choices in LM response"),
        ):
            chat, textbox, answer, rows, sources, sql, chat_state, conversation = (
                respond_conversation("who was Babe Ruth", [], [])
            )

        assert textbox == "who was Babe Ruth"
        assert "could not return an answer" in answer.lower()
        assert "missing choices in LM response" in chat[-1]["content"]
        assert chat_state == chat
        assert conversation[-1]["question"] == "who was Babe Ruth"
        assert conversation[-1]["answer"]["intent"] == "error"
        assert rows == []
        assert sources == []
        assert sql == ""

    def test_trace_shows_correct_route_type(self):
        """Trace correctly records stat_query vs general_explanation route."""
        from baseball_rag.arch.tracing import finish_trace, start_trace, traced
        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        diagram: ArchitectureDiagram = dash.arch_diagram
        diagram.trace_history.clear()

        # Simulate a stat_query trace manually via the tracing API
        start_trace("who had the most RBIs in 1962")
        with traced(component_id="cli", label="CLI"):
            pass
        with traced(
            component_id="query-router",
            label="Query Router",
            output_summary="stat_query",
        ):
            pass
        with traced(
            component_id="duckdb",
            label="DuckDB Query",
            output_summary="Mickey Mantle 123 RBIs",
        ):
            pass
        trace = finish_trace(route_type="stat_query")
        if trace:
            diagram.trace_history.append(trace)

        assert len(diagram.trace_history) == 1
        assert diagram.trace_history[0].route_type == "stat_query"


# --------------------------------------------------------------------------
# Phase 4.3 — Dashboard launch
# --------------------------------------------------------------------------


class TestDashboardLaunch:
    """The dashboard can be launched and responds to requests."""

    def test_build_dashboard_returns_a_gradio_blocks(self):
        """build_dashboard() returns a gr.Blocks instance."""
        import gradio

        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        assert isinstance(dash, gradio.Blocks)

    def test_dashboard_events_output_rendered_components(self):
        """Dashboard events only target concrete components present in Gradio config."""
        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        config = dash.get_config_file()
        component_ids = {component["id"] for component in config["components"]}

        for dependency in config["dependencies"]:
            missing_outputs = [
                output_id
                for output_id in dependency.get("outputs", [])
                if output_id not in component_ids
            ]
            assert missing_outputs == []
            assert dash.arch_diagram._id not in dependency.get("outputs", [])

    def test_web_app_module_has_main_block(self):
        """web_app.py defines a `demo` Blocks (for uvicorn/Gradio hosting)."""
        import gradio

        from baseball_rag import web_app

        assert hasattr(web_app, "demo")
        # demo should be launchable or mountable
        assert isinstance(web_app.demo, gradio.Blocks)
