# Fresh Architecture Deepening Handoff Plan

Status: Completed implementation. This document turns the 2026-05-24 architecture review
into worker-ready implementation slices for `/Volumes/Envoy/projects/baseball-rag`.
It began as a proposed handoff and now serves as the completion ledger for the
implemented Modules.

No `CONTEXT.md` or `docs/adr/` exists in this repo. Use `README.md`,
`docs/architecture.md`, `docs/architecture-followup-worker-handoff-plan.md`,
and `docs/architecture-next-deepening-plan.md` as the active vocabulary and
decision context.

## Fresh Deepening Opportunities

The previous architecture ledgers are completed records. Do not reopen completed
Modules unless a worker can show a fresh public-behavior test that exposes new
friction. Treat request lifecycle ordering, routing decision order, visible
evidence presentation, eval reporting, source provenance, LLM-flavored narration
guard, grounded database planning, DuckDB answer assembly, biography stat-claim
vocabulary, support state and human review, conversation context, and Gradio
query adapter as landed unless new evidence says otherwise.

Primary worker scope:

1. Biography Contract Completeness Guard Module.
2. LLM Router Adapter Module.
3. Player Identity Authority Module.
4. Query Output Contract Module.
5. Verified Evidence Read Model Module.

## Implementation Ledger

Completed in the documented worker order with TDD slices and code-review
subagents:

- Worker A added a Biography Contract completeness guard at the generated LLM
  JSON Seam. It rejects supported stat facts missing from `stat_claims`, accepts
  unsupported stat-like prose and generic dates, preserves `llm_unavailable`,
  and handles stat-before-value, season-year, career-scope, same-sentence, and
  numeric normalization cases.
- Worker D added a named Query Output Contract around the Gradio adapter so
  pending, completed, and stale callback payload order is owned in one Adapter.
- Worker B extracted the LLM Router Adapter behind `route(question)`, keeping
  deterministic precedence and malformed-output fallback stable.
- Worker E introduced a Verified Evidence read model for LLM narration checks,
  including unambiguous `stat_value` evidence adaptation without relying on
  rendered answer text.
- Worker C introduced the Player Identity Authority for Lahman player
  resolution, display metadata, suffix-aware ambiguity policy, and optional
  Retrosheet ID mapping while keeping `corpus/player_bios.py` as a compatibility
  facade.

Preserved project rules: DuckDB/Lahman remains the primary factual/stat
authority, Retrosheet remains optional secondary consensus evidence, and no
stored corpus, vector index, or Chroma replacement was added.

Final verification for commit `fee989d`:

- `uv run pytest tests/test_project_cleanup.py -q` passed with 84 tests.
- `uv run ruff check src/ tests/ evals/` passed.
- `uv run mypy src/` passed.
- `uv run pytest -q` passed with 747 tests.
- `uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json`
  passed with 26 deterministic cases and 44 live/manual cases skipped.
- Browser smoke at `http://127.0.0.1:7861/` passed for
  `who had the most RBIs in 1962`: the UI showed Davis, Tommy, result rows,
  source JSON, SQL, and an enabled Ask button. The dev server was left running.

Backlog candidates from the review, not primary scope for this pass: claim
evidence adapter extraction, pre-routing unsupported guard, stat query planning
outcome, source authority provenance catalog, browser-session trace, and
operational verification health checks. Promote one only if it blocks a primary
worker.

## Global Rules

- Use TDD for every code-changing slice: one public-behavior test, minimal
  implementation, then refactor while green.
- Tests must cross public Interfaces. Avoid tests that lock to private helper
  names unless preserving a compatibility Adapter is the behavior under test.
- Use the architecture vocabulary consistently: Module, Interface,
  Implementation, Depth, Seam, Adapter, Leverage, and Locality.
- DuckDB/Lahman remains the primary factual/stat authority. Retrosheet remains
  optional secondary consensus evidence for biography stat claims.
- Do not add a stored corpus, vector index, or Chroma replacement.
- Preserve public CLI, FastAPI, Gradio, source JSON, SQL, metadata, review, and
  eval shapes unless a failing test proves an intentional behavior alignment.
- Preserve compatibility Adapters first. Delete them only after callers and
  behavior tests have moved to the deeper Interface.
- Run a code-review subagent after every worker task and after final integration.
- A task is not complete until changes are committed and any unstaged changes
  are explained.
- If a branch is pushed to GitHub, wait for CI and confirm it is green.

## Parallelization Strategy

All workers may orient in parallel. Code edits should land in this order unless
the integration lead narrows write locks further:

| Wave | Workers | Notes |
| --- | --- | --- |
| 1 | Worker A, Worker D | Mostly disjoint. Worker A owns biography contract validation; Worker D owns Gradio output mapping. |
| 2 | Worker B, Worker E | Worker B changes routing internals. Worker E changes narration evidence internals while preserving the public narration guard Interface. |
| 3 | Worker C | Player identity touches biography, stat query, and Retrosheet mapping, so integrate after route and evidence assumptions are stable. |
| 4 | Integration lead | Reconcile behavior, update docs/evals if needed, run verification, run Browser smoke, review, and commit. |

Suggested branch names: `disco/biography-contract-completeness`,
`disco/llm-router-adapter`, `disco/player-identity-authority`,
`disco/query-output-contract`, `disco/verified-evidence-read-model`, and
`disco/fresh-architecture-integration`.

## Shared Definition Of Done

Every worker final report must include files changed, TDD slices completed,
tests run, public behavior preserved or intentionally aligned, code-review
subagent findings and fixes, remaining risk, and unstaged changes if any.

Final integration must run:

```bash
uv run pytest tests/test_project_cleanup.py -q
uv run ruff check src/ tests/ evals/
uv run mypy src/
uv run pytest -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
uv run baseball-rag-ui
```

For the UI command, use the Codex in-app Browser at
`http://127.0.0.1:7861/`, run the default query
`who had the most RBIs in 1962`, confirm Davis, Tommy plus rows, source JSON,
SQL, and an enabled Ask button, make the Browser visible, and keep the dev
server running.

## Worker A: Biography Contract Completeness Guard Module

### Ownership

Primary files: `src/baseball_rag/biography_contract.py`,
`src/baseball_rag/player_biography.py`, `src/baseball_rag/generation/prompt.py`,
`tests/test_biography_contract.py`, and `tests/test_player_bio_query.py`.

Coordinate before editing: `src/baseball_rag/db/biography_stat_vocabulary.py`,
`src/baseball_rag/db/player_stat_claims.py`, `docs/architecture.md`, and
`README.md`.

### Problem

The biography prompt tells the LLM to put every explicit stat in `stat_claims`,
but the contract Interface mostly validates JSON shape. A generated biography
can include supported facts such as `714 HR` while returning `stat_claims: []`,
which bypasses the claim-verification Seam.

Deletion test: deleting the current contract validation would push JSON parsing
and missing-field checks into `PlayerBiographyCaseAnswerer`. That Module earns
its keep, but it is shallow for factual completeness because callers must trust
the LLM Adapter to expose its own supported claims.

### Target Shape

Add a focused guard at the LLM-output Seam. Its Interface should accept the
generated biography JSON and return either the accepted biography payload or a
typed contract failure that preserves the existing `llm_unavailable` outcome
path. The guard should compare biography prose against the supported biography
claim vocabulary before `verify_player_stat_claims_consensus(...)` runs.

The LLM biography response is one Adapter. Supplied-biography extraction is a
second Adapter and should remain outside this worker except for shared
vocabulary reuse.

### Benefits

Depth: callers still learn only `answer` plus `stat_claims`, while the contract
Module hides prose/claim completeness checks. Leverage: every generated
biography gets the same missing-claim protection. Locality: regex tuning and
false-positive policy stay near the biography contract.

### TDD Slices

1. RED: fake the biography LLM to return prose with an explicit supported stat
   claim and `stat_claims: []` through `PlayerBiographyCaseAnswerer.answer(...)`.
   GREEN: reject the response through the contract path without calling claim
   verification.
2. RED: fake prose with an unsupported stat-like phrase and no supported claim;
   it should remain accepted. GREEN: scope detection to
   `biography_stat_vocabulary` support only.
3. RED: fake clean prose with no supported stat claims; it should preserve the
   current answer and resolved-player metadata. GREEN: avoid turning generic
   numbers, years, or dates into contract failures.
4. RED: preserve the existing invalid JSON/invalid contract `llm_unavailable`
   public behavior. GREEN: route completeness failure through the same visible
   outcome shape.

### Verification

```bash
uv run pytest tests/test_biography_contract.py tests/test_player_bio_query.py -q
uv run pytest tests/test_generation.py tests/test_service.py -q
```

Run the deterministic eval gate if biography warnings, unsupported reasons,
source rows, or metadata change.

### Risks

Regex false positives can reject valid prose. Do not broaden the biography stat
contract just to satisfy a test. Be explicit if a completeness failure should be
`llm_unavailable` rather than a warning-bearing partial answer.

## Worker B: LLM Router Adapter Module

### Ownership

Primary files: `src/baseball_rag/routing/query_router.py`,
`src/baseball_rag/routing/contracts.py`, `tests/test_router.py`,
`tests/test_router_player_detection.py`, and `tests/test_query_scope.py`.

Coordinate before editing: `src/baseball_rag/routing/decisions.py`,
`src/baseball_rag/request_dispatch.py`,
`src/baseball_rag/db/grounded_database_planner.py`, and `evals/questions.yaml`.

### Problem

`route(question)` is the public routing Interface and a good external Seam.
Inside it, `query_router.py` still owns the LLM prompt, model call, JSON
extraction, field validation, `TimePeriod` conversion, fallback behavior, and a
large deterministic feature surface. Understanding one routing failure requires
bouncing between prompt handling, route precedence, and fallback heuristics.

Deletion test: deleting routing would scatter route facts across request
dispatch and answer Modules, so the Module earns its keep. The shallow part is
the embedded LLM Adapter: prompt/output weirdness is not local.

### Target Shape

Keep `route(question)` stable. Extract an internal LLM Router Adapter Module
whose Interface returns either a typed routed case or a small typed failure that
the deterministic decision chain can handle. Do not change route precedence in
the same slice unless a public behavior test requires it.

The deterministic feature extraction found in review can become a later internal
Module, but start by making model I/O local and testable.

### Benefits

Depth: callers still use one `route(question)` Interface while prompt,
malformed JSON, timeout, and field coercion behavior hides behind one Adapter.
Leverage: model upgrades and prompt changes stop touching route ordering code.
Locality: malformed-output fixes land in one Module and one focused test set.

### TDD Slices

1. RED: preserve malformed JSON fallback behavior through `route(...)`. GREEN:
   move only JSON extraction and failure handling behind the Adapter.
2. RED: preserve time-period conversion for year, range, decade, and current-year
   route facts. GREEN: move LLM payload-to-case conversion behind the Adapter.
3. RED: preserve timeout/connection fallback behavior. GREEN: return a typed
   Adapter failure and let existing deterministic fallback handle it.
4. RED: add a behavior test proving deterministic fallback is unchanged when
   the Adapter returns no usable route. GREEN: keep route precedence intact.

### Verification

```bash
uv run pytest tests/test_router.py tests/test_router_player_detection.py tests/test_query_scope.py -q
uv run pytest tests/test_request_execution.py tests/test_grounded_database.py -q
```

Run the deterministic eval gate if route outcomes, unsupported reasons, or eval
case classifications change.

### Risks

Route precedence is user-visible and eval-visible. Prompt wording drift can
change model output even when tests use fakes. Do not fix route misses by adding
a hidden ungrounded fallback.

## Worker C: Player Identity Authority Module

### Ownership

Primary files: `src/baseball_rag/corpus/player_bios.py`,
`src/baseball_rag/player_biography.py`, `src/baseball_rag/stat_query.py`,
`src/baseball_rag/db/queries.py`, `src/baseball_rag/db/player_stat_claims.py`,
and new `src/baseball_rag/db/player_identity.py` if the slice proves the Module
belongs under `db/`.

Coordinate before editing: `src/baseball_rag/routing/query_router.py`,
`src/baseball_rag/db/secondary_sources/retrosheet.py`,
`tests/test_player_bio_query.py`, `tests/test_request_execution.py`,
`tests/test_player_stat_claims_consensus.py`, and `evals/questions.yaml`.

### Problem

Player identity is a core factual authority, but its Implementation is spread
across `corpus/player_bios.py`, stat-query name parsing, DuckDB query helpers,
and Retrosheet `retroID` lookup inside claim verification. The Interface for
"who is this player?" changes by caller: biography asks one Module, stat query
uses another path, and Retrosheet mapping is buried in consensus lookup.

Deletion test: deleting identity behavior would force every route to repeat
Lahman player lookup, ambiguity policy, display-name shaping, and optional
Retrosheet mapping. That is real Depth waiting for a clearer Seam.

### Target Shape

Create a Player Identity Authority Module for Lahman player resolution,
ambiguity policy, display names, and optional Retrosheet ID mapping. Biography,
stat lookup, and claim consensus should use it through one Interface. Lahman
identity and Retrosheet mapping should be separate internal Adapters.

Move the current `corpus/player_bios.py` role only after a public test proves
the new Module preserves behavior. The user-visible rule remains: ambiguity and
missing players fail closed before LLM generation or stat fabrication.

### Benefits

Depth: callers ask one identity question and get one typed result. Leverage:
stat queries, biographies, supplied claim checks, and Retrosheet consensus share
ambiguity and mapping policy. Locality: name-matching bugs and cross-source ID
issues stop bouncing between biography, stat query, and claim verification code.

### TDD Slices

1. RED: ambiguous biography still fails before any LLM call. GREEN: route
   biography resolution through the new identity Interface.
2. RED: surname-only stat query ambiguity still fails closed with the same
   unsupported/ambiguous reason. GREEN: move stat-query player lookup through
   the same authority.
3. RED: resolved biography carries the same `resolved_player` metadata and
   context player name. GREEN: keep public metadata shape stable.
4. RED: missing `retroID` for optional Retrosheet evidence remains explainable
   and nonfatal. GREEN: move Retrosheet mapping behind an internal Adapter.

### Verification

```bash
uv run pytest tests/test_player_bio_query.py tests/test_request_execution.py -q
uv run pytest tests/test_player_stat_claims_consensus.py tests/test_queries.py -q
```

Run the deterministic eval gate if ambiguity wording, unsupported reasons,
resolved metadata, or source rows change.

### Risks

Name matching behavior is user-visible and has many historical edge cases.
`retroID` is optional; missing mappings must remain warnings/no-data, not
crashes. Do not treat Retrosheet as a replacement primary factual authority.

## Worker D: Query Output Contract Module

### Ownership

Primary files: `src/baseball_rag/web_app.py`,
`src/baseball_rag/ui/gradio_adapter.py`,
`src/baseball_rag/ui/query_transaction.py`,
`src/baseball_rag/ui/query_session.py`, `tests/test_gradio_query_adapter.py`,
`tests/test_query_transaction.py`, `tests/test_query_session.py`, and
`tests/test_dashboard.py`.

Coordinate before editing: `src/baseball_rag/ui/presentation.py` and
`src/baseball_rag/arch/read_model.py`.

### Problem

The Gradio Adapter hides `gr.update`, but the public UI callback Interface is
still positional tuples. `web_app.py` and tests must know exact output count and
order for pending, completed, and stale paths. The Seam exists, but the Module
is shallow because tuple order leaks through every caller.

Deletion test: deleting the adapter would spread `gr.update`, disabled-button
policy, and stale-output behavior across dashboard callbacks. It earns its keep,
but needs a named output contract for better Depth.

### Target Shape

Add a named output contract Module around `QueryUiUpdate`. The Interface should
map named fields to Gradio outputs in one Adapter. `web_app.py` should wire
components once, then delegate output order validation and mapping to the
Adapter. Preserve the current 9-output completed contract until parity tests
prove the new Interface.

### Benefits

Depth: dashboard callbacks stop knowing tuple slot meaning. Leverage:
output-order changes become one contract update plus one focused test. Locality:
pending/completed/stale output bugs live in the Adapter instead of scattered
dashboard assertions.

### TDD Slices

1. RED: stale, completed, and pending output names match the dashboard config.
   GREEN: introduce named output definitions without changing runtime behavior.
2. RED: a changed component order fails in the contract test, not through tuple
   slot unpacking elsewhere. GREEN: make the Adapter own output ordering.
3. RED: pending output clears Answer/Rows/Sources/SQL, disables Ask, and keeps
   the pending token and registry. GREEN: map pending through the named contract.
4. RED: completed output returns chat, question reset, answer, rows, sources,
   SQL, chat state, conversation state, and enabled Ask. GREEN: map completed
   through the named contract.

### Browser Smoke Expectations

At `http://127.0.0.1:7861/`, submit the default query. Confirm Answer, Rows,
Sources, and SQL clear while pending; Ask disables while pending; completion
shows Davis, Tommy, result rows, source JSON, SQL, and an enabled Ask button.
Submit overlapping queries and confirm stale completion cannot overwrite the
newer pending UI.

### Verification

```bash
uv run pytest tests/test_gradio_query_adapter.py tests/test_query_transaction.py tests/test_query_session.py -q
uv run pytest tests/test_dashboard.py tests/test_browser_contract.py -q
```

### Risks

Gradio callback order is brittle. Do not bundle Architecture-tab session changes
into this worker unless the output contract test exposes the need.

## Worker E: Verified Evidence Read Model Module

### Ownership

Primary files: `src/baseball_rag/llm_narration_guard.py`,
`src/baseball_rag/db/answer_assembly.py`,
`src/baseball_rag/db/grounded_database_types.py`,
`src/baseball_rag/db/queries.py`, `tests/test_service.py`, `tests/test_api.py`,
and `tests/test_grounded_database.py`.

Coordinate before editing: `src/baseball_rag/ui/presentation.py`,
`src/baseball_rag/db/player_stat_claims.py`,
`src/baseball_rag/db/biography_stat_vocabulary.py`, and `evals/questions.yaml`.

### Problem

The LLM narration guard protects DuckDB-backed answers, but it rebuilds facts
from generic `SourceRecord.rows`, rendered text, duplicated stat aliases, name
heuristics, and row order. The public Interface is generic source rows, while
the Implementation needs verified fact claims.

Deletion test: deleting the guard would move hallucination checks into stat and
grounded database callers, so it earns its keep. The shallow part is the source
row Interface: callers and tests must understand too many row-shape quirks.

### Target Shape

Introduce a `VerifiedEvidence` read model behind the existing
`apply_llm_flavored_narration(...)` Interface. Stat query, grounded database,
and future consensus evidence can become Adapters into the evidence Seam. The
narration guard should validate against evidence claims, not raw row dictionaries
or display text.

Do not move UI/source presentation policy into this Module. Its job is
verification semantics for LLM narration only.

### Benefits

Depth: narration receives a small Interface with stronger semantics. Leverage:
row-shape churn in stat and grounded database answers stays local to evidence
Adapters. Locality: hallucination guard tuning stays in one Module instead of
spreading into answer assembly or UI presentation.

### TDD Slices

1. RED: preserve an accepted `llm_flavored` stat-query narration that uses only
   row-backed facts. GREEN: adapt stat-query source rows into `VerifiedEvidence`.
2. RED: preserve rejection of a wrong-player or wrong-stat narration. GREEN:
   validate name/stat/value triples through evidence claims.
3. RED: row aliases such as `stat_value`, year fields, and rank order become
   evidence claims without relying on rendered answer text. GREEN: move alias
   knowledge into source-specific Adapters.
4. RED: name-only grounded database rows still reject unverified names while
   accepting verified multi-name lists. GREEN: model name-only evidence
   explicitly.

### Verification

```bash
uv run pytest tests/test_service.py tests/test_api.py tests/test_grounded_database.py -q
uv run pytest tests/test_request_execution.py tests/test_answer_presentation.py -q
```

Run the deterministic eval gate if answer text, fallback wording, source rows,
SQL visibility, or metadata change.

### Risks

Weakening the guard reopens hallucination risk. Changing fallback wording can
affect demos and eval artifacts. Evidence read models are for verification
semantics, not a replacement for public source JSON.

## Integration Review Checklist

The integration lead must verify:

1. Every worker used a public-behavior TDD slice before implementation.
2. No worker reopened a completed Module without a fresh public-behavior test.
3. DuckDB/Lahman remains the primary factual/stat authority.
4. No stored corpus, vector index, or Chroma replacement was added.
5. Public CLI, API, Gradio, source JSON, SQL, metadata, review, and eval shapes
   are preserved or intentionally documented.
6. A code-review subagent reviewed every worker change and final integration.
7. Focused tests, full tests, eval gate, and Browser smoke were run or skipped
   checks are explicitly explained.
8. The final commit includes docs, tests, and generated eval artifacts only when
   they intentionally changed.

## Coordinator Handoff Prompt

Use this prompt to start the implementation coordinator:

```text
Implement docs/architecture-fresh-deepening-handoff-plan.md end to end in
/Volumes/Envoy/projects/baseball-rag.

Start by reading:
- AGENTS.md
- README.md
- docs/architecture.md
- docs/architecture-followup-worker-handoff-plan.md
- docs/architecture-next-deepening-plan.md
- docs/architecture-fresh-deepening-handoff-plan.md

Rules:
- Use TDD vertical slices for every code-changing worker task.
- Use subagents wherever possible.
- Run a code-review subagent after every worker task and after final integration.
- Do not reopen completed Modules unless a fresh public-behavior test proves a
  new delta.
- Keep DuckDB/Lahman as the primary factual/stat authority.
- Do not add a stored corpus, vector index, or Chroma replacement.
- Preserve public CLI, API, Gradio, source JSON, SQL, metadata, review, and eval
  shapes unless a test proves an intentional behavior alignment.
- Update this handoff ledger as each worker lands.
- Run focused verification after each worker merge.
- Final verification must include ruff, mypy, full pytest, deterministic evals,
  and the Browser smoke at http://127.0.0.1:7861/.
- Commit the completed work and explain any unstaged changes.

Recommended order:
1. Worker A: Biography Contract Completeness Guard Module.
2. Worker D: Query Output Contract Module.
3. Worker B: LLM Router Adapter Module.
4. Worker E: Verified Evidence Read Model Module.
5. Worker C: Player Identity Authority Module.
6. Integration review, Browser smoke, eval gate, commit, and CI if pushed.
```
