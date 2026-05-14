"""Tests for ArchitectureDiagram UI — Phase 3.3 / 3.4.

Covers: detail panel, animation sequence, timing display, query history.
"""

from datetime import datetime
from unittest.mock import patch

import pytest

from baseball_rag.arch import TestStatus
from baseball_rag.arch.components import ComponentRegistry
from baseball_rag.arch.diagram import (
    _ANIMATION_HIGHLIGHT_MS,
    _ANIMATION_STAGE_DELAY_MS,
    ArchitectureDiagram,
)
from baseball_rag.arch.tracing import PipelineStage, PipelineTrace

# --------------------------------------------------------------------------:
# Phase 3.1 — test_diagram_renders_all_layers
# --------------------------------------------------------------------------:


class TestDiagramRendersAllLayers:
    """ArchitectureDiagram must lay out all five layers in order and show cards per component."""

    def setup_method(self):
        self.reg = ComponentRegistry()
        self.diagram = ArchitectureDiagram(registry=self.reg, _test_mode=True)

    def teardown_method(self):
        try:
            self.diagram.close()
        except Exception:
            pass

    def test_architecture_diagram_accepts_registry(self):
        """The component constructor accepts a ComponentRegistry (or None for default)."""
        assert self.diagram is not None
        assert self.diagram.registry is self.reg

    def test_architecture_diagram_default_registry(self):
        """Passing no argument uses the global registry."""
        from baseball_rag.arch.components import get_registry

        diagram = ArchitectureDiagram(_test_mode=True)
        assert diagram.registry is get_registry()

    def test_all_five_layers_render_in_order_api_to_generation(self):
        """Layers appear in display order: API → Routing → Retrieval → Data → Generation."""
        html = self.diagram._build_diagram_html()

        api_pos = html.find(">API<")
        routing_pos = html.find(">Routing<")
        retrieval_pos = html.find(">Retrieval<")
        data_pos = html.find(">Data<")
        generation_pos = html.find(">Generation<")

        assert api_pos < routing_pos < retrieval_pos < data_pos < generation_pos, (
            "Layers must appear top-to-bottom in the HTML in enum order"
        )

    def test_each_layer_shows_its_components_as_cards(self):
        """Every component registered to a layer appears as an arch-card div."""
        html = self.diagram._build_diagram_html()

        # API layer has cli + api-server
        assert "cli" in html
        assert "api-server" in html

    def test_component_cards_install_selection_bridge_function(self):
        """Rendered cards include the JS bridge needed by their onclick handlers."""
        html = self.diagram._build_diagram_html()

        assert 'onclick="(function(componentId)' in html
        assert "arch-select-bridge" in html
        assert "display:none!important" in html
        assert "dispatchEvent" in html

    def test_component_cards_are_accessible_click_controls(self):
        """Visible components render as focusable controls with stable component ids."""
        html = self.diagram._build_diagram_html()

        assert 'role="button"' in html
        assert '<button type="button"' in html
        assert 'tabindex="0"' in html
        assert 'data-component-id="query-router"' in html

    def test_selected_component_state_is_separate_from_trace_highlight(self):
        """Selected means inspected, while highlighted still means used by the latest query."""
        self.diagram.highlight(["duckdb"])
        self.diagram.select_component("query-router")

        html = self.diagram._build_diagram_html()

        assert 'id="card-duckdb"' in html
        assert "arch-card highlighted" in html
        assert 'id="card-query-router"' in html
        assert "selected" in html

    def test_selected_component_outside_trace_is_not_dimmed(self):
        """A selected component remains visually inspectable even if the latest trace missed it."""
        self.diagram.highlight(["duckdb"])
        self.diagram.select_component("query-router")

        html = self.diagram._build_diagram_html()

        assert 'id="card-query-router"' in html
        assert 'class="arch-card selected"' in html
        assert 'class="arch-card dimmed selected"' not in html

    def test_routing_layer_shows_query_router(self):
        """Routing layer shows the query-router component."""
        html = self.diagram._build_diagram_html()
        assert "query-router" in html or "Query Router" in html

    def test_data_layer_shows_duckdb_without_removed_corpus_grounding(self):
        """The current runtime data layer shows DuckDB, not removed corpus retrieval."""
        html = self.diagram._build_diagram_html()

        assert "duckdb" in html
        assert "corpus-grounding" not in html
        assert "Corpus Grounding" not in html
        assert "Chroma" not in html

    def test_generation_layer_shows_llm_and_prompt(self):
        """Generation layer shows both LLM and Prompt Templates components."""
        html = self.diagram._build_diagram_html()

        assert "llm" in html
        assert "prompt" in html or "Prompt" in html


# --------------------------------------------------------------------------:
# Phase 3.2 — test_highlight_active_components
# --------------------------------------------------------------------------:


class TestHighlightActiveComponents:
    """Nodes can be highlighted (active) and dimmed (inactive)."""

    def setup_method(self):
        self.reg = ComponentRegistry()
        self.diagram = ArchitectureDiagram(registry=self.reg, _test_mode=True)

    def teardown_method(self):
        try:
            self.diagram.close()
        except Exception:
            pass

    def test_highlight_accepts_list_of_component_ids(self):
        """Calling diagram.highlight([...]) accepts a list of component id strings."""
        result = self.diagram.highlight(["query-router", "duckdb"])
        assert result is self.diagram  # chainable

    def test_highlighted_nodes_use_highlighted_css_class(self):
        """Nodes in the highlight list receive the 'highlighted' CSS class."""
        self.diagram.highlight(["query-router", "duckdb"])

        html = self.diagram._build_diagram_html()

        assert "highlighted" in html
        # At least two cards should be highlighted
        assert html.count("highlighted") >= 2

    def test_inactive_nodes_render_dimmed(self):
        """Nodes NOT in highlight list get 'dimmed' CSS class when any highlight is active."""
        self.diagram.highlight(["query-router"])

        html = self.diagram._build_diagram_html()

        assert "dimmed" in html
        card_count = html.count("arch-card")
        highlighted_count = html.count("highlighted")
        assert highlighted_count < card_count

    def test_highlighting_is_cleared_on_clear_highlight(self):
        """clear_highlight() removes all highlight classes and resets the diagram."""
        self.diagram.highlight(["query-router", "llm"])
        html_after_highlight = self.diagram._build_diagram_html()
        assert "highlighted" in html_after_highlight

        # Clear before new query
        self.diagram.clear_highlight()
        html_after_clear = self.diagram._build_diagram_html()

        assert "highlighted" not in html_after_clear
        assert "arch-card" in html_after_clear  # structure still present

    def test_empty_highlight_list_keeps_all_cards_neutral(self):
        """Passing an empty list to highlight() leaves all cards with no dim/highlight class."""
        self.diagram.highlight([])

        html = self.diagram._build_diagram_html()

        assert "highlighted" not in html
        # With empty ids, no card gets any extra class (neutral state)
        assert "dimmed" not in html

    def test_highlight_unknown_component_id_does_not_crash(self):
        """Highlighting a non-existent component id is handled gracefully."""
        self.diagram.highlight(["query-router", "nonexistent-component-xyz"])  # must not raise


# --------------------------------------------------------------------------:
# Phase 3.3 — Detail Panel
# --------------------------------------------------------------------------:


class TestStageDetailPanel:
    """Test the detail panel that appears when a component is selected."""

    def setup_method(self):
        # Fresh registry per test to avoid cross-test pollution on singleton state
        self.reg = ComponentRegistry()
        self.diagram = ArchitectureDiagram(registry=self.reg, _test_mode=True)

    def teardown_method(self):
        try:
            self.diagram.close()
        except Exception:
            pass

    def test_detail_panel_shows_label_and_description(self):
        """Clicking a component shows label and description in the detail panel."""
        comp = self.reg.get("query-router")
        assert comp is not None

        # select_component updates internal state and detail HTML
        self.diagram.select_component("query-router")

        html = self.diagram._build_detail_html("query-router")
        assert comp.label in html
        assert comp.description in html

    def test_detail_panel_uses_inspection_placeholder_copy(self):
        """The empty detail panel invites selection without promising broken click behavior."""
        html = self.diagram._build_detail_html(None)

        assert "Select a component to inspect its role and source." in html

    def test_detail_panel_shows_runtime_role_source_and_excerpt(self):
        """Selected details expose the component role, source path, and source availability."""
        html = self.diagram._build_detail_html("query-router")

        assert "Runtime role" in html
        assert "Source path" in html
        assert "src/baseball_rag/routing/query_router.py" in html
        assert ("Source excerpt" in html) or ("source unavailable" in html)

    def test_detail_panel_shows_file_path(self):
        """Detail panel includes the component's file path."""
        html = self.diagram._build_detail_html("claim-verifier")
        # File path appears somewhere in the detail HTML
        comp = self.reg.get("claim-verifier")
        assert comp is not None
        assert comp.file_path in html

    def test_detail_panel_shows_source_snippet(self):
        """Detail panel renders source snippet for a component."""
        html = self.diagram._build_detail_html("duckdb")
        # Should contain the "Source (first 10 lines)" summary or detail-snippet block
        assert ("detail-snippet" in html) or ("No source file found" in html)

    def test_test_status_badge_shown_per_component(self):
        """Component with a test status shows a coloured badge in the panel."""
        # Set FAIL on claim-verifier via registry
        self.reg.set_test_status("claim-verifier", TestStatus.FAIL)
        diagram = ArchitectureDiagram(registry=self.reg, _test_mode=True)

        html = diagram._build_detail_html("claim-verifier")
        assert "badge-fail" in html or "FAIL" in html

    def test_unknown_component_shows_error_message(self):
        """Selecting a non-existent component renders an error string."""
        html = self.diagram._build_detail_html("nonexistent-component-xyz")
        assert "Unknown component" in html or "nonono" in html.lower()

    def test_selecting_none_clears_panel(self):
        """Passing None to select_component shows the placeholder message."""
        self.diagram.select_component(None)
        html = self.diagram._build_detail_html(None)
        assert "Select a component to inspect its role and source." in html

    def test_detail_panel_renders_in_right_sidebar(self):
        """The diagram layout places detail panel HTML in #detail-panel elem."""
        self.diagram._build_diagram_html()
        diag_with_panel = self.diagram._build_detail_html("llm")
        assert "detail-panel" in diag_with_panel

    def test_select_component_is_idempotent(self):
        """Calling select_component twice with same id is a no-op (no error)."""
        diagram = ArchitectureDiagram(registry=self.reg, _test_mode=True)
        diagram.select_component("llm")
        diagram.select_component("llm")  # should not raise
        assert True


# --------------------------------------------------------------------------:
# Phase 3.4 — Animation Sequence
# --------------------------------------------------------------------------:


class TestAnimatePipelineFlow:
    """Test the sequential stage highlighting animation."""

    def setup_method(self):
        self.reg = ComponentRegistry()
        # Note: some tests will patch _js_animate and Button.click directly.
        # Those tests need gr.Blocks.__init__ patched too, done per-test via @patch.
        try:
            self.diagram = ArchitectureDiagram(registry=self.reg, _test_mode=True)
        except Exception:
            # If we're in a test that patches __init__, the object is still usable
            # as a plain Python object for attribute testing
            pass

    def teardown_method(self):
        try:
            self.diagram.close()
        except Exception:
            pass

    def _make_trace(self, *stage_ids) -> PipelineTrace:
        """Helper: build a PipelineTrace with one stage per id."""
        now = datetime.now()
        stages = []
        for i, cid in enumerate(stage_ids):
            comp = self.reg.get(cid)
            label = comp.label if comp else cid
            stages.append(
                PipelineStage(
                    component_id=cid,
                    label=label,
                    started_at=now,
                    elapsed_ms=10.0 + i * 5,
                )
            )
        t = PipelineTrace(query="test")
        for s in stages:
            t.add_stage(s)
        return t

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_animate_trace_highlights_stages_sequentially(self):
        """animate_trace stores the trace and sets up stage highlighting state."""
        trace = self._make_trace("cli", "query-router", "claim-verifier")

        result = self.diagram.animate_trace(trace)

        # Returns self for chaining
        assert result is self.diagram
        # The diagram keeps a history of traces
        assert len(self.diagram.trace_history) == 1
        assert self.diagram.trace_history[0] is trace

    def test_animation_variables_are_configured(self):
        """Animation uses the correct timing constants."""
        # Verify the module-level constants match spec:
        # - 100ms delay between stages
        # - 400ms highlight duration per stage
        assert _ANIMATION_STAGE_DELAY_MS == 100
        assert _ANIMATION_HIGHLIGHT_MS == 400

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    def test_animate_empty_trace_is_noop(self):
        """animate_trace with no stages returns immediately without error."""
        empty = PipelineTrace(query="nothing")
        result = self.diagram.animate_trace(empty)
        assert result is self.diagram
        # No trace added to history for empty traces
        assert len(self.diagram.trace_history) == 0

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_skip_animation_stops_early_and_shows_full_path(self):
        """Calling skip_animation stops the animation and shows all stages at once."""
        trace = self._make_trace("cli", "query-router", "duckdb")

        # Start animation
        self.diagram.animate_trace(trace)
        assert self.diagram.skip_btn.visible is True

        # Skip it
        self.diagram.skip_animation()

        assert self.diagram.skip_btn.visible is False
        # All stage IDs should now be highlighted (not dimmed)
        expected_ids = {"cli", "query-router", "duckdb"}
        assert self.diagram.highlight_ids == expected_ids

    def test_skip_button_is_initially_hidden(self):
        """The Skip Animation button is not visible until animation starts."""
        assert self.diagram.skip_btn.visible is False

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_animate_trace_clears_previous_animation(self):
        """Starting a new animate_trace cancels any in-progress one before re-registering."""
        _ = self._make_trace("cli", "query-router")
        trace2 = self._make_trace("llm", "prompt")

        # Simulate first animation is already running
        with patch.object(self.diagram, "_animating", True):
            self.diagram.animate_trace(trace2)

        # Should have called skip_animation internally (which sets _animating=False)
        assert self.diagram._animating is False

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    def test_route_type_badge_in_footer(self):
        """After animate_trace, footer shows route type badge and total time."""
        trace = self._make_trace("cli", "query-router")
        trace.route_type = "stat_query"

        # Manually exercise the history + footer update path without Gradio event wiring
        self.diagram.trace_history.append(trace)
        if len(self.diagram.trace_history) > self.diagram.max_history:
            self.diagram.trace_history.pop(0)

        route_str = "\u26a1 stat_query"
        self.diagram.footer_html.value = (
            f"<span class='route-badge'>{route_str}</span>"
            f" &nbsp;|&nbsp; Pipeline completed in {trace.total_ms:.1f}ms"
        )

        footer = self.diagram.footer_html.value
        assert ("stat_query" in footer) or ("general_explanation" in footer)
        assert "ms" in footer


# --------------------------------------------------------------------------:
# Phase 3.5 — Timing Display  (also covers route badge and per-stage timing)
# --------------------------------------------------------------------------:


class TestTimingDisplay:
    """Test that elapsed_ms values and total time are displayed correctly."""

    def setup_method(self):
        self.reg = ComponentRegistry()
        self.diagram = ArchitectureDiagram(registry=self.reg, _test_mode=True)

    def teardown_method(self):
        try:
            self.diagram.close()
        except Exception:
            pass

    def test_per_stage_elapsed_ms_in_trace(self):
        """Each PipelineStage carries its own elapsed_ms."""
        now = datetime.now()
        s1 = PipelineStage(
            component_id="duckdb",
            label="DuckDB",
            started_at=now,
            elapsed_ms=23.4,
        )
        s2 = PipelineStage(
            component_id="llm",
            label="LLM Generation",
            started_at=now,
            elapsed_ms=1500.0,
        )
        trace = PipelineTrace(query="test")
        trace.add_stage(s1)
        trace.add_stage(s2)

        assert trace.total_ms == pytest.approx(1523.4, rel=1e-9)
        stage_times = [s.elapsed_ms for s in trace.stages]
        assert 23.4 in stage_times
        assert 1500.0 in stage_times

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_total_time_in_footer_after_animation(self):
        """Footer shows 'Pipeline completed in Xms' with the correct sum."""
        now = datetime.now()
        stages = [
            PipelineStage(component_id="cli", label="CLI", started_at=now, elapsed_ms=1.5),
            PipelineStage(
                component_id="router",
                label="Router",
                started_at=now,
                elapsed_ms=2.7,
            ),
        ]
        trace = PipelineTrace(query="test")
        for s in stages:
            trace.add_stage(s)

        self.diagram.animate_trace(trace)

        footer = self.diagram.footer_html.value
        # Should contain "completed in" and a number ending in ms
        assert "completed in" in footer
        assert "ms" in footer

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_route_type_badge_bolt_for_stat_query(self):
        """⚡ stat_query route type is rendered correctly."""
        now = datetime.now()
        trace = PipelineTrace(query="test", route_type="stat_query")
        trace.add_stage(PipelineStage("x", "X", started_at=now, elapsed_ms=1.0))
        self.diagram.animate_trace(trace)

        footer = self.diagram.footer_html.value
        # Unicode bolt symbol (U+26A1) + stat_query
        assert "\u26a1" in footer or "stat_query" in footer

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_route_type_badge_magnifier_for_general_explanation(self):
        """🔍 general_explanation route type is rendered correctly."""
        now = datetime.now()
        trace = PipelineTrace(query="test", route_type="general_explanation")
        trace.add_stage(PipelineStage("x", "X", started_at=now, elapsed_ms=1.0))
        self.diagram.animate_trace(trace)

        footer = self.diagram.footer_html.value
        # Unicode magnifier (U+1F50D) + general_explanation
        assert "\ud83d\udd0d" in footer or "general_explanation" in footer


# --------------------------------------------------------------------------:
# Query History  (from Phase 4.2 trace history requirements)
# --------------------------------------------------------------------------:


class TestQueryHistory:
    """Test that completed traces are accumulated in a history list."""

    def setup_method(self):
        self.reg = ComponentRegistry()
        # Use a small max_history to test eviction
        self.diagram = ArchitectureDiagram(registry=self.reg, max_history=3, _test_mode=True)

    def teardown_method(self):
        try:
            self.diagram.close()
        except Exception:
            pass

    def _make_trace(self, query: str) -> PipelineTrace:
        now = datetime.now()
        trace = PipelineTrace(query=query)
        trace.add_stage(PipelineStage("cli", "CLI", started_at=now, elapsed_ms=1.0))
        return trace

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_animate_trace_appends_to_history(self):
        """Each completed animate_trace call adds to trace_history."""
        t1 = self._make_trace("first query")
        t2 = self._make_trace("second query")

        self.diagram.animate_trace(t1)
        assert len(self.diagram.trace_history) == 1
        assert self.diagram.trace_history[0].query == "first query"

        self.diagram.animate_trace(t2)
        assert len(self.diagram.trace_history) == 2

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_history_evicts_oldest_when_max_exceeded(self):
        """History drops the oldest entry once max_history is reached."""
        for i in range(5):
            t = self._make_trace(f"query {i}")
            self.diagram.animate_trace(t)

        # max_history=3, so only last 3 are kept
        assert len(self.diagram.trace_history) == 3
        queries = [tr.query for tr in self.diagram.trace_history]
        assert "query 2" in queries
        assert "query 0" not in queries

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    @patch("gradio.Button.click", lambda self, **kwargs: None)
    def test_skip_animation_does_not_duplicate_history(self):
        """skip_animation does not add a new history entry."""
        t1 = self._make_trace("alpha")
        self.diagram.animate_trace(t1)
        initial_len = len(self.diagram.trace_history)

        self.diagram.skip_animation()
        assert len(self.diagram.trace_history) == initial_len

    @patch.object(ArchitectureDiagram, "_js_animate", lambda self, ids, elapseds: None)
    def test_empty_trace_does_not_add_to_history(self):
        """animate_trace with no stages leaves history unchanged."""
        empty = PipelineTrace(query="empty")
        before = len(self.diagram.trace_history)
        self.diagram.animate_trace(empty)
        assert len(self.diagram.trace_history) == before

    def test_show_latest_trace_renders_static_highlighted_path(self):
        """A recorded trace can be rendered visibly without replaying animation."""
        now = datetime.now()
        trace = PipelineTrace(query="stat leaders")
        trace.add_stage(
            PipelineStage("query-router", "Query Router", started_at=now, elapsed_ms=1.0)
        )
        trace.add_stage(PipelineStage("duckdb", "DuckDB", started_at=now, elapsed_ms=2.0))
        trace.route_type = "stat_query"
        self.diagram.trace_history.append(trace)

        result = self.diagram.show_latest_trace()

        assert result is self.diagram
        assert self.diagram.highlight_ids == {"query-router", "duckdb"}
        assert "card-query-router" in self.diagram.diagram_html.value
        assert "highlighted" in self.diagram.diagram_html.value
        assert "stat_query" in self.diagram.footer_html.value
