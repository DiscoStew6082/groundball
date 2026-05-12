"""Tests for Dashboard integration — Phase 4.

Replaces web_app.py ChatInterface with a tabbed dashboard:
- Tab "Query": existing Q&A functionality (ChatInterface)
- Tab "Architecture": ArchitectureDiagram with full pipeline visualization

The dashboard wires the Query tab's answer() calls through the tracing
instrumentation so the Architecture Explorer shows every query execution.
"""

from unittest.mock import patch

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
        ask_id = next(
            component["id"]
            for component in components
            if component["type"] == "button" and component.get("props", {}).get("value") == "Ask"
        )
        query_dependencies = [
            dependency
            for dependency in config["dependencies"]
            if dependency["targets"]
            and dependency["targets"][0][0] in {ask_id, question_id}
            and dependency["targets"][0][1] in {"click", "submit"}
        ]

        assert len(query_dependencies) == 1
        for dependency in query_dependencies:
            assert len(dependency["targets"]) == 2
            assert chatbot_id not in dependency["inputs"]
            assert chatbot_id in dependency["outputs"]
            assert dependency["queue"] is True
            assert dependency["show_progress"] == "hidden"
            assert dependency["trigger_mode"] == "once"
            state_inputs = [
                component_id
                for component_id in dependency["inputs"]
                if component_types[component_id] == "state"
            ]
            assert len(state_inputs) == 2


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

        assert textbox == "who had the most RBIs in 1962"
        assert chat[-2:] == [
            {"role": "user", "content": "tell me about the second player"},
            {"role": "assistant", "content": "Hank Aaron bio"},
        ]
        assert chat_state == chat
        assert conversation[-1]["question"] == "tell me about the second player"
        assert conversation[-1]["answer"]["intent"] == "player_biography"
        assert answer == "Hank Aaron bio"
        assert rows == []
        assert sources == []
        assert sql == ""

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
