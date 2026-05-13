# Architecture Deepening Worker Plan

## Goal

Provide a step-by-step implementation handoff for deepening Baseball RAG's
current modules while preserving product behavior first. This plan breaks the
eight reviewed architecture suggestions into sequential phases that worker
agents and subagents can execute with TDD.

Hand this document to a new Codex conversation as the starting prompt. The
coordinator should read this plan, inspect the current code, create a phase
checklist, delegate disjoint work to worker agents when useful, run a
code-review subagent after every phase, and commit each completed phase before
starting the next one.

## Architecture Vocabulary

Use these terms consistently in implementation notes, tests, and review reports:

- **Module**: anything with an interface and an implementation.
- **Interface**: everything callers must know to use a module correctly,
  including invariants, errors, ordering, configuration, and performance.
- **Implementation**: the code inside a module.
- **Depth**: leverage at the interface. A deep module hides meaningful behavior
  behind a small interface.
- **Seam**: where an interface lives; a place behavior can be altered without
  editing in place.
- **Adapter**: a concrete thing satisfying an interface at a seam.
- **Leverage**: what callers get from depth.
- **Locality**: what maintainers get from depth.

Apply the deletion test before introducing or keeping a module: if deleting the
module makes complexity vanish, it was shallow; if complexity reappears across
callers, it was earning its keep.

## Operating Rules

- Use the TDD skill for implementation work. Write one behavior-focused tracer
  test, make it pass, then continue vertically. Do not write all tests first.
- Tests should verify behavior through public interfaces, not private helper
  shape.
- Use subagents wherever possible. The coordinator owns sequencing and final
  integration; worker agents own disjoint write sets.
- Run a code-review subagent after every phase. Do not commit until review
  findings are addressed or explicitly deferred in the phase notes.
- Preserve user changes. If the worktree is dirty, identify unrelated changes
  before editing and never revert them without explicit instruction.
- Commit each completed phase before starting the next phase.
- Explain any remaining unstaged changes at the end of every phase.
- If a branch is pushed to GitHub, wait for CI to come back green before
  declaring pushed work complete.

## Coordinator Workflow

Run this loop for each phase:

1. Check `git status --short --branch` and identify unrelated user changes.
2. Read the phase section and inspect the listed files.
3. Ask explorer subagents only the narrow questions that block the next design
   decision.
4. Create a short phase checklist.
5. Delegate implementation to worker agents only when write sets are disjoint.
6. Run one TDD tracer cycle locally or through the owning worker.
7. Integrate worker changes and run targeted tests.
8. Run a code-review subagent.
9. Address blocking findings or record an explicit deferral.
10. Run the phase verification commands.
11. Check `git status --short`.
12. Commit with a message naming the deepened module.

## Subagent Model

Use these roles consistently:

- **Coordinator**: owns sequencing, final file integration, conflict resolution,
  verification, commits, and user communication.
- **Explorer subagent**: answers narrow read-only questions before edits when
  hidden coupling or call-site uncertainty could waste implementation time.
- **Worker agent**: edits files directly inside an assigned write set. It must
  list changed files, tests added or updated, verification commands run, and any
  residual risk. Workers are not alone in the codebase and must not revert edits
  made by others.
- **Code-review subagent**: reviews the phase after implementation for behavior
  regressions, public interface drift, missing tests, accidental broad seams,
  and whether the module actually became deeper.

Every worker handoff should include:

- Phase goal.
- Owned files or responsibility.
- Files explicitly out of scope.
- Existing behavior that must stay compatible.
- Required TDD tracer test.
- Verification commands.
- Instruction not to revert others' edits.

## Phase Order

The phases are sequenced to put lifecycle and dispatch first, then typed routed
cases, then domain-specific query modules, then corpus/retrieval, then UI and
outcome policy cleanup.

1. Request-to-answer dispatch spine
2. Structured routed intent cases
3. Deterministic `stat_query` module
4. `freeform_query` planning seam
5. Corpus lifecycle contract
6. Retrieval decision module
7. Gradio query adapter/session state
8. Answer outcome policy

Do not run implementation phases in parallel unless their write sets are
disjoint and the coordinator can integrate them before verification. Safe
parallel exploration is encouraged.

## Implementation Progress

- [x] Phase 1: Request-to-answer dispatch spine. Added
  `request_dispatch.RequestAnswerDispatcher`, kept `service.answer()` as the
  compatibility wrapper, added a public `execute_request()` follow-up tracer
  test, and verified adapter/tracing/player-biography compatibility. Code review
  found no blocking issues; trace ownership remains in `request_execution.py` as
  the shared adapter execution spine.
- [x] Phase 2: Structured routed intent cases. Added intent-specific routed
  cases and a shared validating factory, routed heuristic and LLM outputs
  through those cases, isolated legacy `RouteResult` normalization at the
  dispatch boundary, narrowed `answer_stat_query()` to `StatQueryCase`, and
  added request-path coverage for the new cases. Code review found no blocking
  issues.
- [x] Phase 3: Deterministic `stat_query` module. Added a stat query plan/result
  flow that owns stat table choice, time-period resolution, coverage, player
  ambiguity, fielding support, answer formatting, and SQL provenance. Kept
  DuckDB as the adapter with explicit table input and retained legacy query
  helpers as compatibility adapters. Code review found no blocking issues after
  fixes.
- [x] Phase 4: `freeform_query` planning seam. Added a DB-free freeform planner
  capability and route-precedence interface so the router no longer mirrors
  deterministic template patterns, while templates and LLM extraction still
  converge on `PlannedFreeformQuery`. Preserved stat-query precedence for plain
  leaderboards such as career HR and season ERA. Code review found no blocking
  issues after fixes.
- [x] Phase 5: Corpus lifecycle contract. Centralized collection, manifest
  section, metadata key, generated profile, and persist-dir conventions in
  `corpus.lifecycle`; moved ingest, diagnostics, player-bio frontmatter, Chroma
  metadata mapping, and generated-profile provenance checks to those helpers.
  Code review found no blocking issues after fixes.
- [x] Phase 6: Retrieval decision module. Added routed-case retrieval request
  construction, lifecycle-owned category/player metadata filters, and tracer
  coverage for exact player lookup, exact stat definition lookup, general
  fallback categories, and eval-stable strategy metadata. Service and retrieval
  evals now ask for grounded chunks by routed case rather than spelling Chroma
  filters. Planned pytest, ruff, and mypy checks passed; retrieval-only eval was
  attempted but the local Chroma index was static-only/unavailable for generated
  player profiles, so the documented deterministic fallback path was used.
- [x] Phase 7: Gradio query adapter/session state. Added
  `ui.query_session.QuerySession` to own latest-turn/session policy and
  trace-recording hooks around `QueryTransaction`, leaving `web_app.py` with
  thin Gradio wiring and tuple mapping. Added public session tests for
  overlapping submissions, session scoping, trace recording, and empty input.
  Planned pytest, ruff, mypy, and Browser smoke passed; the Browser default
  query returned 1962 RBI rows, DuckDB source metadata, and SQL on the existing
  local `127.0.0.1:7861` server.
- [x] Phase 8: Answer outcome policy. Added `outcomes.py` with focused
  helpers for ambiguous, no-data, missing-corpus, retrieval-failed,
  LLM-unavailable, timeout, and local request failures. Migrated service,
  stat-query, and UI transaction unsupported/failure construction so audit and
  review queue consume structured reason fields rather than prose. Added
  provenance tests for ambiguous review/audit policy, no-data review fallback,
  and UI failure reason consistency. Planned pytest, ruff, mypy, eval baseline,
  and code review passed.

## Completion Log

This plan was executed as eight phase commits on `main`, following the TDD,
subagent review, verification, and per-phase commit rules above. The inclusive
phase commit range is `7cb1b1b^..efe855c`.

| Phase | Commit | Verification Notes |
| --- | --- | --- |
| 1. Request-to-answer dispatch spine | `7cb1b1b` | Request execution, API, dashboard, tracing, and player biography suites passed; code-review subagent found no blocking issues. |
| 2. Structured routed intent cases | `f78b11a` | Router, player detection, stat-query integration, player biography, request execution, and freeform suites passed; ruff/mypy passed on touched modules; review findings were addressed before commit. |
| 3. Deterministic `stat_query` module | `3427906` | Query/API/stat-registry suites and eval baseline passed; ruff/mypy passed; code-review findings were addressed before commit. |
| 4. `freeform_query` planning seam | `1a8807c` | Freeform, eval-question, router, API, and eval baseline checks passed; ruff/mypy passed; code-review findings were addressed before commit. |
| 5. Corpus lifecycle contract | `584d912` | Ingest player bios, corpus diagnostics/content, Chroma store, player-bio tests, and `uv run python -m baseball_rag.corpus --static-only` passed; ruff/mypy passed; code review found no blocking issues after fixes. |
| 6. Retrieval decision module | `d88a89c` | Retrieval strategy, Chroma store, and player-bio suites passed; ruff/mypy and `git diff --check` passed. Retrieval-only eval was attempted, but the local Chroma index was static-only/unavailable for generated player profiles; the documented deterministic fallback suite passed. |
| 7. Gradio query adapter/session state | `12e3f09` | Query transaction, dashboard, answer presentation, browser contract, and query session suites passed; ruff/mypy and `git diff --check` passed. Browser smoke on `http://127.0.0.1:7861/` returned the default 1962 RBI answer with rows, DuckDB source metadata, and SQL populated. |
| 8. Answer outcome policy | `efe855c` | Provenance, audit, review queue, API, query transaction, and eval baseline checks passed; ruff/mypy and `git diff --check` passed; code-review subagent found no tracked-code issues. |

Global gate notes:

- The full `uv run pytest tests/ -v` suite was not run as one command after all
  phases. Instead, each phase ran the targeted verification suites listed
  above, with additional compatibility suites where risk warranted it.
- The full report-writing eval command from the Global Verification Matrix was
  not run. The non-mutating baseline command
  `uv run python -m evals.questions --baseline evals/baseline.json` passed for
  phases that changed answer semantics.
- The retrieval-only all-strategies eval was attempted in Phase 6 and failed
  because the local Chroma index was static-only/unavailable for generated
  player profiles. The documented deterministic fallback suite passed and the
  condition was recorded in the Phase 6 notes.
- GitHub CI was not checked because no push was performed.

Code-review subagent summary:

| Phase | Review Result |
| --- | --- |
| 1 | No blocking issues; trace ownership intentionally remained in `request_execution.py`. |
| 2 | Findings addressed before commit; no blocking issues remained. |
| 3 | Findings addressed before commit; no blocking issues remained. |
| 4 | Findings addressed before commit; no blocking issues remained. |
| 5 | Findings addressed before commit; no blocking issues remained. |
| 6 | No tracked-code issues; generated `data/review_queue.jsonl` remained out of scope. |
| 7 | No findings; Browser smoke evidence was recorded in the phase notes. |
| 8 | No tracked-code issues; `data/review_queue.jsonl` was flagged as stale generated local state and intentionally left unstaged. |

Final status after Phase 8 implementation:

- Branch `main` is ahead of `origin/main` by 9 commits, including the original
  plan expansion commit and the eight phase commits listed above.
- No GitHub push was performed, so GitHub Actions/CI was not triggered.
- The local UI server was already running on `127.0.0.1:7861` and was left
  running after the Browser smoke test, per project instructions.
- `data/review_queue.jsonl` remains intentionally unstaged because it is
  generated review-queue state. Review subagents flagged it as stale local
  state that should not be included in these architecture commits.

Documentation audit follow-up:

- This completion log was added after re-auditing the plan against the phase
  commits and is intended to be committed separately from the eight
  implementation phases.
- After that documentation commit, the only expected unstaged path is
  `data/review_queue.jsonl`.

## Phase 1: Request-To-Answer Dispatch Spine

### Goal

Make `service.answer()` thinner by moving request dispatch and answer lifecycle
behind a deeper module. The request-to-answer module should hide follow-up
resolution, route dispatch, answer handler selection, trace ownership, context
metadata, and result assembly behind a compact interface.

### Current Friction

`request_execution.py` already centralizes trace/audit/review lifecycle for
adapters, but `service.answer()` still owns follow-up resolution, route
dispatch, player biography retrieval, freeform conversion, general answer
handling, and context metadata. The module has some depth, but callers and tests
still feel too much of the implementation.

### Likely Files

- `src/baseball_rag/service.py`
- `src/baseball_rag/request_execution.py`
- `src/baseball_rag/conversation.py`
- `src/baseball_rag/api/server.py`
- `src/baseball_rag/cli.py`
- `src/baseball_rag/web_app.py`
- `tests/test_request_execution.py`
- `tests/test_pipeline_tracing_integration.py`
- `tests/test_api.py`
- `tests/test_dashboard.py`

### Worker And Subagent Plan

- Coordinator owns phase design and final integration.
- Explorer subagent: map all callers of `service.answer()` and
  `execute_request()`, including tests that patch either function.
- Worker agent A owns the new dispatch module and `service.py`.
- Worker agent B may own adapter test updates only after Worker A publishes the
  new interface. Do not run both workers against `service.py`.
- Code-review subagent runs after targeted tests pass.

### Step-By-Step Worker Tasks

1. Add one behavior test proving a request with follow-up context is resolved,
   routed, answered, and annotated through the public request interface.
2. Introduce a small dispatch module or object that accepts a question and
   optional conversation, then returns `StructuredAnswer`.
3. Move route dispatch out of `service.answer()` without changing public return
   fields or answer text.
4. Move context metadata attachment into the dispatch module so metadata rules
   are local to the request lifecycle.
5. Keep `service.answer()` as a compatibility wrapper around the new module.
6. Keep CLI, FastAPI, and Gradio behavior unchanged.
7. Remove or shrink tests that only verify private dispatch helper shape once
   behavior tests cover the public interface.

### TDD Tracer Tests

- Add or update a request execution behavior test where a prior leaderboard
  answer lets a follow-up ask about the second player and receives context
  metadata through `execute_request()`.
- Add a regression test proving `/query` still returns existing metadata,
  sources, warnings, unsupported fields, and review shape.
- Add a tracing test proving the dispatch path records one trace for one
  request.

### Verification

```bash
uv run pytest tests/test_request_execution.py tests/test_api.py tests/test_dashboard.py tests/test_pipeline_tracing_integration.py -v
uv run pytest tests/test_player_bio_query.py -v
```

### Done Criteria

- `service.answer()` delegates to a deeper dispatch module.
- Follow-up resolution, route dispatch, and context metadata have one locality.
- CLI, FastAPI, and Gradio still answer through compatible public interfaces.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that lifecycle ordering is local and visible through one interface.
- Check that no public response fields were removed or renamed.
- Check that traces are started and finished exactly once.
- Check that tests verify observable behavior, not private helper names.

## Phase 2: Structured Routed Intent Cases

### Goal

Replace the universal `RouteResult` optional-field bag with validated
intent-specific routed cases. The routing seam should give downstream modules
only the facts that are valid for that intent.

### Current Friction

`RouteResult` covers `stat_query`, `player_biography`, `freeform_query`, and
`general_explanation` with one set of nullable fields. Callers must know which
fields matter, when `.year` is valid, how `time_period` resolves, and when
`raw_question` should be used. That makes the interface shallow.

### Likely Files

- `src/baseball_rag/routing/query_router.py`
- `src/baseball_rag/routing/__init__.py`
- `src/baseball_rag/service.py`
- `src/baseball_rag/stat_query.py`
- `src/baseball_rag/db/freeform_runtime.py`
- `tests/test_router.py`
- `tests/test_router_player_detection.py`
- `tests/test_cli_stat_query_integration.py`
- `tests/test_player_bio_query.py`

### Worker And Subagent Plan

- Explorer subagent: inventory every `RouteResult` construction in tests and
  production code, then classify which routed intent each call represents.
- Worker agent A owns routing types and parser/heuristic conversion.
- Worker agent B owns call-site migration in service/stat/freeform tests after
  Worker A has a passing tracer test.
- Coordinator integrates compatibility shims only when needed to keep public
  behavior stable.

### Step-By-Step Worker Tasks

1. Add one behavior test proving a routed stat query exposes only stat-query
   facts and still answers through the normal request path.
2. Introduce routed case dataclasses or a discriminated union for:
   `StatQueryCase`, `PlayerBiographyCase`, `FreeformQueryCase`, and
   `GeneralExplanationCase`.
3. Make heuristic routing and LLM routing build those cases through one
   conversion module.
4. Preserve a compatibility shim only for tests or callers that cannot migrate
   in this phase.
5. Update `service` dispatch to match on routed case type instead of string
   intent plus nullable fields.
6. Move time-period value validation closer to case construction, while leaving
   domain-specific resolution for `stat_query` in Phase 3.
7. Remove duplicated nullable-field assumptions from tests as behavior coverage
   becomes stronger.

### TDD Tracer Tests

- Add a routing behavior test for a stat query with a range time period.
- Add a player biography routing behavior test for a name-bearing query and a
  follow-up query.
- Add a freeform routing behavior test proving a deterministic freeform pattern
  produces a `FreeformQueryCase`.

### Verification

```bash
uv run pytest tests/test_router.py tests/test_router_player_detection.py tests/test_cli_stat_query_integration.py -v
uv run pytest tests/test_player_bio_query.py -v
```

### Done Criteria

- Downstream answer modules consume validated routed cases.
- The universal optional-field bag is removed or reduced to a compatibility
  adapter.
- Existing answer behavior and eval intent IDs stay compatible.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that intent-specific interfaces are smaller than the old bag.
- Check that case construction is shared by heuristic and LLM routing adapters.
- Check that no broad seam was introduced just to satisfy typing.
- Check that tests do not merely assert dataclass shape.

## Phase 3: Deterministic `stat_query` Module

### Goal

Make deterministic stat query handling own stat table choice, time-period
resolution, data coverage, player lookup, fielding support, executed SQL
provenance, row formatting, and unsupported results behind one compact
interface.

### Current Friction

`stat_query.py` imports routing `TimePeriod` directly and owns some planning,
while `db/queries.py` owns execution and still carries legacy helper functions.
The seam between routing and SQL execution leaks stat defaults, positions,
coverage rules, and provenance formatting.

### Likely Files

- `src/baseball_rag/stat_query.py`
- `src/baseball_rag/db/queries.py`
- `src/baseball_rag/db/stat_registry.py`
- `src/baseball_rag/routing/query_router.py`
- `tests/test_queries.py`
- `tests/test_cli_stat_query_integration.py`
- `tests/test_stat_registry.py`
- `tests/test_api.py`
- `tests/test_eval_questions.py`

### Worker And Subagent Plan

- Explorer subagent: list legacy `db.queries` helpers and identify which are
  still production callers versus test-only compatibility.
- Worker agent A owns stat planning/result model inside `stat_query.py`.
- Worker agent B owns `db/queries.py` cleanup only after Worker A preserves
  behavior.
- Coordinator keeps DuckDB as the concrete Adapter and blocks broad storage
  abstractions.

### Step-By-Step Worker Tasks

1. Add one end-to-end behavior test for a fielding `PO` query through
   `service.answer()` or `execute_request()`.
2. Introduce a stat query plan/result interface that hides table selection,
   coverage decisions, and source construction from callers.
3. Move time-period resolution out of generic service/routing code and into the
   stat query module.
4. Ensure executed SQL and source SQL come from the same result object.
5. Preserve batting, pitching, fielding, player, range, and career behavior.
6. Deprecate or remove shallow legacy leader helpers when no production caller
   needs them.
7. Update tests to assert behavior and provenance rather than helper names.

### TDD Tracer Tests

- Fielding `PO` query through the normal answer path.
- AVG or OPS leaderboard query preserving sample guard behavior.
- Player-specific stat lookup returning no-data as a structured unsupported
  answer when appropriate.
- SQL provenance test proving the source SQL is the executed parameterized SQL.

### Verification

```bash
uv run pytest tests/test_queries.py tests/test_cli_stat_query_integration.py tests/test_api.py tests/test_stat_registry.py -v
uv run python -m evals.questions --baseline evals/baseline.json
```

### Done Criteria

- `stat_query` hides stat registry, table choice, coverage, execution, and
  provenance behind one interface.
- DuckDB remains the structured data Adapter.
- Existing deterministic eval behavior stays compatible.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that stat table choice is not hard-coded in request handling.
- Check that executed SQL and provenance cannot drift.
- Check fielding, batting, pitching, player, range, and career paths.
- Check that legacy helpers are either removed safely or explicitly retained as
  compatibility adapters.

## Phase 4: `freeform_query` Planning Seam

### Goal

Align deterministic templates and LLM-backed freeform extraction behind one
planning seam before SQL assembly. The freeform module should hide whether a
question matched a deterministic template or required typed LLM extraction.

### Current Friction

`PlannedFreeformQuery` exists, but the router mirrors deterministic template
knowledge in `_should_use_deterministic_freeform_route()`, while
`freeform_templates.py` owns the real template set. `freeform.py` re-exports
many private helpers, making the interface almost as complex as the
implementation.

### Likely Files

- `src/baseball_rag/db/freeform_runtime.py`
- `src/baseball_rag/db/freeform_templates.py`
- `src/baseball_rag/db/freeform_intent.py`
- `src/baseball_rag/db/freeform_assembler.py`
- `src/baseball_rag/db/freeform.py`
- `src/baseball_rag/db/team_history.py`
- `src/baseball_rag/routing/query_router.py`
- `tests/test_freeform.py`
- `tests/test_eval_questions.py`

### Worker And Subagent Plan

- Explorer subagent: compare router deterministic freeform patterns with
  `_detect_template()` and list drift.
- Worker agent A owns freeform planning and template convergence.
- Worker agent B owns router integration only after the planner exposes the
  needed interface.
- Coordinator preserves compatibility facade exports until tests and callers
  are migrated.

### Step-By-Step Worker Tasks

1. Add one planning behavior test proving a deterministic template and an
   LLM-backed intent produce the same kind of planned object before execution.
2. Add a planner capability check that router can call without duplicating
   template pattern logic.
3. Move deterministic template detection behind the planner interface.
4. Keep SQL parameterized and validation/row-limit guardrails intact.
5. Resolve historical team identity into typed data before SQL assembly instead
   of relying on English hints.
6. Preserve unsupported freeform reasons as structured data.
7. Narrow `freeform.py` compatibility exports when safe, without breaking tests
   in the same phase.

### TDD Tracer Tests

- Deterministic template planning bypasses the LLM but returns
  `PlannedFreeformQuery`.
- LLM-backed typed extraction returns the same planned interface.
- Historical Braves-style franchise mention resolves to typed team identity
  before SQL assembly.
- Unsupported deterministic template preserves `ambiguous` or `unsupported`
  reason.

### Verification

```bash
uv run pytest tests/test_freeform.py tests/test_eval_questions.py -v
uv run python -m evals.questions --baseline evals/baseline.json
```

### Done Criteria

- Template and LLM paths converge on one planning interface.
- Router no longer mirrors deterministic template details.
- Historical franchise handling is typed before assembly.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that templates do not return raw SQL through a separate path.
- Check that LLM output is still constrained before SQL assembly.
- Check that router delegates planning capability decisions instead of copying
  pattern logic.
- Check that private compatibility exports are not expanded.

## Phase 5: Corpus Lifecycle Contract

### Goal

Keep corpus document kinds, manifest entries, validated metadata, collection
names, generated profile conventions, and persist-dir resolution local to the
corpus lifecycle module.

### Current Friction

`corpus.lifecycle` already builds validated records, but document kinds and
metadata conventions still leak as raw strings and dict keys across retrieval,
diagnostics, tests, and Chroma filter construction.

### Likely Files

- `src/baseball_rag/corpus/lifecycle.py`
- `src/baseball_rag/corpus/player_bios.py`
- `src/baseball_rag/corpus/ingest.py`
- `src/baseball_rag/corpus/diagnostics.py`
- `src/baseball_rag/retrieval/chroma_store.py`
- `tests/test_ingest_player_bios.py`
- `tests/test_corpus_diagnostics.py`
- `tests/test_corpus_content.py`

### Worker And Subagent Plan

- Explorer subagent: find all raw corpus category/doc_kind/player_id strings in
  production and tests.
- Worker agent A owns corpus lifecycle constants/value objects and record
  builders.
- Worker agent B owns diagnostics and ingest call-site cleanup after Worker A
  lands the contract.
- Coordinator ensures corpus lifecycle does not absorb retrieval lookup order;
  that belongs to Phase 6.

### Step-By-Step Worker Tasks

1. Add one corpus contract test proving a generated player profile yields text,
   Chroma metadata, and manifest entry from one validated record.
2. Add typed constants or value helpers for document categories, document kinds,
   metadata keys, manifest section names, and collection name.
3. Replace raw strings in ingest and diagnostics with lifecycle helpers.
4. Add tolerant parsing helpers for manifest section counts and metadata
   round-tripping.
5. Preserve Markdown corpus files as the durable source of truth.
6. Keep ChromaDB as generated local state; do not commit generated Chroma data.
7. Leave retrieval policy changes for Phase 6 unless a tiny compatibility
   helper is needed.

### TDD Tracer Tests

- Generated player profile record round-trips source tables and player ID.
- Missing required frontmatter raises a clear validation error.
- Diagnostics report missing, partial, or corrupt manifest/Chroma state without
  raising.

### Verification

```bash
uv run pytest tests/test_ingest_player_bios.py tests/test_corpus_diagnostics.py tests/test_corpus_content.py -v
uv run python -m baseball_rag.corpus --static-only
```

### Done Criteria

- Corpus conventions live in one module.
- Ingest and diagnostics do not repeat metadata/manifest conventions.
- Generated player profile provenance remains intact.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that corpus lifecycle did not take over retrieval policy.
- Check that missing/partial Chroma states remain tolerant.
- Check that generated profile metadata includes source tables and player ID.
- Check that no generated Chroma state was committed.

## Phase 6: Retrieval Decision Module

### Goal

Let callers ask for grounded chunks for a routed case while Chroma filters,
category strings, exact-player lookup order, static vocabulary fallbacks,
thresholds, and `top_k` defaults stay behind the retrieval interface.

### Current Friction

`retrieval/decision.py` has useful depth, but `RetrievalStrategy` is still
Chroma-shaped. `where={"player_id": ...}`, `where={"category": ...}`, static
document IDs, and category strings leak through strategies and tests.

### Likely Files

- `src/baseball_rag/retrieval/decision.py`
- `src/baseball_rag/retrieval/strategies.py`
- `src/baseball_rag/retrieval/chroma_store.py`
- `src/baseball_rag/retrieval/static_vocab.py`
- `src/baseball_rag/corpus/lifecycle.py`
- `src/baseball_rag/db/stat_registry.py`
- `evals/questions.py`
- `tests/test_retrieval_strategies.py`
- `tests/test_chroma_store.py`
- `tests/test_player_bio_query.py`

### Worker And Subagent Plan

- Explorer subagent: identify tests that assert raw Chroma call choreography and
  propose observable replacements.
- Worker agent A owns retrieval decision/policy interface.
- Worker agent B owns eval strategy metadata compatibility.
- Worker agent C may own Chroma Adapter helpers if the write set stays inside
  `chroma_store.py`.
- Coordinator prevents a broad storage seam; Chroma remains the Adapter.

### Step-By-Step Worker Tasks

1. Add one behavior test proving a resolved player biography retrieves by
   player ID before semantic fallback through the retrieval interface.
2. Add one behavior test proving stat explanation can retrieve an exact static
   stat definition without service-level filters.
3. Add domain retrieval operations for exact document fetch, player biography
   lookup, stat-definition grounding, and semantic fallback.
4. Move Chroma `where` dict construction behind the Chroma Adapter or retrieval
   policy module.
5. Preserve strategy names and metadata used by evals.
6. Update tests to assert returned chunks and strategy metadata rather than raw
   filter dict call order.
7. Keep recoverable missing-corpus and embedding-mismatch behavior.

### TDD Tracer Tests

- Exact player ID lookup before semantic fallback.
- Exact stat definition lookup before semantic Chroma search.
- Fallback category behavior for general explanations.
- Retrieval strategy metadata remains stable for eval reporting.

### Verification

```bash
uv run pytest tests/test_retrieval_strategies.py tests/test_chroma_store.py tests/test_player_bio_query.py -v
uv run python -m evals.questions --all-strategies --retrieval-only
```

If the local Chroma index is unavailable, record that and run the deterministic
subset instead:

```bash
uv run pytest tests/test_retrieval_strategies.py tests/test_player_bio_query.py -v
```

### Done Criteria

- Request handling does not pass raw Chroma filters.
- Retrieval policy owns exact, semantic, and fallback ordering.
- Existing eval strategy names and flags still work.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that Chroma remains an Adapter, not the public retrieval interface.
- Check that corpus categories and doc kinds are not spread across callers.
- Check exact, semantic, and fallback behavior.
- Check eval compatibility.

## Phase 7: Gradio Query Adapter/Session State

### Goal

Move latest-turn guards, session policy, trace recording choices, named UI
state, and Gradio tuple mapping out of `web_app.py` closures into a deeper UI
adapter/session module. Keep Gradio as a thin Adapter.

### Current Friction

`QueryTransaction` earns its keep for chat/conversation/presentation state, but
`web_app.py` still owns the hard adapter behavior: latest-turn state,
stale-completion suppression, trace recording versus animation, widget tuple
ordering, and local closure functions.

### Likely Files

- `src/baseball_rag/web_app.py`
- `src/baseball_rag/ui/query_transaction.py`
- `src/baseball_rag/ui/presentation.py`
- `src/baseball_rag/arch/diagram.py`
- `tests/test_dashboard.py`
- `tests/test_query_transaction.py`
- `tests/test_answer_presentation.py`
- `tests/test_browser_contract.py`

### Worker And Subagent Plan

- Explorer subagent: list all nested functions inside `build_dashboard()` and
  classify which are Gradio-only versus reusable session policy.
- Worker agent A owns UI session/query adapter module.
- Worker agent B owns tests around stale-query and timeout behavior.
- Coordinator owns final `web_app.py` integration because Gradio wiring is
  sensitive.

### Step-By-Step Worker Tasks

1. Add one behavior test for stale query suppression through a public UI session
   object, not by reaching into Gradio closures.
2. Introduce a `QuerySession` or similarly named module that owns latest-turn
   tracking, pending/completed query state, and trace recording policy.
3. Keep `QueryTransaction` focused on answer/conversation/presentation state.
4. Move trace recording choice into the UI adapter/session layer without making
   it own `ArchitectureDiagram` internals.
5. Expose named UI state values, then let `web_app.py` map them to Gradio
   widget tuples.
6. Reduce nested closures in `build_dashboard()` to thin Gradio handlers.
7. Keep Browser smoke behavior unchanged.

### TDD Tracer Tests

- Latest query wins when two submissions overlap.
- Timeout and request failure still produce displayable structured answers.
- Trace history records completed executions without double-answering.
- Empty input resets to default question without executing.

### Verification

```bash
uv run pytest tests/test_query_transaction.py tests/test_dashboard.py tests/test_answer_presentation.py tests/test_browser_contract.py -v
```

Browser smoke test:

1. Start or reuse `uv run baseball-rag-ui`.
2. Open `http://127.0.0.1:7861/` in the Codex in-app Browser.
3. Make the Browser visible.
4. Run the default query: `who had the most RBIs in 1962`.
5. Confirm answer text, rows, sources, and SQL populate.
6. Keep the dev server running.

### Done Criteria

- `web_app.py` is mostly Gradio wiring.
- Session/latest-turn and trace-recording behavior have one locality.
- Existing dashboard behavior and Browser contract remain compatible.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that the UI session module is not a broad dumping ground.
- Check that `ArchitectureDiagram` internals did not leak into query
  transaction logic.
- Check that tests use public UI session/query interfaces where possible.
- Check Browser smoke evidence or recorded reason if it could not run.

## Phase 8: Answer Outcome Policy

### Goal

Centralize construction of unsupported, reviewable, and failure outcomes without
wrapping `StructuredAnswer` in a shallow pass-through. The outcome policy module
should make ambiguous/no-data/retrieval-failed/LLM-unavailable cases consistent
while audit and review queue remain adapters.

### Current Friction

`StructuredAnswer` already has `unsupported_reason` and `review_reason`, and
audit/review consume those fields. The remaining problem is construction:
unsupported prose, warnings, sources, and reason fields are assembled in
`service.py`, `stat_query.py`, freeform handling, and UI failure helpers.

### Likely Files

- `src/baseball_rag/provenance.py`
- `src/baseball_rag/service.py`
- `src/baseball_rag/stat_query.py`
- `src/baseball_rag/db/freeform_runtime.py`
- `src/baseball_rag/ui/query_transaction.py`
- `src/baseball_rag/audit.py`
- `src/baseball_rag/review_queue.py`
- `tests/test_provenance.py`
- `tests/test_audit.py`
- `tests/test_review_queue.py`
- `tests/test_api.py`
- `tests/test_query_transaction.py`

### Worker And Subagent Plan

- Explorer subagent: inventory every `StructuredAnswer(... unsupported=True ...)`
  construction and classify by reason.
- Worker agent A owns outcome factory/policy helpers and tests.
- Worker agent B owns call-site migration in `service.py`, `stat_query.py`, and
  UI failure helpers after Worker A lands the interface.
- Coordinator prevents a broad provenance wrapper that merely forwards
  `StructuredAnswer.to_dict()`.

### Step-By-Step Worker Tasks

1. Add one behavior test proving an ambiguous unsupported outcome produces
   consistent answer fields, review reason, audit reason, and review queue
   reason without prose sniffing.
2. Add focused outcome helpers for no-data, ambiguous, missing-corpus,
   retrieval-failed, LLM-unavailable, timeout, and local request failure.
3. Migrate call sites one vertical slice at a time.
4. Keep public payload fields additive and compatible.
5. Keep audit and review queue as adapters consuming structured answer fields.
6. Remove duplicated reason mapping only after tests cover the public behavior.
7. Update deterministic eval expectations only when intentionally additive.

### TDD Tracer Tests

- Ambiguous player/stat/freeform outcome queues review as `ambiguous`.
- No-data outcome remains unsupported but review reason maps to `unsupported`.
- UI timeout produces `llm_unavailable` consistently.
- Audit prefers structured unsupported reason.

### Verification

```bash
uv run pytest tests/test_provenance.py tests/test_audit.py tests/test_review_queue.py tests/test_api.py tests/test_query_transaction.py -v
uv run python -m evals.questions --baseline evals/baseline.json
```

### Done Criteria

- Unsupported/review/failure outcome construction has one locality.
- Audit and review queue consume structured fields, not prose.
- Existing public response fields remain compatible.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that outcome helpers add real Depth rather than wrapping constructors.
- Check that reason codes are stable and compatible.
- Check no prose-sniffing behavior controls review reasons.
- Check eval baseline compatibility.

## Global Verification Matrix

Run targeted tests inside each phase. Before each phase commit, run as much of
the local gate as feasible and explain anything skipped:

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -v
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

Additional checks when relevant:

```bash
uv run python -m baseball_rag.corpus --static-only
uv run python -m baseball_rag.corpus diagnostics --persist-dir data
uv run python -m evals.questions --all-strategies --retrieval-only
```

UI smoke check after UI-affecting phases:

```bash
uv run baseball-rag-ui
```

Then use the Codex in-app Browser at `http://127.0.0.1:7861/` and run the
default query.

## Commit And CI Expectations

Each phase ends with:

1. Targeted behavior tests for the changed interface.
2. Full local verification, or a written explanation for skipped commands.
3. Code-review subagent report with findings addressed or explicitly deferred.
4. `git status --short` reviewed.
5. Commit containing only the phase work.
6. Summary of any remaining unstaged changes.

Suggested commit message format:

```text
Deepen <module name>
```

If changes are pushed to GitHub:

- Monitor GitHub Actions for the branch.
- Do not report pushed work complete until CI is green.
- If CI fails, inspect logs, fix with TDD, rerun relevant local checks, commit,
  push, and wait again.

## Coordinator Prompt Template

Use this prompt when starting a phase with worker agents:

```text
We are implementing Phase <N>: <name> from docs/architecture-deepening-plan.md.

Use TDD with vertical slices: one behavior test, minimal implementation, then
refactor. Do not write all tests first.

Your owned write set:
- <files>

Out of scope:
- <files/behaviors>

Existing behavior that must stay compatible:
- <bullets>

Required tracer test:
- <test>

Verification:
- <commands>

You are not alone in the codebase. Do not revert edits made by others. Work
with current changes, report files changed, tests added/updated, verification
run, and any residual risk.
```

## Code-Review Subagent Prompt Template

Use this prompt after each phase implementation:

```text
Review Phase <N>: <name> in /Volumes/Envoy/projects/baseball-rag.

Take a code-review stance. Prioritize behavior regressions, public interface
drift, missing tests, accidental broad seams, and whether the changed module is
actually deeper by the deletion test.

Check:
- Changed files from git diff.
- Phase done criteria in docs/architecture-deepening-plan.md.
- Targeted tests and any skipped verification notes.

Return findings first with file/line references, then open questions, then a
brief summary. Do not edit files.
```
