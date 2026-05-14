# Architecture Deepening Handoff

These plans turn the architecture review suggestions into implementation-ready
handoffs. Each task should preserve current user-visible behavior unless the
task explicitly says otherwise.

Selected path: implement the plans from `docs/architecture-deepening-handoff.md`.

## Shared Implementation Rules

- Use TDD with vertical slices: one behavior test, minimal implementation, then
  refactor while green.
- Use worker subagents where possible, with disjoint write scopes.
- Run a code review subagent after each task.
- Commit completed changes and explain any unstaged changes.
- If a branch is pushed to GitHub, verify CI is green before calling the task
  done.
- After implementation, run the Gradio UI smoke test: start
  `uv run baseball-rag-ui`, open `http://127.0.0.1:7861/` in the Codex in-app
  Browser, run the default query, and keep the dev server running.

## 1. Freeform Planning And Routing Ownership

### Summary

Deepen the freeform planning/routing Module so `query_router.route()` delegates
deterministic freeform ownership decisions instead of coordinating template
detection and precedence inline.

### Key Changes

- Add an internal routing ownership helper, likely
  `baseball_rag.routing.freeform_ownership`.
- Move "should deterministic freeform own this question?" logic behind that
  helper.
- Keep DuckDB/freeform planning and execution in
  `baseball_rag.db.freeform_runtime`.
- Preserve facade exports from `baseball_rag.db.freeform`, including
  `plan_query`, `query`, `can_plan_deterministically`, and
  `should_route_deterministic_freeform`.
- Do not remove private helper re-exports in this PR.

### Worker Split

- **Worker A: Routing worker**
  - Write scope: `src/baseball_rag/routing/query_router.py`, the new routing
    ownership helper, and routing tests.
  - Refactor route ownership only. Do not edit SQL or freeform execution.
- **Worker B: Freeform compatibility worker**
  - Write scope: `src/baseball_rag/db/freeform*.py` and freeform tests.
  - Preserve facade behavior and shift tests toward public planning behavior.
- **Review subagent**
  - Check import cycles, behavior drift, facade compatibility, and test
    coupling.

### Test Plan

- `career pitching wins leaders` routes to `FreeformQueryCase`.
- `career home run leaders` stays `StatQueryCase`.
- `best ERA in 1968` stays `StatQueryCase`.
- `who is in the 500 club` routes to `FreeformQueryCase` and remains ambiguous
  unsupported.
- Run:
  - `uv run pytest tests/test_router.py tests/test_freeform.py -q -m "not llm"`
  - `uv run pytest tests/test_api.py::TestApi::test_query_endpoint_preserves_ambiguous_freeform_unsupported_reason -q`
  - `uv run pytest -q`

### Assumptions

- Preserve facade is locked in for this PR.
- No external API, CLI, UI, or answer payload changes.
- The freeform compatibility facade may be revisited in a later cleanup PR only
  after the new routing ownership seam is stable.

## 2. Biography Claim Verification Presentation

### Summary

Deepen the biography claim verification Module by moving Lahman/Retrosheet
consensus presentation, scorecard wording, warning shaping, and evidence-row
shaping out of `service.py`.

### Key Changes

- Add a verification presentation/read-model layer inside or beside
  `baseball_rag.db.player_stat_claims`.
- Let `service.py` orchestrate player resolution, LLM biography JSON, and claim
  verification, then ask the verifier Module for answer-ready evidence.
- Preserve current verification semantics and response shape.
- Keep `StructuredAnswer` fields unchanged.

### Worker Split

- **Worker A: Verifier read-model worker**
  - Write scope: `src/baseball_rag/db/player_stat_claims.py` or a new adjacent
    Module, plus verifier tests.
  - Move consensus category summary, rows, warnings, and scorecard text behind
    the verifier Module.
- **Worker B: Service integration worker**
  - Write scope: `src/baseball_rag/service.py` and player biography tests.
  - Replace service-local consensus formatting with calls into the verifier
    presentation layer.
- **Review subagent**
  - Check that `service.py` no longer depends on Lahman/Retrosheet row-key
    details and that answer payloads remain stable.

### Test Plan

- Existing player biography claim tests still pass.
- Add behavior tests asserting:
  - Verified claims produce the same visible scorecard.
  - Contradicted claims produce the same warnings and evidence rows.
  - Mixed Lahman/Retrosheet statuses keep current metadata shape.
- Run:
  - `uv run pytest tests/test_player_bio_query.py tests/test_player_stat_claims_consensus.py -q`
  - `uv run pytest tests/test_request_execution.py -q`
  - `uv run pytest -q`

### Assumptions

- Do not change verification rules.
- Do not change the LLM biography JSON contract.
- Do not alter public API response shape.

## 3. Deterministic Stat SQL Execution

### Summary

Deepen deterministic stat execution by carrying `StatQueryPlan` through the
execution path, reducing the shallow `execute_stat_query(...)` argument surface.

### Key Changes

- Make `StatQueryPlan` the primary internal execution input for stat queries.
- Hide table-specific SQL choices behind the deterministic stat Module.
- Keep existing compatibility adapters such as `get_stat_leaders`,
  `get_career_stat_leaders`, and `get_player_stat` working.
- Preserve stat registry ownership of whitelisted stat expressions and sample
  guards.

### Worker Split

- **Worker A: Plan execution worker**
  - Write scope: `src/baseball_rag/stat_query.py` and stat-query tests.
  - Ensure public answer behavior flows plan to execute to answer without
    re-deciding route facts.
- **Worker B: Query internals worker**
  - Write scope: `src/baseball_rag/db/queries.py` and query tests.
  - Refactor table-specific SQL execution behind plan-aware internals while
    keeping compatibility adapters stable.
- **Review subagent**
  - Check no SQL behavior drift, especially AVG/OPS/ERA/WHIP sample guards and
    sort direction.

### Test Plan

- Existing stat query tests still pass.
- Add or confirm behavior coverage for:
  - batting leaderboard
  - pitching lower-is-better leaderboard
  - fielding position leaderboard
  - player-specific lookup
  - no-data and ambiguous outcomes
- Run:
  - `uv run pytest tests/test_queries.py tests/test_stat_leaders_range_db.py tests/test_cli_stat_query_integration.py -q`
  - `uv run pytest tests/test_api.py::TestApi::test_query_endpoint_preserves_pitching_rate_stat_provenance -q`
  - `uv run pytest -q`

### Assumptions

- No external answer shape changes.
- Compatibility adapters remain available.
- SQL provenance remains visible and parameterized.

## 4. Architecture Explorer Read Model Versus Gradio Rendering

### Summary

Separate Architecture Explorer state/read-model behavior from Gradio rendering
so tests can verify trace and latest-run behavior without inspecting HTML and
Gradio config as the primary interface.

### Key Changes

- Add an Architecture Explorer read-model Module that owns:
  - latest run per session
  - active path/component ids
  - diagnostics/warnings/errors
  - trace summary values
  - test status mapping
- Keep `ArchitectureDiagram` as the Gradio Adapter that renders the read model.
- Update stale component descriptions to match the current four-route
  architecture.
- Preserve current UI behavior and visual output unless a test-approved behavior
  change is explicitly requested.

### Worker Split

- **Worker A: Read-model worker**
  - Write scope: a new/read-model Module under `src/baseball_rag/arch/` and
    focused model tests.
  - Extract latest-run and active-path state from `ArchitectureDiagram`.
- **Worker B: Gradio adapter worker**
  - Write scope: `src/baseball_rag/arch/diagram.py`,
    `src/baseball_rag/web_app.py`, and dashboard tests.
  - Wire the read model into existing rendering and event refresh behavior.
- **Review subagent**
  - Check session isolation, trace history behavior, UI smoke expectations, and
    stale route/component language.

### Test Plan

- Add pure read-model tests for:
  - recording latest execution
  - session-specific latest run lookup
  - active component path extraction
  - unsupported/warning diagnostics
- Keep a smaller Gradio smoke layer for:
  - Query and Architecture tabs exist
  - latest trace refresh updates diagram/footer
  - developer test button remains wired
- Run:
  - `uv run pytest tests/test_diagram_ui.py tests/test_dashboard.py tests/test_arch_components.py -q`
  - `uv run pytest tests/test_pipeline_tracing.py tests/test_pipeline_tracing_integration.py -q`
  - `uv run pytest -q`

### Assumptions

- UI behavior remains functionally unchanged.
- HTML/CSS may move, but the user-facing dashboard stays visually equivalent.
- The stale `docs/architecture-explorer-plan.md` should not drive
  implementation decisions over current runtime code.
