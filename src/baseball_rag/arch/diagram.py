"""ArchitectureDiagram — Gradio Blocks component for the Baseball RAG pipeline diagram.

Phase 3 of the Architecture Explorer plan.
"""

from __future__ import annotations

import threading
from typing import Any, Callable

import gradio as gr

from baseball_rag.arch.components import (
    ComponentRegistry,
    DiagramComponent,
    Layer,
    TestStatus,
    get_registry,
)
from baseball_rag.arch.tracing import PipelineTrace

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ANIMATION_STAGE_DELAY_MS = 100  # pause between stages during animation
_ANIMATION_HIGHLIGHT_MS = 400  # how long each stage stays highlighted

_LAYER_LABELS: dict[Layer, str] = {
    Layer.API: "API",
    Layer.ROUTING: "Routing",
    Layer.RETRIEVAL: "Retrieval",
    Layer.DATA: "Data",
    Layer.GENERATION: "Generation",
}

_ROUTE_BADGE: dict[str, str] = {
    "stat_query": "\u26a1 stat_query",
    "general_explanation": "\ud83d\udd0d general_explanation",
}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

_DIAGRAM_CSS = """
#arch-diagram { font-family: 'Courier New', monospace; }
.layer-row { margin-bottom: 12px; }
.layer-label {
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: #6b7280;
    margin-bottom: 4px;
}
.component-grid { display: flex; gap: 8px; flex-wrap: wrap; }
.arch-card {
    border: 2px solid #374151;
    border-radius: 8px;
    padding: 10px 14px;
    min-width: 140px;
    max-width: 200px;
    cursor: pointer;
    transition: all 0.2s ease;
    background: #1f2937;
    color: #f9fafb;
}
.arch-card:hover { border-color: #60a5fa; }
.arch-card .card-id   { font-size: 11px; color: #9ca3af; margin-bottom: 2px; }
.arch-card .card-body { font-size: 13px; font-weight: 600; }
.arch-card .status-row { font-size: 12px; margin-top: 4px; }

/* Highlighted (active pipeline stage) */
.arch-card.highlighted {
    border-color: #34d399;
    background: #064e3b;
    box-shadow: 0 0 12px #34d39966;
}

/* Dimmed (not in current trace) */
.arch-card.dimmed { opacity: 0.35; }

/* Error state */
.arch-card.error-state { border-color: #f87171; background: #7f1d1d; }

#detail-panel {
    border-left: 1px solid #374151;
    padding-left: 16px;
}
.detail-title   { font-size: 15px; font-weight: bold; margin-bottom: 4px; }
.detail-meta    { font-size: 11px; color: #9ca3af; margin-bottom: 8px; }
.detail-desc    { font-size: 13px; margin-bottom: 8px; line-height: 1.5; }
.detail-snippet {
    background: #111827;
    border-radius: 6px;
    padding: 10px;
    font-family: 'Courier New', monospace;
    font-size: 11px;
    white-space: pre-wrap;
    overflow-x: auto;
    max-height: 200px;
}
.detail-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
.badge-pass   { background: #064e3b; color: #34d399; }
.badge-fail   { background: #7f1d1d; color: #f87171; }
.badge-unknown{ background: #374151; color: #9ca3af; }

#footer { font-size: 12px; color: #6b7280; margin-top: 8px; text-align: right; }
.route-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 9999px;
    font-size: 12px;
    background: #1f2937;
    border: 1px solid #374151;
}

#skip-btn { font-size: 11px; padding: 2px 10px; }
"""


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------


def _layer_html(layer: Layer, components: list[DiagramComponent]) -> str:
    """Return the HTML string for one layer row (label + component cards)."""
    label = _LAYER_LABELS.get(layer, layer.value)
    cards_html = "".join(_card_html(c) for c in components)
    return f"""
<div class="layer-row">
  <div class="layer-label">{label}</div>
  <div class="component-grid" id="layer-{layer.value}">{cards_html}</div>
</div>"""


def _card_html(comp: DiagramComponent, extra_cls: str = "") -> str:
    """Return the HTML for a single component card."""
    status_emoji = comp.status_indicator()
    return f"""
<div class="arch-card {extra_cls}"
     id="card-{comp.id}"
     onclick="select_component('{comp.id}')">
  <div class="card-id'>{status_emoji} {comp.id}</div>
  <div class="card-body">{comp.label}</div>
</div>"""


# ---------------------------------------------------------------------------
# ArchitectureDiagram Blocks class
# ---------------------------------------------------------------------------


class ArchitectureDiagram(gr.Blocks):
    """Interactive Gradio Blocks component that renders the Baseball RAG architecture.

    Parameters
    ----------
    registry
        ComponentRegistry providing all DiagramComponent definitions.
        Defaults to the global registry.

    Attributes
    ----------
    highlight_ids: set[str]
        Currently highlighted component ids (the active pipeline path).
    selected_id: str | None
        The component whose detail panel is currently shown.
    trace_history: list[PipelineTrace]
        Last N=10 completed traces for the history sidebar.
    """

    # Gradio event tag → component id that triggered it
    SELECTED_ID = "selected_component_id"
    ANIMATION_DONE = "animation_done"

    def __init__(
        self,
        registry: ComponentRegistry | None = None,
        *,
        max_history: int = 10,
        _test_mode: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)

        self.registry = registry or get_registry()
        self.max_history = max_history

        # Runtime state
        self.highlight_ids: set[str] = set()
        self.selected_id: str | None = None
        self.trace_history: list[PipelineTrace] = []
        self._animating = False
        self._anim_lock = threading.RLock()

        if _test_mode:
            # Provide lightweight stand-ins for Gradio components so tests can run
            class _DummyComp:
                """Mimics a gradio component's most-used attributes in test mode."""

                def __init__(self) -> None:
                    self.visible = False
                    self.value = ""

                def click(self, **kwargs):  # noqa: ARG002
                    pass  # no-op in test mode

            self.skip_btn: Any = _DummyComp()
            self.footer_html: Any = _DummyComp()
            self.diagram_html: Any = _DummyComp()  # needed by _js_animate guard
            return  # Skip Gradio UI construction in unit tests

        # ---- Build the UI --------------------------------------------------------
        with self:
            gr.Markdown("### \U0001f3c6 Baseball RAG — Architecture Explorer")

            with gr.Row():
                # Left: diagram + footer
                with gr.Column(scale=3):
                    self.diagram_html = gr.HTML(
                        self._build_diagram_html(),
                        elem_id="arch-diagram",
                        show_label=False,
                    )
                    self.footer_html = gr.HTML("", elem_id="footer", show_label=False)

                    # Skip animation button (hidden until animation starts)
                    with gr.Row():
                        self.skip_btn = gr.Button(
                            "Skip Animation \u23ed",
                            elem_id="skip-btn",
                            visible=False,
                            size="sm",
                        )
                        self.skip_btn.click(fn=self._on_skip_animation, inputs=[], outputs=[])

                # Right: detail panel
                with gr.Column(scale=1):
                    self.detail_panel = gr.HTML(self._build_detail_html(), elem_id="detail-panel")

            # ---- JavaScript callbacks ----------------------------------------
            self._setup_js()

        # Register default select handler (no-op until user hooks it up)
        self._on_select_callbacks: list[Callable[[str], None]] = []

    def post_init(self) -> ArchitectureDiagram:
        """Hook for subclasses or callers to add components after the main UI is built.

        Override this in a subclass or call it after construction to append
        additional Gradio components inside the still-active ``with self:`` context.
        """
        return self

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def highlight(self, ids: set[str] | list[str]) -> ArchitectureDiagram:
        """Highlight *ids* as the active pipeline path; all others are dimmed.

        Calling this also clears any in-progress animation.
        """
        self.highlight_ids = set(ids)
        self._update_diagram()
        return self

    def clear_highlight(self) -> ArchitectureDiagram:
        """Remove all highlighting and return to idle state."""
        self.highlight_ids.clear()
        self.selected_id = None
        self._update_diagram()
        self._set_detail_html(self._build_detail_html())
        return self

    def select_component(self, component_id: str | None) -> ArchitectureDiagram:
        """Show the detail panel for *component_id* (or clear it if None)."""
        self.selected_id = component_id
        self._update_diagram()
        self._set_detail_html(self._build_detail_html(component_id))
        return self

    def animate_trace(self, trace: PipelineTrace) -> ArchitectureDiagram:
        """Animate the diagram through *trace*, highlighting one stage at a time.

        Each stage is highlighted for ANIMATION_HIGHLIGHT_MS before advancing.
        Callbacks registered via ``on_animation_done`` are invoked when all stages
        have been shown.  The animation can be skipped at any time by clicking
        the "Skip Animation" button or calling ``skip_animation()``.
        """
        if not trace.stages:
            return self

        with self._anim_lock:
            if self._animating:
                self.skip_animation()
            self._animating = True
            self.trace_history.append(trace)
            if len(self.trace_history) > self.max_history:
                self.trace_history.pop(0)

        # Update footer with route badge + total time (skip in test mode)
        if hasattr(self, "footer_html"):
            route_str = _ROUTE_BADGE.get(trace.route_type, trace.route_type or "\u26a1 unknown")
            self.footer_html.value = (
                f"<span class='route-badge'>{route_str}</span>"
                f" &nbsp;|&nbsp; Pipeline completed in {trace.total_ms:.1f}ms"
            )

        # Kick off JS-driven animation
        stage_ids = [s.component_id for s in trace.stages]
        elapsed_list = [s.elapsed_ms for s in trace.stages]
        if hasattr(self, "skip_btn"):
            self.skip_btn.visible = True

        self._js_animate(stage_ids, elapsed_list)
        return self

    def _on_skip_animation(self) -> None:
        """Handle the Skip Animation button event registered during UI setup."""
        self.skip_animation()
        return None

    def skip_animation(self) -> None:
        """Stop any in-progress animation and show all trace stages at once."""
        with self._anim_lock:
            if not self._animating:
                return
            self._animating = False

        # Build the full set of highlighted ids from the most recent trace
        if self.trace_history:
            last = self.trace_history[-1]
            final_ids: set[str] = {s.component_id for s in last.stages}
            self.highlight_ids = final_ids
            self._update_diagram()
        if hasattr(self, "skip_btn"):
            self.skip_btn.visible = False

    def on_select(self, fn: Callable[[str], None]) -> ArchitectureDiagram:
        """Register a callback invoked whenever the user selects a component.

        The callback receives the selected *component_id* (may be None).
        """
        self._on_select_callbacks.append(fn)
        return self

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_diagram_html(self, highlight_ids: set[str] | None = None) -> str:
        """Render the full architecture diagram as an HTML string."""
        ids = highlight_ids if highlight_ids is not None else self.highlight_ids

        rows = []
        for layer in Layer:
            components = self.registry.by_layer(layer)
            if not components:
                continue
            # Assign CSS classes to each card based on current state
            cards_html = ""
            for comp in components:
                extra_cls = ""
                if comp.id in ids:
                    extra_cls = "highlighted"
                elif ids:  # something is highlighted but not this card
                    extra_cls = "dimmed"
                cards_html += _card_html(comp, extra_cls)
            rows.append(
                f'<div class="layer-row">'
                f'  <div class="layer-label">{_LAYER_LABELS[layer]}</div>'
                f'  <div class="component-grid" id="layer-{layer.value}">'
                f"{cards_html}"
                f"  </div>"
                f"</div>"
            )

        return "<div id='arch-diagram-inner'>" + "".join(rows) + "</div>"

    def _build_detail_html(self, component_id: str | None = None) -> str:
        """Render the detail panel HTML for *component_id* (or blank placeholder)."""
        if component_id is None:
            return (
                "<div id='detail-panel-inner'>"
                "<p style='color:#6b7280;font-size:12px;'>"
                "Click a component to inspect it."
                "</p></div>"
            )

        comp = self.registry.get(component_id)
        if comp is None:
            return f"<div id='detail-panel-inner'><i>Unknown component: {component_id}</i></div>"

        # Test status badge
        status_html = ""
        if comp.test_status is not None:
            css_cls = {
                TestStatus.PASS: "badge-pass",
                TestStatus.FAIL: "badge-fail",
                TestStatus.UNKNOWN: "badge-unknown",
            }.get(comp.test_status, "badge-unknown")
            label_text = {
                TestStatus.PASS: "PASS",
                TestStatus.FAIL: "FAIL",
                TestStatus.UNKNOWN: "UNKNOWN",
            }.get(comp.test_status, "")
            status_html = f"<span class='detail-badge {css_cls}'>{label_text}</span>"

        # Source snippet
        snippet = self.registry.get_source_snippet(component_id, n=10)
        if snippet:
            snippet_html = (
                "<details><summary style='cursor:pointer;font-size:12px;margin-bottom:4px;'>"
                "Source (first 10 lines)</summary>"
                f"<pre class='detail-snippet'>{_esc(snippet)}</pre></details>"
            )
        else:
            snippet_html = "<p style='font-size:11px;color:#6b7280;'>No source file found.</p>"

        return (
            f"<div id='detail-panel-inner'>"
            f"<div class='detail-title'>{_esc(comp.label)}</div>"
            f"<div class='detail-meta'>{status_html} &nbsp;|&nbsp; {_esc(comp.file_path)}</div>"
            f"<div class='detail-desc'>{_esc(comp.description)}</div>"
            f"{snippet_html}"
            f"</div>"
        )

    def _set_detail_html(self, html: str) -> None:
        """Safely update the detail panel HTML (thread-safe for animation callbacks)."""
        try:
            self.detail_panel.value = html
        except Exception:
            # Gradio may not be in a ready state during early init — ignore
            pass

    def _update_diagram(self) -> None:
        """Re-render the diagram with current highlight / dim state."""
        if hasattr(self, "diagram_html"):
            self.diagram_html.value = self._build_diagram_html()

    def _setup_js(self) -> None:
        """Wire up client-side JavaScript for interactive card selection."""

        # Expose Python methods to JS via a small bridging approach using
        # gr.State and change events.  We use a hidden Textbox as the bridge.
        self._js_bridge = gr.Textbox(visible=False, value="")

        def handle_js_select(raw: str) -> Any:
            if raw:
                comp_id = raw.strip()
                for cb in self._on_select_callbacks:
                    cb(comp_id)
                self.select_component(comp_id)
            else:
                self.select_component(None)
            return self.diagram_html.value, self.detail_panel.value

        self._js_bridge.change(
            fn=handle_js_select,
            inputs=[self._js_bridge],
            outputs=[self.diagram_html, self.detail_panel],
        )

    def _js_animate(self, stage_ids: list[str], elapsed_list: list[float]) -> None:
        """Trigger client-side staged animation via JavaScript.

        The JS function `animateStages` is injected into the page and called
        with the ordered list of component ids to highlight.
        """
        import json

        ids_json = json.dumps(stage_ids)
        delay_ms = _ANIMATION_STAGE_DELAY_MS + _ANIMATION_HIGHLIGHT_MS

        animation_script = f"""
<script>
(function() {{
    var stageIds = {ids_json};
    if (!stageIds || stageIds.length === 0) return;

    // Helper: set card CSS class
    function setCard(id, cls) {{
        var el = document.getElementById('card-' + id);
        if (!el) return;
        el.className = 'arch-card ' + cls;
    }}

    // Dim all cards initially
    stageIds.forEach(function(id) {{ setCard(id, 'dimmed'); }});

    var step = 0;
    function advance() {{
        if (step >= stageIds.length) {{
            // Animation complete — final highlight state persists
            stageIds.forEach(function(id) {{ setCard(id, ''); }});
            // Show the "Skip" button as done
            return;
        }}
        var currentId = stageIds[step];
        setCard(currentId, 'highlighted');
        step++;
        setTimeout(advance, {delay_ms});
    }}

    // Expose a skip function on window so the Skip button can call it
    window._skipArchAnimation = function() {{
        step = stageIds.length;  // force loop to exit after current tick
    }};

    advance();
}})();
</script>"""

        # Inject into diagram HTML — Gradio will render this via .then() or we append directly
        if hasattr(self, "diagram_html"):
            self.diagram_html.value = (
                self._build_diagram_html()
                + f"<div id='arch-animation-script'>{animation_script}</div>"
            )


def _esc(s: str) -> str:
    """HTML-escape a plain string for safe embedding."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
