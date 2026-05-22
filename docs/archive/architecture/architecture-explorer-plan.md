# Baseball RAG — Architecture Explorer Dashboard

## Overview

Replace the current `web_app.py` simple `ChatInterface` with a tabbed Gradio dashboard:

- **Tab 1: Query** — The existing Q&A interface
- **Tab 2: Architecture Explorer** — Interactive diagram showing the query pipeline + component inspector

The goal is portfolio visibility: management sees a real-time animated view of how a RAG query flows through the system, with timing breakdowns and clickable components.

---

## System Design

### Data Models

#### `DiagramComponent` (dataclass)
```
- id: str           # unique slug e.g. "query-router"
- label: str        # human-readable "Query Router"
- description: str  # one-liner
- layer: Layer      # enum: api | routing | retrieval | data | generation
- file_path: str    # relative path to source file
- test_status: TestStatus | None
```

#### `PipelineStage` (dataclass)
```
- component_id: str
- label: str
- started_at: datetime
- elapsed_ms: float
- output_summary: str  # "routed to stat_query → DuckDB"
- error: str | None
```

#### `PipelineTrace` (dataclass)
```
- query: str
- stages: list[PipelineStage]
- total_ms: float
- route_type: RouteType  # stat_query | general_explanation
```

### Layer Enum
```python
class Layer(Enum):
    API = "api"
    ROUTING = "routing"
    RETRIEVAL = "retrieval"
    DATA = "data"
    GENERATION = "generation"
```

---

## TDD Breakdown

### Phase 1: Diagram Component Registry

**Goal**: Define the data model + registry that the UI will consume.

#### 1.1 — `test_diagram_component_dataclass`
- [ ] `DiagramComponent` has all required fields
- [ ] `Layer` enum has all five layers
- [ ] Two components can be compared by id equality

#### 1.2 — `test_component_registry_singleton`
- [ ] A `get_registry()` function returns the same instance every time (singleton)
- [ ] Registry tracks all architecture components
- [ ] Components cover: cli, api_server, query_router, claim_verifier, duckdb, llm, prompt

#### 1.3 — `test_registry_by_layer`
- [ ] `get_components_by_layer(Layer.ROUTING)` returns only routing-layer components
- [ ] Each layer returns at least one component
- [ ] All five layers are represented in the registry

#### 1.4 — `test_component_file_path_resolution`
- [ ] `get_source_snippet(component, n=10)` reads first n lines of the file
- [ ] Returns None if file doesn't exist (graceful)
- [ ] Snippet is returned as string

#### 1.5 — `test_test_status_from_latest_run`
- [ ] Registry can store a `TestStatus` per component
- [ ] Status maps to: pass (green), fail (red), unknown (gray)
- [ ] Component display includes status indicator emoji

---

### Phase 2: Pipeline Tracing

**Goal**: Instrument the query pipeline to emit timing + routing events.

#### 2.1 — `test_pipeline_stage_records_timing`
- [ ] `PipelineStage` records component_id, label, started_at, elapsed_ms
- [ ] Stage has an `output_summary` field
- [ ] Stage can represent a successful run or error state

#### 2.2 — `test_pipeline_trace_assembles_stages`
- [ ] `PipelineTrace.query` stores the original query string
- [ ] `PipelineTrace.stages` is a list of PipelineStage in execution order
- [ ] `PipelineTrace.total_ms` equals sum of stage elapsed_ms values

#### 2.3 — `test_route_type_from_router`
- [ ] Trace records whether router chose `stat_query` or `general_explanation`
- [ ] Route type is set correctly when tracing a real query through the system

#### 2.4 — `test_tracer_context_manager`
- [ ] `@traced(component_id="query-router")` decorator/context manager
- [ ] Automatically records start time, elapsed_ms, output_summary on exit
- [ ] Nested traces work (stage within stage)
- [ ] On exception, error is recorded and re-raised

#### 2.5 — `test_trace_hooks_integrated`
- [ ] Tracing hooks are called in: `cli.answer()`, router.route(), DuckDB query/verification paths
- [ ] Hooks can be disabled via env var `DISABLE_TRACING=true`
- [ ] A full query produces a `PipelineTrace` object

---

### Phase 3: Architecture Diagram UI

**Goal**: Gradio component that renders the architecture diagram with highlighting.

#### 3.1 — `test_diagram_renders_all_layers`
- [ ] `ArchitectureDiagram` Gradio component accepts registry
- [ ] All five layers render in order (API at top → Generation at bottom)
- [ ] Each layer shows its components as cards/blocks

#### 3.2 — `test_highlight_active_components`
- [ ] Calling `diagram.highlight(["query-router", "duckdb"])` highlights those nodes
- [ ] Inactive nodes render dimmed
- [ ] Highlighting is cleared on new query start

#### 3.3 — `test_stage_detail_panel`
- [ ] Clicking a component shows: label, description, file path, source snippet
- [ ] Test status badge shown per component
- [ ] Panel appears in right sidebar or below diagram

#### 3.4 — `test_animate_pipeline_flow`
- [ ] After query submit, stages animate/highlight sequentially (100ms delay)
- [ ] Each stage highlights for 400ms before advancing
- [ ] Final answer text appears after animation completes
- [ ] Animation is skippable by clicking "Skip"

#### 3.5 — `test_timing_display`
- [ ] Per-stage elapsed_ms shown on each node during trace
- [ ] Total time shown in footer: "Pipeline completed in Xms"
- [ ] Route type badge displayed: "⚡ stat_query" or "🔍 general_explanation"

---

### Phase 4: Dashboard Integration

**Goal**: Replace `web_app.py` with tabbed dashboard.

#### 4.1 — `test_dashboard_two_tabs`
- [ ] `Dashboard` Gradio app has tabs: "Query" and "Architecture"
- [ ] Query tab contains existing ChatInterface functionality
- [ ] Architecture tab contains ArchitectureDiagram + detail panel

#### 4.2 — `test_trace_visible_in_arch_tab`
- [ ] After submitting query in Query tab, the trace is accessible
- [ ] Switching to Architecture tab shows last executed path highlighted
- [ ] Multiple queries accumulate as a history list (last 10)

#### 4.3 — `test_dashboard_launch`
- [ ] `uv run python -m baseball_rag.web_app` launches dashboard on port 7860
- [ ] All tabs load without errors

---

## Dependency Graph

```
Phase 1 ──────────────────────────────────────────────────────────────
  └─ Phase 2 (PipelineTrace needs DiagramComponent)                   │
       └─ Phase 3 (Diagram UI needs both data models + tracing hooks) │
            └─ Phase 4 (Dashboard needs all of the above)             │
```

Critical path: 1 → 2 → 3 → 4

---

## File Map

```
src/baseball_rag/
  web_app.py          # refactor to dashboard
  arch/               # NEW
    __init__.py
    components.py     # DiagramComponent, Layer enum, registry
    tracing.py        # PipelineStage, PipelineTrace, @traced decorator
    diagram.py        # ArchitectureDiagram Gradio component

tests/
  test_arch_components.py   # Phase 1
  test_pipeline_tracing.py  # Phase 2
  test_diagram_ui.py        # Phase 3
  test_dashboard.py         # Phase 4
```

---

## Verification Commands

```bash
# Run all new tests
uv run pytest tests/test_arch_*.py tests/test_pipeline*.py tests/test_diagram*.py tests/test_dashboard.py -v

# Full suite with coverage
uv run pytest --cov=baseball_rag --cov-report=term-missing

# Launch locally
uv run python -m baseball_rag.web_app
```
