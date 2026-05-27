# Current Architecture Opportunities Handoff Plan

Status: Completed implementation.

Completed implementation ledger for the four tracks reviewed on 2026-05-26.
`CONTEXT.md` remains the canonical front door. This file records the completed
work and evidence for `/Volumes/Envoy/projects/baseball-rag`.
Implementation landed on branch `disco-current-architecture-opportunities`;
implementation commit `7137788` is recorded in `CONTEXT.md`.

Use the architecture vocabulary from `CONTEXT.md`: a Module has an Interface and
an Implementation; Depth creates Leverage at a Seam; a Shallow Module leaks too
much work to callers; an Adapter is the concrete thing at a Seam; Locality is
the maintenance payoff.

## Scope

Completed tracks, in original risk order:

1. Gradio Query Tab Wiring Module.
2. Query Scope Outcome Interface Module.
3. Architecture Trace Publication Policy Adapter.
4. Retrosheet Source Catalog Audit Module.

Preserve completed Modules unless a public-behavior test proves a real delta:
Routing Decision Evidence, Grounded Database Template Catalog, Context-Aware
Stat Mention Vocabulary, Visible Evidence Presentation, Query Output Contract,
Verified Evidence Read Model, Package-Safe Eval Manifest Metadata Adapter,
Operational verification health checks, and Architecture Test Status Adapter.

Do not reopen the filtered Verification Readiness Ledger or eval-runner ideas.
The review found that health and eval manifest behavior is already recorded as
completed in `CONTEXT.md`.

Evidence and decision basis:

- Gradio Query Tab Wiring Module: current-code evidence from `web_app.py` shows
  the live Query tab still owns callback sequencing, session-key extraction,
  pending/completed component wiring, and stale-turn plumbing outside the
  existing `QuerySession` and `GradioQueryAdapter` Modules. The 2026-05-26
  Browser smoke also confirmed this is visible Query-tab behavior, not just a
  stale helper surface.
- Query Scope Outcome Interface Module: current-code evidence from
  `query_scope.py`, `stat_query.py`, and `service.py` shows callers still
  consume a `QueryScope | StructuredAnswer | None` Interface and stat-query
  player-specific planning makes two passes to preserve single-season ordering.
  This is a fresh Interface-shape finding adjacent to, but not replacing, the
  completed `StatQueryPlanningOutcome` Module.
- Architecture Trace Publication Policy Adapter: current-code evidence from
  `web_app.py`, `QuerySession`, `ArchitectureDiagram`, and `LatestRunStore`
  shows query-to-Architecture publication policy is split. The decision is to
  keep this track narrow and preserve existing failure isolation.
- Retrosheet Source Catalog Audit Module is audit-gated: current-code evidence
  shows Retrosheet schema facts are spread across downloader, DuckDB loading,
  biography vocabulary, and claim verification, but this overlaps completed
  Retrosheet-adjacent Modules. No code changes are authorized for Worker D until the audit cites concrete current friction and records why a catalog Module would add Depth instead of reopening completed work.

## New-Session Operating Contract

- Start with `CONTEXT.md`, then this plan, then the smallest relevant code and
  tests for the worker track.
- Use the tdd skill for code-changing slices: write one public-behavior RED,
  make the smallest GREEN change, then refactor while green.
- Use subagents wherever possible. Run a code-review subagent after every worker task and after final integration.
- Workers are not alone in the codebase. They must not revert edits made by
  other workers; they should adapt to existing changes.
- DuckDB/Lahman remains the primary factual/stat authority.
- Retrosheet remains optional secondary consensus evidence for biography stat
  claims, not a replacement authority for all query paths.
- Do not add a stored corpus, vector index, or Chroma replacement.
- Preserve CLI, HTTP Adapter, Gradio, source JSON, SQL, metadata, review, and
  eval payload shapes unless a public-behavior test proves an intentional
  change.
- For UI-affecting changes, start the local UI with `uv run baseball-rag-ui`,
  open `http://127.0.0.1:7861/` in the Codex in-app Browser, make the Browser
  visible, run `who had the most RBIs in 1962`, confirm rows, source JSON, SQL,
  enabled Ask button state, and Architecture tab trace visibility, and keep the
  dev server running.
- The task is not complete until docs are updated, review is complete, changes
  are committed, and any unstaged changes are explained.
- If the branch is pushed to GitHub, watch CI until it is green.

## Subagent Work Order

Suggested branch: `disco/current-architecture-opportunities`.

| Wave | Owner | Scope | Parallelism |
| --- | --- | --- | --- |
| 0 | Coordinator | Re-check `CONTEXT.md`, branch, worktree, and Browser/server state | First |
| 1 | Worker A | Gradio Query Tab Wiring Module | Can run with Worker B and Worker D audit |
| 1 | Worker B | Query Scope Outcome Interface Module | Can run with Worker A and Worker D audit |
| 1 | Worker D | Retrosheet Source Catalog Audit Module | Start as read-only or disjoint catalog prep |
| 2 | Worker C | Architecture Trace Publication Policy Adapter | Run after Worker A if both touch `web_app.py` |
| 3 | Coordinator | Integration, docs ledger, Browser smoke, review subagent, commit | Last |

Each worker final report should include changed files, tests run, public
behavior preserved, review risks, and any follow-up that should remain open.

## Worker A: Gradio Query Tab Wiring Module

### Files

- `src/baseball_rag/web_app.py`
- `src/baseball_rag/ui/gradio_adapter.py`
- `src/baseball_rag/ui/query_session.py`
- `tests/test_dashboard.py`
- `tests/test_gradio_query_adapter.py`
- `tests/test_query_session.py`
- `tests/test_query_transaction.py`
- `tests/test_browser_contract.py`

### Problem

`QuerySession` and `GradioQueryAdapter` have useful Depth, but `web_app.py`
still owns callback sequencing, session-key extraction, pending/completed
wiring, `BegunQuery` plumbing, and stale-turn output mapping. The Interface for
the live Query tab is therefore split between layout code and adapter code.

Deletion test: deleting `GradioQueryAdapter` would push real Gradio output
ordering back into callers, so it earns its keep. Deleting the inline callback
choreography in `build_dashboard()` would mostly move that wiring complexity to
the next caller, which means this is the Shallow part.

### Target Shape

Create a browser-facing Query tab wiring Module that owns the callback order,
session-key extraction, pending/completed output mapping, stale-turn behavior,
and component map validation. Keep `QuerySession` as the adapter-neutral query
lifecycle Module and `GradioQueryAdapter` as the output-order Adapter.

Do not redesign the UI. `build_dashboard()` should become more layout-oriented
and delegate the query wiring through a small Interface.

### TDD Slices

1. RED: add or tighten a dashboard test proving the Query tab can be wired from
   one Interface and exposes the same pending and completed component ids.
   GREEN: introduce the wiring Module without changing visible behavior.
2. RED: prove Gradio `request.session_hash` is still used for latest-turn and
   Architecture publication session keys. GREEN: move session-key extraction
   behind the wiring Module.
3. RED: prove stale completion still returns no-op updates and never executes
   the backend after a stale snapshot. GREEN: route stale-turn plumbing through
   the wiring Module.
4. RED: prove the live default query still updates chat, answer, rows, sources,
   SQL, conversation state, and Ask button interactivity in the same order.
   GREEN: remove duplicate inline callback construction from `build_dashboard()`.

### Verification

```bash
uv run pytest tests/test_dashboard.py tests/test_gradio_query_adapter.py tests/test_query_session.py tests/test_query_transaction.py tests/test_browser_contract.py -q
```

Run the Browser smoke if any Query tab wiring changed.

### Done Criteria

- `build_dashboard()` reads primarily as UI layout plus a call into the Query
  tab wiring Module.
- The Query tab output contract remains unchanged.
- Existing compatibility wrappers keep current behavior or are explicitly
  routed through the new Interface.
- A code-review subagent finds no callback ordering, session, or stale-write
  regression.

## Worker B: Query Scope Outcome Interface Module

### Files

- `src/baseball_rag/query_scope.py`
- `src/baseball_rag/stat_query.py`
- `src/baseball_rag/service.py`
- `tests/test_query_scope.py`
- `tests/test_queries.py`
- `tests/test_request_execution.py`
- `tests/test_api.py`

### Problem

`resolve_query_scope(...)` returns `QueryScope | StructuredAnswer | None`. That
Interface makes callers understand answerable scope, no-scope, unsupported
answer construction, coverage validation ordering, and single-season policy.
`stat_query.py` calls it twice for player-specific lookups so it can reject
multi-season player queries before coverage no-data behavior.

Deletion test: `QueryScope` itself earns its keep because range, decade,
relative-year, reversed-range, and manifest-coverage behavior would reappear in
multiple callers. The Shallow part is the union-shaped Interface.

### Target Shape

Deepen the scope Seam into an explicit outcome/read model with named states:
answerable scope, no scope, and unsupported answer. It should also be able to
enforce a single-season requirement without a caller making two passes.

This does not replace the completed `StatQueryPlanningOutcome` Module. It makes
the scope Interface deeper so stat-query planning and grounded database
single-season planning do less policy work.

### TDD Slices

1. RED: add a scope test that consumes the new outcome Interface for an
   answerable single season and no-scope career query. GREEN: introduce the
   read model while preserving `resolve_query_scope(...)` or using it as a thin
   compatibility Adapter during migration.
2. RED: add a test for player-specific range policy proving the caller does not
   need a double scope pass. GREEN: move single-season requirement into the
   scope outcome Module.
3. RED: prove bare current-century decades and reversed ranges still return the
   same unsupported reason and answer text. GREEN: migrate ambiguity handling.
4. RED: prove out-of-coverage years still use manifest coverage and return the
   same no-data shape through API review behavior. GREEN: migrate coverage
   validation without payload drift.
5. RED: prove grounded database single-season planning still extracts a year for
   `GroundedDatabaseQuestionCase` without changing route or answer behavior.
   GREEN: consume the new scope outcome there.

### Verification

```bash
uv run pytest tests/test_query_scope.py tests/test_queries.py tests/test_request_execution.py tests/test_api.py -q
```

Run the deterministic eval gate if unsupported reasons, answer text, or route
outcomes change:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Done Criteria

- Callers no longer inspect a three-way union for normal scope policy.
- Player-specific single-season policy has Locality in the scope Module.
- API and eval payloads preserve existing unsupported/no-data semantics.
- A code-review subagent finds no coverage, decade, or reversed-range drift.

## Worker C: Architecture Trace Publication Policy Adapter

### Files

- `src/baseball_rag/web_app.py`
- `src/baseball_rag/ui/query_session.py`
- `src/baseball_rag/arch/diagram.py`
- `src/baseball_rag/arch/read_model.py`
- `tests/test_dashboard.py`
- `tests/test_diagram_ui.py`
- `tests/test_query_session.py`

### Problem

Query-to-Architecture publication is split across recorder helpers in
`web_app.py`, the `QuerySession` record callback, `ArchitectureDiagram`, and
`LatestRunStore`. Failure isolation already exists, so do not claim it is
missing. The remaining friction is that animate-vs-record policy and
session-scoped latest-run publication do not live behind one named Adapter.

Deletion test: deleting `LatestRunStore` would move session latest-run state
into the diagram, so it has Depth. Deleting the recorder helper policy would
spread publication choices across wrappers and dashboard wiring.

### Target Shape

Introduce a small Architecture Trace Publication Policy Adapter that owns how a
completed `RequestExecution` is published to the Architecture Explorer. It can
choose animation, static record, session key, and exception handling, while
`ArchitectureDiagram` remains the rendering Adapter.

Coordinate with Worker A because both may touch `web_app.py`.

### TDD Slices

1. RED: add a pure unit test proving the publication Adapter can publish in
   record mode with a session key and update the latest Architecture read model.
   GREEN: extract only the current record behavior.
2. RED: prove animation mode still calls the diagram animation path. GREEN:
   move animate-vs-record branching behind the Adapter.
3. RED: prove diagram publication exceptions are logged and do not fail the
   Query tab completion. GREEN: preserve the current failure-isolation behavior
   inside the Adapter.
4. RED: prove the Architecture tab still shows the latest path for the current
   browser session after a Query tab run. GREEN: wire `QuerySession` through the
   publication Adapter.

### Verification

```bash
uv run pytest tests/test_dashboard.py tests/test_diagram_ui.py tests/test_query_session.py -q
```

Run Browser smoke and inspect the Architecture tab if dashboard wiring changed.

### Done Criteria

- Publication policy is named and testable without walking dashboard closure
  internals.
- `ArchitectureDiagram` stays focused on rendering and latest-run storage.
- Query tab failures do not appear when Architecture publication fails.
- A code-review subagent finds no session leakage or trace-history regression.

## Worker D: Retrosheet Source Catalog Audit Module

### Files

- `src/baseball_rag/db/secondary_sources/retrosheet.py`
- `src/baseball_rag/db/duckdb_schema.py`
- `src/baseball_rag/db/biography_stat_vocabulary.py`
- `src/baseball_rag/db/player_stat_claims.py`
- `tests/test_retrosheet_downloader.py`
- `tests/test_retrosheet_duckdb_schema.py`
- `tests/test_player_stat_claims_consensus.py`

### Problem

Retrosheet archive names, CSV names, DuckDB table names, stat-table identity,
load filters, id-column guesses, date/year parsing, and stat column candidates
are spread across downloader, optional DuckDB loading, biography vocabulary, and
claim verification.

Deletion test: deleting the downloader catalog would not remove runtime
Retrosheet complexity; table and column assumptions would remain scattered in
verification code. This may be a real internal Seam, but it overlaps completed
Claim Verification Evidence, Source Provenance, Biography Stat Claim
Vocabulary, and Context-Aware Stat Mention work.

### Target Shape

Start with an audit. If the audit finds only low churn, record that no code
deepening is needed yet. If the audit finds repeated schema assumptions that are
already causing tests or implementation friction, introduce one Retrosheet
Source Catalog Module consumed by download, optional load, provenance, and claim
evidence paths.

No code changes are authorized for Worker D until the audit cites concrete current friction and explains why a catalog Module would add Depth instead of reopening completed Claim Verification Evidence, Source Provenance, Biography Stat Claim Vocabulary, or Context-Aware Stat Mention work.

Preserve Retrosheet as optional secondary consensus evidence. Do not broaden it
into a general factual authority.

### TDD Slices

1. RED: add an audit/doc-contract test or focused unit test listing the current
   Retrosheet archive/table/stat-column facts in one expected place. GREEN:
   either document the existing spread as accepted or introduce a catalog read
   model.
2. If implementing a catalog, RED: prove downloader `ARCHIVES` and optional
   DuckDB loading consume the same archive/table facts. GREEN: move archive and
   table metadata behind the catalog.
3. RED: prove claim verification consumes the same player id, year, filter, and
   stat-column rules for real Retrosheet daily-log headers. GREEN: move only
   shared schema facts behind the catalog.
4. RED: prove missing Retrosheet files/tables still degrade to optional
   unsupported secondary evidence while Lahman primary verification remains
   unchanged. GREEN: preserve all current public rows, warnings, SQL, and
   consensus statuses.

### Verification

```bash
uv run pytest tests/test_retrosheet_downloader.py tests/test_retrosheet_duckdb_schema.py tests/test_player_stat_claims_consensus.py -q
```

Run broader biography and provenance tests if public source payloads change:

```bash
uv run pytest tests/test_player_bio_query.py tests/test_provenance.py tests/test_answer_presentation.py -q
```

### Done Criteria

- The final state is either a documented audit decision or a catalog Module with
  clear Leverage.
- DuckDB/Lahman remains the primary factual/stat authority.
- Retrosheet remains optional and failure-tolerant.
- A code-review subagent finds no source-authority or consensus-status drift.

## Integration Coordinator

### Files

- `CONTEXT.md`
- `docs/architecture.md`
- `docs/architecture-current-opportunities-handoff-plan.md`
- `docs/api.md` only if public API payload docs change.
- `tests/test_project_cleanup.py`

### Duties

1. Keep this plan current while workers land changes.
2. After each worker, run a code-review subagent and address actionable
   findings before starting the next conflicting track.
3. Move completed opportunities from `CONTEXT.md` Current Opportunities to
   Completed Modules with commit hashes after the final commit.
4. Preserve archived ledgers as historical records; do not edit completed
   archive docs unless a doc-contract test proves stale current claims.
5. Run the focused worker commands, then:

```bash
uv run ruff check src/ tests/ evals/
uv run mypy src/
uv run pytest -q
```

6. If eval-facing payloads or unsupported behavior changed, run:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

7. Run Browser smoke for UI-affecting changes and keep the server running.
8. Commit the finished work and explain any unstaged changes.

## Implementation Ledger

### Worker A: Gradio Query Tab Wiring Module

Status: Completed.

Implemented `src/baseball_rag/ui/query_tab_wiring.py` as the browser-facing
Query tab wiring Module. It owns Gradio callback registration, session-hash
extraction, pending/completed component mapping, stale completion no-ops, and
component id publication. `build_dashboard()` now stays layout-oriented and
delegates Query tab choreography through `GradioQueryTabWiring`.

Public behavior preserved: callback API names remain `begin_query` and
`on_query`; pending/completed/stale output order still comes from
`GradioQueryAdapter`; stale same-session completions no-op before backend
execution; Architecture publication still receives the Gradio session key.

Verification:

```bash
uv run pytest tests/test_dashboard.py tests/test_gradio_query_adapter.py tests/test_query_session.py tests/test_query_transaction.py tests/test_browser_contract.py tests/test_query_tab_wiring.py -q
```

### Worker B: Query Scope Outcome Interface Module

Status: Completed.

Implemented `QueryScopeOutcome` and `resolve_query_scope_outcome(...)` in
`src/baseball_rag/query_scope.py`. The outcome names answerable scope, no-scope,
and unsupported answer states and can enforce single-season policy before
coverage validation. `stat_query.py` now consumes the outcome once for
player-specific planning instead of making a double scope pass, and grounded
database year extraction consumes the same outcome without route or answer
drift.

Public behavior preserved: bare current-century decades, reversed ranges,
manifest coverage no-data answers, player-specific multi-season ambiguity, API
review payloads, and grounded database single-season planning.

Verification:

```bash
uv run pytest tests/test_query_scope.py tests/test_queries.py tests/test_request_execution.py tests/test_api.py -q
```

### Worker C: Architecture Trace Publication Policy Adapter

Status: Completed.

Implemented `src/baseball_rag/arch/trace_publication.py` as
`ArchitectureTracePublisher`. It owns animate-vs-record policy, session-key
publication into the Architecture latest-run read model, and exception logging
without failing Query tab completion. `ArchitectureDiagram` remains the
rendering Adapter and `LatestRunStore` remains the session-scoped latest-run
store.

Public behavior preserved: `respond()` and `respond_structured()` animate
traces, Query tab completions record without mutating Architecture-tab
components, session-scoped refresh still shows the current browser's latest
trace, and diagram failures remain isolated.

Verification:

```bash
uv run pytest tests/test_dashboard.py tests/test_diagram_ui.py tests/test_query_session.py tests/test_architecture_trace_publication.py -q
```

### Worker D: Retrosheet Source Catalog Audit Module

Status: Completed as audit; no code catalog implemented.

The audit found spread but no current friction that justifies a Retrosheet
catalog Module. Keep no catalog Module until concrete friction appears.
Downloader archive facts, optional DuckDB table loading,
biography stat vocabulary, and claim verification each own distinct
responsibilities, and existing tests cover the risky optional-secondary-source
contracts. No catalog should be added until concrete churn or drift appears.

Public behavior preserved: Lahman/DuckDB remains the primary factual/stat
authority; Retrosheet remains optional secondary consensus evidence for
biography stat claims; missing Retrosheet sources degrade without source
authority, consensus-status, SQL, params, warning, or payload drift.

Verification:

```bash
uv run pytest tests/test_retrosheet_downloader.py tests/test_retrosheet_duckdb_schema.py tests/test_player_stat_claims_consensus.py -q
```

### Integration Verification

Focused commands run during implementation:

```bash
uv run pytest tests/test_query_scope.py tests/test_query_tab_wiring.py tests/test_architecture_trace_publication.py -q
uv run pytest tests/test_dashboard.py tests/test_gradio_query_adapter.py tests/test_query_session.py tests/test_query_transaction.py tests/test_browser_contract.py tests/test_query_tab_wiring.py tests/test_diagram_ui.py tests/test_architecture_trace_publication.py -q
uv run pytest tests/test_query_scope.py tests/test_queries.py tests/test_request_execution.py tests/test_api.py -q
```

Final required commands, Browser smoke, code-review subagent results, and commit
evidence belong in the final coordinator report.

## New-Session Handoff Prompt

Use this prompt to continue in a new Codex session:

```text
You are in /Volumes/Envoy/projects/baseball-rag. Follow AGENTS.md: use the tdd
skill for dev work, use subagents wherever possible, run a code-review subagent
after every task, commit before finishing, and if you push, verify CI is green.

Start by reading CONTEXT.md and docs/architecture-current-opportunities-handoff-plan.md.
The completed ledger has four tracks:

1. Worker A: Gradio Query Tab Wiring Module.
2. Worker B: Query Scope Outcome Interface Module.
3. Worker C: Architecture Trace Publication Policy Adapter.
4. Worker D: Retrosheet Source Catalog Audit Module.

Do not reopen these tracks without fresh public-behavior evidence or an explicit
product decision. For any new follow-up, spawn subagents for disjoint work, use
TDD for code-changing slices, preserve public behavior, and report changed files
plus tests run. After each worker, run a code-review subagent and address
findings.

For UI-affecting work, start or reuse `uv run baseball-rag-ui`, open
http://127.0.0.1:7861/ in the Codex in-app Browser, make the Browser visible,
run `who had the most RBIs in 1962`, verify rows/source JSON/SQL/Ask button
state, check the Architecture tab, and keep the dev server running.

Finish by updating CONTEXT.md and the handoff ledger, running focused tests plus
`uv run ruff check src/ tests/ evals/`, `uv run mypy src/`, and
`uv run pytest -q`, then commit. If eval-facing behavior changed, also run the
deterministic eval gate. Explain any unstaged changes.
```
