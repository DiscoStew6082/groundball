# Architecture Deepening Handoff

This document tracks the architecture review suggestions that were turned into
implementation work. All four tasks are now complete on this branch. User-visible
behavior, DuckDB provenance, compatibility adapters, and API/CLI/UI response
shapes were preserved.

Selected path implemented: the plans from
`docs/architecture-deepening-handoff.md`.

## Implementation Status

- **Complete:** Freeform planning and routing ownership.
- **Complete:** Biography claim verification presentation.
- **Complete:** Deterministic stat SQL execution.
- **Complete:** Architecture Explorer read model versus Gradio rendering.
- **Committed:** `6ad7e20 Route deterministic freeform via ownership helper`
  and `58e38a7 Deepen architecture ownership modules`.
- **Final verification:** `uv run pytest -q` passed with `505 passed`.
- **UI smoke:** `uv run baseball-rag-ui` was started, the Codex in-app Browser
  opened `http://127.0.0.1:7861/`, and the default query returned Davis, Tommy
  with rows, sources, and SQL. The dev server was left running.
- **GitHub:** The branch was not pushed, so CI was not triggered.

## Rules Used During Implementation

- TDD with vertical slices: one behavior test, minimal implementation, then
  refactor while green.
- Worker subagents were used where possible, with disjoint write scopes.
- A code review subagent reviewed the integrated implementation.
- Completed changes were committed, and no unstaged changes remained.
- The branch was not pushed to GitHub, so no CI verification was required.
- After implementation, the Gradio UI smoke test was run: start
  `uv run baseball-rag-ui`, open `http://127.0.0.1:7861/` in the Codex in-app
  Browser, run the default query, and keep the dev server running.

## 1. Freeform Planning And Routing Ownership

**Status: complete.**

### Summary

Deepen the freeform planning/routing Module so `query_router.route()` delegates
deterministic freeform ownership decisions instead of coordinating template
detection and precedence inline.

### Implemented Changes

- Added internal routing ownership helper
  `baseball_rag.routing.freeform_ownership`.
- `query_router.route()` now asks the helper whether deterministic freeform owns
  a question, including optional competing stat precedence.
- DuckDB/freeform planning and execution remain in
  `baseball_rag.db.freeform_runtime`.
- Preserved facade exports from `baseball_rag.db.freeform`, including
  `plan_query`, `query`, `can_plan_deterministically`, and
  `should_route_deterministic_freeform`.
- Private helper re-exports were not removed.

### Implementation Notes

- Routing behavior coverage now includes ambiguous `500 club` ownership.
- Freeform facade compatibility is covered through public planning/query
  behavior instead of private helper shape.
- The review subagent found no issues in this slice.

### Verified Behavior

- `career pitching wins leaders` routes to `FreeformQueryCase`.
- `career home run leaders` stays `StatQueryCase`.
- `best ERA in 1968` stays `StatQueryCase`.
- `who is in the 500 club` routes to `FreeformQueryCase` and remains ambiguous
  unsupported.
- `uv run pytest tests/test_router.py tests/test_freeform.py -q -m "not llm"`
  passed.
- `uv run pytest tests/test_api.py::TestApi::test_query_endpoint_preserves_ambiguous_freeform_unsupported_reason -q`
  passed.

### Assumptions

- Preserve facade remains locked in for this PR.
- No external API, CLI, UI, or answer payload changes.
- The freeform compatibility facade may be revisited in a later cleanup PR only
  after the new routing ownership seam is stable.

## 2. Biography Claim Verification Presentation

**Status: complete.**

### Summary

Deepen the biography claim verification Module by moving Lahman/Retrosheet
consensus presentation, scorecard wording, warning shaping, and evidence-row
shaping out of `service.py`.

### Implemented Changes

- Added verifier presentation/read-model shaping in
  `baseball_rag.db.player_stat_claims`.
- `service.py` now orchestrates player resolution, LLM biography JSON, and claim
  verification, then asks the verifier layer for answer-ready evidence.
- Moved consensus category summary, scorecard text, warning shaping, source
  detail, SQL/tables, data manifest, and evidence row enrichment out of
  `service.py`.
- Preserved verification semantics, `StructuredAnswer` fields, metadata shape,
  warnings, and source rows.

### Implementation Notes

- Public biography answer shape remains stable.
- The verifier layer now owns Lahman/Retrosheet presentation vocabulary and row
  keys.
- The integrated review found no response-shape or import-cycle issues in this
  slice.

### Verified Behavior

- Existing player biography claim tests pass.
- Verified claims preserve the visible scorecard.
- Contradicted claims preserve warnings and evidence rows.
- Mixed Lahman/Retrosheet statuses preserve metadata shape.
- `uv run pytest tests/test_player_bio_query.py tests/test_player_stat_claims_consensus.py -q`
  passed.
- `uv run pytest tests/test_request_execution.py -q` passed.

### Assumptions

- Do not change verification rules.
- Do not change the LLM biography JSON contract.
- Do not alter public API response shape.

## 3. Deterministic Stat SQL Execution

**Status: complete.**

### Summary

Deepen deterministic stat execution by carrying `StatQueryPlan` through the
execution path, reducing the shallow `execute_stat_query(...)` argument surface.

### Implemented Changes

- Moved `StatQueryPlan` into `baseball_rag.db.queries` and made it the primary
  internal execution input for deterministic stat queries.
- Added `execute_stat_query_plan(...)` for plan-aware execution.
- Kept `execute_stat_query(...)` as a compatibility adapter that translates the
  old optional-argument surface into a plan.
- Hid table-specific SQL choices behind the DB query module.
- Kept existing compatibility adapters such as `get_stat_leaders`,
  `get_career_stat_leaders`, and `get_player_stat` working.
- Preserved stat registry ownership of whitelisted stat expressions and sample
  guards.

### Implementation Notes

- `stat_query.py` now plans once, executes that plan, then formats the answer
  from the executed result.
- The CLI test that previously patched the shallow adapter now verifies the plan
  boundary instead.
- Review found no SQL guard, sort-direction, or provenance drift.

### Verified Behavior

- Existing stat query tests pass.
- Behavior coverage includes batting leaderboard, pitching lower-is-better
  leaderboard, fielding position leaderboard, player-specific lookup, no-data
  outcomes, and ambiguous outcomes.
- `uv run pytest tests/test_queries.py tests/test_stat_leaders_range_db.py tests/test_cli_stat_query_integration.py -q`
  passed.
- `uv run pytest tests/test_api.py::TestApi::test_query_endpoint_preserves_pitching_rate_stat_provenance -q`
  passed.

### Assumptions

- No external answer shape changes.
- Compatibility adapters remain available.
- SQL provenance remains visible and parameterized.

## 4. Architecture Explorer Read Model Versus Gradio Rendering

**Status: complete.**

### Summary

Separate Architecture Explorer state/read-model behavior from Gradio rendering
so tests can verify trace and latest-run behavior without inspecting HTML and
Gradio config as the primary interface.

### Implemented Changes

- Added `baseball_rag.arch.read_model`, a pure Architecture Explorer read-model
  module that owns:
  - latest run per session
  - active path/component ids
  - diagnostics/warnings/errors
  - trace summary values
  - row counts and status text
- Kept `ArchitectureDiagram` as the Gradio adapter that renders the read model.
- Updated stale component descriptions to match the current four-route
  architecture.
- Preserved current UI behavior and visual output.

### Implementation Notes

- Read-model tests now cover latest execution, session isolation, active
  component path extraction, unsupported/warning diagnostics, and legacy reset
  behavior.
- The review subagent found one stale sessionless latest-run reset bug; it was
  fixed and covered with a regression test.
- `web_app.py` did not need changes.

### Verified Behavior

- Query and Architecture tabs still exist.
- Latest trace refresh updates diagram/footer.
- Developer test button remains wired.
- Session-specific latest trace lookup remains isolated.
- Legacy reset paths do not resurrect stale read-model state.
- `uv run pytest tests/test_diagram_ui.py tests/test_dashboard.py tests/test_arch_components.py -q`
  passed.
- `uv run pytest tests/test_pipeline_tracing.py tests/test_pipeline_tracing_integration.py -q`
  passed.

### Assumptions

- UI behavior remains functionally unchanged.
- HTML/CSS may move, but the user-facing dashboard stays visually equivalent.
- The stale `docs/architecture-explorer-plan.md` should not drive
  implementation decisions over current runtime code.
