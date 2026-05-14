# Architecture Worker Handoff Plan

This plan turns the architecture review findings into worker-agent tasks. It is
written for parallel implementation by subagents, with a code-review subagent
after each completed task.

No `CONTEXT.md` or `docs/adr/` existed when this plan was written. Workers
should use `README.md`, `docs/architecture.md`, and
`docs/architecture-deepening-handoff.md` as the current project vocabulary and
decision record. Because workers may run in parallel, `CONTEXT.md` is owned by
the integration lead unless a worker is explicitly granted the vocabulary lock.
Workers should record proposed vocabulary additions in their final handoff notes
instead of independently creating competing `CONTEXT.md` versions.

## Global Working Rules

- Use the TDD skill for every implementation slice: one public-behavior test,
  minimal implementation, then refactor while green.
- Keep tests behavior-focused. Avoid locking tests to private helper names unless
  the slice is explicitly about preserving a compatibility Adapter.
- Use the architecture vocabulary consistently: Module, Interface,
  Implementation, Depth, Seam, Adapter, Leverage, and Locality.
- Keep public answer payloads stable unless the task explicitly says otherwise.
  API, CLI, Gradio, eval, source, SQL, metadata, and review shapes are portfolio
  surfaces.
- Preserve compatibility Adapters first. Delete them only in a later slice after
  all callers and tests have moved to the deeper Interface.
- Do not revert unrelated work. Each worker owns the files listed for its task
  and must coordinate before touching another worker's ownership.
- Each worker final message must list changed files, tests run, remaining risk,
  and any unstaged changes.
- Run a code-review subagent after each task. Address actionable findings before
  committing.
- A task is not done until its changes are committed and any remaining unstaged
  changes are explained.
- If any branch is pushed to GitHub, wait for CI and confirm it is green.
- If a task affects the Gradio UI, start or reuse `uv run baseball-rag-ui`, open
  `http://127.0.0.1:7861/` in the Codex in-app Browser, make the Browser
  visible, run the default query smoke test, and keep the dev server running.

## Recommended Sequence

1. Worker A: Stat Semantics Module.
2. Worker D: Query Scope Module.
3. Worker C: Deterministic Freeform Template Specs.
4. Worker B: Player Biography Answer Module.
5. Worker F: Support State And Human Review Module.
6. Worker E: Conversation Context Module.
7. Worker G: Gradio Query Adapter Module.

This is the safe merge order for code-changing work. Workers may do read-only
orientation in parallel, but only workers with disjoint write sets should edit at
the same time. In particular:

- Worker A and Worker C both touch freeform stat/template tests, so do not run
  those code edits concurrently.
- Worker D defines query scope first and does not edit freeform runtime files.
  Worker C owns the later freeform consumption of the query scope Interface.
- Worker E and Worker F both touch request execution/API tests, so run them
  sequentially or split test ownership explicitly before starting.
- Worker B should either wait for Worker A or stay strictly orchestration-only.
- Worker G should wait for Worker E if conversation state mapping changes.

## Worker A: Stat Semantics Module

### Ownership

Primary files:

- `src/baseball_rag/db/stat_registry.py`
- `src/baseball_rag/db/player_stat_claims.py`
- `src/baseball_rag/db/freeform_templates.py`
- `src/baseball_rag/db/freeform_schema.py`
- `src/baseball_rag/db/freeform_assembler.py`
- `tests/test_stat_registry.py`
- `tests/test_player_stat_claims_consensus.py`
- `tests/test_freeform.py`

Coordinate before editing `src/baseball_rag/db/queries.py`; that file may be
touched by a later stat-query-shape slice.

### Problem

The existing `StatDefinition` Module owns Lahman formulas and guards, but AVG,
OPS, ERA, WHIP, sample guards, and ranking direction are still duplicated across
Retrosheet verification, deterministic freeform templates, and schema prompt
text. The Interface is not deep enough for multiple source vocabularies.

Deletion test: if the current stat semantics Module were deleted, formula and
qualification knowledge would reappear in `player_stat_claims.py`,
`freeform_templates.py`, `freeform_schema.py`, and stat SQL builders.

### Target Shape

Deepen the stat semantics Module so a caller asks for stat behavior against a
source Adapter. Lahman and Retrosheet should provide column vocabularies; the
Module should provide expression, aggregate expression, sample guard, and ranking
direction. It should also centralize contextual disambiguation such as batting
versus pitching SO when the claim text or table hint makes the source table
clear.

Avoid changing public answer payloads. This slice is about Locality for stat
meaning, not user-visible wording.

### TDD Slices

1. RED: add a registry test showing one derived stat, such as OPS, can render an
   aggregate expression through a Retrosheet Adapter without duplicating formula
   logic in the claim verifier.
   GREEN: add the smallest Adapter-aware rendering path in `stat_registry.py`.
2. RED: add a claim-verification test proving Retrosheet AVG or OPS uses the
   registry-rendered expression and still verifies the existing fixture.
   GREEN: route Retrosheet expression assembly through the new stat Interface.
3. RED: add a freeform template/schema test proving sample guards or formula
   wording comes from the stat semantics Module.
   GREEN: replace template/schema duplication with registry calls where safe.
4. RED: add a claim-verification test proving contextual SO still chooses the
   pitching table when the claim text says "pitcher", "pitching", or "batters".
   GREEN: move contextual stat-table inference into the stat semantics Module.
5. REFACTOR: remove now-dead duplicate formula helpers. Keep compatibility
   helpers if tests or callers still import them.

### Verification

Run:

```bash
uv run pytest tests/test_stat_registry.py tests/test_player_stat_claims_consensus.py tests/test_freeform.py -q
uv run pytest tests/test_queries.py tests/test_stat_leaders_range_db.py tests/test_cli_stat_query_integration.py -q
uv run pytest tests/test_api.py::TestApi::test_query_endpoint_preserves_pitching_rate_stat_provenance -q
```

Run the deterministic eval gate if any answer rows, SQL text, or source metadata
change:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- Retrosheet columns are optional and schema-tolerant. Preserve unsupported
  warnings for missing tables and missing columns.
- SQL text changes can affect audit hashes and eval baselines. Treat that as a
  visible behavior change.

## Worker B: Player Biography Answer Module

### Ownership

Primary files:

- `src/baseball_rag/service.py`
- new `src/baseball_rag/player_biography.py` or similar
- `src/baseball_rag/corpus/player_bios.py`
- `src/baseball_rag/generation/prompt.py`
- `tests/test_player_bio.py`
- `tests/test_player_bio_query.py`
- `tests/test_router_player_bio.py`
- `tests/test_request_execution.py`

Avoid rewriting claim consensus presentation already completed in
`src/baseball_rag/db/player_stat_claims.py`.

### Problem

Player biography answering still lives as broad private Implementation in
`service.py`: identity resolution, supplied claim extraction, LLM JSON repair,
claim verification orchestration, final source shaping, warnings, and metadata.
The route handler Interface is a loose `Callable[..., StructuredAnswer]`.

Deletion test: deleting the current private biography helpers would force the
same orchestration into `service.py`, tests, or adapters. The complexity is real,
but it lacks a deep Module.

### Target Shape

Create a player biography answer Module with one public route-case Interface.
The Module should own biography orchestration while continuing to use the claim
consensus presentation Module as an internal dependency.

Do not change the LLM JSON contract, verification rules, `StructuredAnswer`
shape, or response metadata keys.

### TDD Slices

1. RED: add a public behavior test that a `PlayerBiographyCase` answer resolves
   a single player and returns the same resolved-player metadata.
   GREEN: introduce the new Module and route `service.py` through it.
2. RED: add a supplied-claim behavior test through the new public Interface,
   preserving the existing answer note, source label, and metadata.
   GREEN: move supplied-claim extraction and handling into the Module.
3. RED: add a malformed LLM JSON repair test through the new Module Interface.
   GREEN: move JSON parsing and repair prompt behavior out of `service.py`.
4. REFACTOR: leave `service.answer()` as orchestration only: initialize, resolve
   follow-up, route, dispatch.

### Verification

Run:

```bash
uv run pytest tests/test_player_bio.py tests/test_player_bio_query.py tests/test_router_player_bio.py tests/test_request_execution.py -q
```

If LLM-unavailable handling changes, also run:

```bash
uv run pytest tests/test_api.py tests/test_eval_questions.py -q -m "not llm"
```

### Risks

- Biography behavior depends on LM Studio availability in live paths. Keep unit
  tests mocked at the public route Interface.
- The prior handoff already deepened claim presentation. Do not re-open that
  slice unless a regression forces it.

## Worker C: Deterministic Freeform Template Specs

### Ownership

Primary files:

- `src/baseball_rag/db/freeform_templates.py`
- `src/baseball_rag/db/freeform_runtime.py`
- `src/baseball_rag/routing/freeform_ownership.py`
- `src/baseball_rag/routing/query_router.py`
- `tests/test_freeform.py`
- `tests/test_router.py`
- `tests/test_eval_questions.py`

Coordinate with Worker D before changing time/year handling.

### Problem

Freeform ownership was already deepened in the previous handoff. The remaining
shallow Interface is template matching itself: detection, route precedence,
unsupported policy, SQL text, params, and source detail are split across helpers
that re-detect or reinterpret the same question.

Deletion test: deleting `_template_source_detail()` or
`should_route_deterministic_freeform()` would remove local complexity but force
the same decisions to reappear in routing/runtime tests. The matched template
concept needs more Depth.

### Target Shape

Represent each deterministic pattern as a typed template spec Module. A matched
spec should carry enough information for routing ownership, unsupported policy,
SQL assembly, params, and source detail.

The router should not need full SQL text. Keep the Seam between route ownership
and executable planning explicit.

### TDD Slices

1. RED: add a template-match test for an existing case, such as ambiguous
   `500 club`, asserting one matched object exposes route ownership and
   unsupported reason.
   GREEN: introduce a small matched-template read model.
2. RED: add a planning test proving runtime uses the matched spec source detail
   without re-detecting the question.
   GREEN: carry the matched spec through `plan_query()`.
3. RED: add a routing test proving plain career HR leaderboards still stay on
   stat query while `500 home run club` routes to freeform.
   GREEN: route ownership through the matched spec Interface.
4. RED: add a freeform planning test proving a routed single-season query scope
   from Worker D can be consumed without peeking at raw `TimePeriod` internals.
   GREEN: integrate the query scope Interface into freeform planning where the
   scope is safely single-season.
5. REFACTOR: remove duplicated detection helpers or keep thin compatibility
   Adapters only where tests import them.

### Verification

Run:

```bash
uv run pytest tests/test_freeform.py tests/test_router.py tests/test_eval_questions.py -q -m "not llm"
```

Run the deterministic eval gate because freeform guardrails are release-gated:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- `baseball_rag.db.freeform` is a compatibility facade. Preserve exports during
  this slice.
- Source labels and SQL visibility are demo surfaces. Keep them stable unless a
  test and baseline update make the change intentional.

## Worker D: Query Scope Module

### Ownership

Primary files:

- `src/baseball_rag/routing/query_router.py`
- `src/baseball_rag/stat_query.py`
- new `src/baseball_rag/query_scope.py` or similar
- `tests/test_router.py`
- `tests/test_api.py`
- `tests/test_request_execution.py`
- `tests/test_eval_questions.py`

Do not edit `src/baseball_rag/db/freeform_runtime.py` in this slice. Worker C
owns freeform consumption of the new query scope Interface.

### Problem

`TimePeriod` is currently a shallow data Module. Routing extracts it, stat query
resolves it, coverage checks live near answer planning, and freeform receives
only a year-shaped fragment. Current-year ambiguity, relative scope, reversed
ranges, and manifest coverage are spread out.

Deletion test: deleting `TimePeriod` today mostly moves fields around. Deleting
the actual query-scope behavior would make ambiguity and coverage complexity
reappear in routing, stat planning, freeform planning, and HTTP tests.

### Target Shape

Create a query scope Module that turns routed time facts into an answerable
scope and owns ambiguity plus coverage policy. The Interface should be usable by
stat query first and later by freeform.

Preserve existing answer wording and unsupported reasons unless intentionally
changed.

### TDD Slices

1. RED: add a scope test for bare current-century decades, using configured
   current year.
   GREEN: move that ambiguity policy into the query scope Module.
2. RED: add a scope test for explicit historical decades and reversed ranges.
   GREEN: move range resolution and validation into the Module.
3. RED: add a public stat-query/API test proving coverage no-data behavior still
   uses manifest coverage.
   GREEN: move coverage lookup and coverage source construction behind the
   query scope Interface or a close Adapter.
4. RED: add a stat-query planning test proving callers can use the resolved
   scope without peeking at raw `TimePeriod` internals.
   GREEN: update stat planning only. Leave freeform integration to Worker C.

### Verification

Run:

```bash
uv run pytest tests/test_router.py tests/test_api.py tests/test_request_execution.py tests/test_eval_questions.py -q -m "not llm"
```

### Risks

- Date logic depends on `BASEBALL_RAG_CURRENT_YEAR`. Keep tests deterministic.
- Coverage is audit-visible through source records and metadata.

## Worker E: Conversation Context Module

### Ownership

Primary files:

- `src/baseball_rag/conversation.py`
- `src/baseball_rag/ui/presentation.py`
- `src/baseball_rag/request_dispatch.py`
- `src/baseball_rag/service.py`
- `src/baseball_rag/api/server.py`
- `tests/test_answer_presentation.py`
- `tests/test_request_execution.py`
- `tests/test_api.py`
- `tests/test_dashboard.py`
- new `tests/test_conversation.py` if pure Module coverage outgrows existing
  request tests

Coordinate with Worker G before changing Gradio state shapes.

### Problem

The UI presentation Module decides which metadata and source rows survive into
conversation state, while `conversation.py` independently interprets informal
dicts. HTTP callers also send raw `list[dict[str, Any]]`. The Interface is
"know this payload shape", which is shallow.

Deletion test: deleting `PresentedAnswer.conversation_turn()` would move
field-picking into `web_app.py` or clients. Deleting follow-up resolution would
move player-reference logic into request dispatch. The missing Depth is at the
conversation-turn Seam.

### Target Shape

Move conversation-turn shaping into the conversation Module. UI and HTTP
Adapters should serialize and pass conversation turns; they should not decide
which source fields matter for follow-up resolution. If context metadata
attachment moves too, `RequestAnswerDispatcher` should delegate that policy
rather than knowing which follow-up fields belong in `StructuredAnswer.metadata`.

### TDD Slices

1. RED: add a conversation Module test that builds a turn from a
   `StructuredAnswer` and preserves only follow-up-relevant metadata and rows.
   GREEN: add the core turn-shaping Interface.
2. RED: update `AnswerPresenter` behavior test to consume the new Interface
   without owning field selection.
   GREEN: delegate `conversation_turn()` to the conversation Module.
3. RED: add API/request execution behavior proving a caller-provided turn still
   resolves "the second player".
   GREEN: make resolver tolerant of both new and legacy turn shapes.
4. RED: add a request-path test proving resolved ordinal/pronoun context still
   annotates `original_question`, `context_question`, `context_source`, and
   `context_player_name`.
   GREEN: move metadata attachment policy into the conversation Module or a
   close Adapter.
5. RED: add a regression test proving unsupported answers do not gain player
   context metadata.
   GREEN: preserve the current unsupported behavior behind the same Interface.
6. REFACTOR: document the accepted turn shape in code comments or `CONTEXT.md`
   if a new domain term is introduced.

### Verification

Run:

```bash
uv run pytest tests/test_answer_presentation.py tests/test_request_execution.py tests/test_api.py tests/test_dashboard.py -q
```

### Risks

- Existing clients may send legacy dicts. Keep legacy tolerance until a later
  migration explicitly removes it.
- Conversation payload changes can affect Gradio state and Browser behavior.

## Worker F: Support State And Human Review Module

### Ownership

Primary files:

- `src/baseball_rag/provenance.py`
- `src/baseball_rag/outcomes.py`
- `src/baseball_rag/audit.py`
- `src/baseball_rag/review_queue.py`
- `src/baseball_rag/request_execution.py`
- new `src/baseball_rag/support_state.py` or similar
- `tests/test_provenance.py`
- `tests/test_audit.py`
- `tests/test_review_queue.py`
- `tests/test_request_execution.py`
- `tests/test_api.py`

### Problem

`outcomes.py` centralizes construction, but support state is still re-derived by
audit and human review. Unsupported reason, review reason, source summary, and
review queue policy are inferred in multiple places.

Deletion test: deleting the current review helper choreography would remove some
local complexity, but the same unsupported and ambiguous rules would reappear in
request execution, audit metadata, and API tests. The support state Interface is
not deep enough.

### Target Shape

Deepen answer support state so audit and human review consume a single
Interface. Keep JSONL storage as the current Implementation. Treat storage as an
Adapter only if a second store appears. The request execution path should call
one support-state operation for audit/review application instead of manually
sequencing build, persist, and public payload helpers.

### TDD Slices

1. RED: add a provenance/outcome test for an ambiguous answer showing one support
   state exposes unsupported reason, review reason, and audit reason.
   GREEN: add the support state Interface.
2. RED: update audit tests to consume support state instead of re-deriving
   unsupported reason from warnings or source rows.
   GREEN: route `audit.unsupported_reason()` through support state while
   preserving legacy fallback behavior.
3. RED: update review queue tests to enqueue based on support state.
   GREEN: add an `enqueue_review_item()` style Interface that owns build,
   persist, and payload choreography.
4. RED: update request execution test to patch one human-review Module call
   instead of three helper calls.
   GREEN: simplify request execution.

### Verification

Run:

```bash
uv run pytest tests/test_provenance.py tests/test_audit.py tests/test_review_queue.py tests/test_request_execution.py tests/test_api.py -q
```

### Risks

- Review IDs must remain deterministic and ignore volatile trace/latency fields.
- API response fields `unsupported_reason`, `review_reason`, `metadata`, and
  `review` are public surfaces.

## Worker G: Gradio Query Adapter Module

### Ownership

Primary files:

- `src/baseball_rag/web_app.py`
- `src/baseball_rag/ui/query_transaction.py`
- `src/baseball_rag/ui/query_session.py`
- new `src/baseball_rag/ui/gradio_adapter.py` or similar
- `tests/test_query_transaction.py`
- `tests/test_query_session.py`
- `tests/test_dashboard.py`
- `tests/test_browser_contract.py`
- `tests/test_gradio.py`

Wait for Worker E if conversation turn shape changes.

### Problem

`QueryTransaction` and `QuerySession` have useful Depth, but the Gradio adapter
code still knows tuple order, `gr.update`, pending tokens, registry dictionaries,
and callback output shapes. Tests unpack exact tuples and callback details.

Deletion test: deleting `QueryTransaction` would scatter lifecycle logic, so it
earns its Interface. Deleting `as_gradio_values()` and nested callback tuple
mapping would mostly remove Gradio-specific complexity. That complexity belongs
in a concrete Adapter at the Gradio Seam.

### Target Shape

Add a Gradio query Adapter Module that maps adapter-neutral query updates to
Gradio values and event output policy. Leave `QueryTransaction` and
`QuerySession` adapter-neutral.

### TDD Slices

1. RED: add an Adapter test that maps a completed `QueryUiUpdate` to the exact
   Gradio output tuple currently expected by the Query tab.
   GREEN: introduce the Gradio Adapter Module and delegate existing mapping.
2. RED: add an Adapter test for pending and stale query outputs, including
   button interactivity.
   GREEN: move `gr.update` and no-component-update policy into the Adapter.
3. RED: update dashboard tests to assert behavior through the Adapter rather
   than tuple slot archaeology where possible.
   GREEN: simplify `web_app.py` nested callbacks.
4. REFACTOR: keep Browser-facing behavior unchanged.

### Verification

Run:

```bash
uv run pytest tests/test_query_transaction.py tests/test_query_session.py tests/test_dashboard.py tests/test_browser_contract.py tests/test_gradio.py -q
```

Then run the Browser smoke:

```bash
uv run baseball-rag-ui
```

Open `http://127.0.0.1:7861/`, make the Codex in-app Browser visible, submit the
default query, and verify the answer includes Davis, Tommy, rows, source JSON,
and SQL. Switch to the Architecture tab and verify the latest path reflects the
completed default query. Leave the dev server running.

### Risks

- Gradio callback order is brittle. Move it behind the Adapter before changing
  behavior.
- Keep Architecture tab refresh behavior stable; the previous handoff already
  deepened the Architecture read model.

## Cross-Task Review Checklist

Use this checklist after each worker completes a slice:

- The new Module has a smaller Interface than the Implementation it hides.
- The deletion test still passes: deleting the Module would move real complexity
  into multiple callers, not simply remove complexity.
- Each new Seam has at least two real Adapters or a clear immediate variation.
  Do not create hypothetical Seams.
- Behavior tests cross the same Interface that production callers use.
- Compatibility Adapters are either preserved or removed only with explicit
  migration tests.
- Existing eval, API, CLI, Gradio, source, SQL, and review payloads remain
  stable unless the commit clearly documents the intentional change.
- The worker ran focused tests, then a broader relevant suite.
- A code-review subagent reviewed the patch and all actionable findings were
  addressed.
- The final commit message names the deepened Module and the preserved behavior.

## Suggested Commit Boundaries

Use one commit per worker task unless a task is intentionally split into smaller
vertical slices. Good commit messages:

- `Deepen stat semantics adapters`
- `Extract player biography answer module`
- `Carry deterministic freeform template specs`
- `Centralize query scope resolution`
- `Move conversation turn shaping to core`
- `Deepen support state review policy`
- `Extract Gradio query adapter`
