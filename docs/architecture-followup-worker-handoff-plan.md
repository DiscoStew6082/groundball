# Completed Architecture Follow-Up Worker Handoff Record

This record captures the worker-agent handoffs that turned the 2026-05-23
architecture review into completed implementation work. It covered six fresh
deepening opportunities:

1. Claim Verification Evidence Module
2. Source Provenance Module
3. Routing Decision Module
4. Request Lifecycle Ordering Module
5. Visible Evidence Presentation Module
6. Eval Reporting Module

## Implementation Status

Status: Completed. The six follow-up Modules were implemented and integrated in
commit `148ddd3` (`Deepen architecture follow-up modules`). The sections below
are historical handoff instructions, not current open work. Use this status
ledger as the source for what landed before starting any new follow-up work.

Completion summary:

- Claim verification evidence kept the public consensus verifier stable and
  preserved Lahman plus optional Retrosheet evidence rows, SQL, params, warning
  behavior, and compatibility payloads.
- Source provenance now centralizes compact primary and secondary manifest
  shaping in `src/baseball_rag/provenance.py`.
- Routing decisions now use stable route facts from
  `src/baseball_rag/routing/contracts.py` and an ordered decision chain in
  `src/baseball_rag/routing/decisions.py`, with compatibility exports preserved
  from `query_router.py`.
- Request lifecycle ordering now lives behind
  `src/baseball_rag/request_lifecycle.py`, while `execute_request(...)` remains
  the public adapter.
- Visible evidence presentation now lets `AnswerPresenter` select useful
  verification rows and SQL for multi-source answers while preserving the
  common DuckDB stat display.
- Eval reporting now uses `build_eval_report_payload` so CLI artifacts and API
  governance payloads share summary and case-list data without duplicating that
  shaping in the API endpoint.

Verification run for `148ddd3`:

- `uv run ruff check src/ tests/ evals/` -> passed
- `uv run mypy src/` -> passed
- `uv run pytest -q` -> 710 passed
- `uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json` -> `evals: 26 passed, 0 failed, 44 skipped`
- Codex in-app Browser smoke at `http://127.0.0.1:7861/` -> default query
  showed Davis/Tommy, result rows, source JSON, SQL, and an enabled Ask button;
  the dev server was left running.

Review follow-up:

- Review found that secondary-only and conflict rows needed visible row-level
  SQL/params aligned with the Retrosheet evidence; both findings were fixed
  before commit.
- Review found no remaining actionable integration blockers after the final
  pass.

No `CONTEXT.md` or `docs/adr/` exists in this repo. Workers should use
`README.md`, `docs/architecture.md`, and the archived architecture handoff docs
as the current project vocabulary and decision record.

Prior architecture handoffs completed these Modules and should not be reopened
unless a worker can show fresh friction with a failing public-behavior test:

- Freeform planning and routing ownership.
- Biography claim verification presentation.
- Deterministic stat SQL execution.
- Architecture Explorer read model versus Gradio rendering.
- Stat Semantics Module.
- Query Scope Module.
- Deterministic Freeform Template Specs.
- Player Biography Answer Module.
- Support State And Human Review Module.
- Conversation Context Module.
- Gradio Query Adapter Module.

Workers must treat this as a follow-up plan. If a slice appears to repeat
completed work, stop and narrow the slice to the fresh delta named here. Do not
re-extract completed Modules just to match old plan language.

## Global Working Rules

- Use the TDD skill for every code-changing slice: one public-behavior test,
  minimal implementation, then refactor while green.
- Tests must verify behavior through public Interfaces. Avoid tests that lock to
  private helper names unless preserving a compatibility Adapter is the point of
  the slice.
- Use the architecture vocabulary consistently: Module, Interface,
  Implementation, Depth, Seam, Adapter, Leverage, and Locality.
- Preserve public API, CLI, Gradio, source, SQL, metadata, review, and eval
  shapes unless the task explicitly calls out behavior alignment.
- Keep DuckDB/Lahman as the primary factual/stat authority. Treat Retrosheet as
  optional secondary consensus evidence for biography stat-claim verification,
  not as a replacement truth source for all query paths.
- Preserve compatibility Adapters first. Delete or deprecate them only after all
  callers and behavior tests have moved to the deeper Interface.
- Do not revert unrelated work. Each worker owns only the files listed for its
  task unless the integration lead grants an explicit write lock.
- Each worker final message must list changed files, tests run, behavior
  alignment decisions, remaining risk, and any unstaged changes.
- Run a code-review subagent after every worker task. Address actionable
  findings before commit.
- A worker task is not complete until its changes are committed and any
  remaining unstaged changes are explained.
- If any branch is pushed to GitHub, wait for CI and confirm it is green.
- Final integration must run the Gradio smoke contract: start or reuse
  `uv run baseball-rag-ui`, open `http://127.0.0.1:7861/` in the Codex in-app
  Browser, make the Browser visible, run the default query, confirm Davis,
  Tommy plus rows, sources, and SQL, and keep the dev server running.

## Parallelization Strategy

All workers may start with read-only orientation in parallel. Code edits should
use these waves unless the integration lead assigns narrower write locks.

| Wave | Workers | Parallel notes |
| --- | --- | --- |
| 1 | Worker A, Worker C, Worker F | Mostly disjoint write sets. Worker C changes routing contracts while Worker A touches verification. Worker F works outside runtime query code. |
| 2 | Worker B, Worker E | Run after Worker A clarifies consensus evidence shape. Worker E should wait for any source row/schema changes from Worker A and provenance shape from Worker B. |
| 3 | Worker D | Run after routing and evidence presentation settle, because lifecycle ordering is easiest to validate once downstream seams are stable. |
| 4 | Integration lead | Resolve cross-worker conflicts, update docs/evals, run full verification and Browser smoke, then commit the integration state. |

Suggested branch/worktree layout:

- `codex/claim-verification-evidence`
- `codex/source-provenance-module`
- `codex/routing-decision-module`
- `codex/request-lifecycle-ordering`
- `codex/visible-evidence-presentation`
- `codex/eval-reporting-module`
- `codex/architecture-followup-integration`

## Shared Definition Of Done

Every worker must satisfy:

- TDD red-green-refactor cycles are visible in the work notes.
- Behavior tests pass for the worker-owned Module.
- Public payload compatibility is preserved or behavior alignment is documented.
- A code-review subagent has reviewed the worker changes.
- Actionable review findings are fixed.
- Changes are committed.
- `git status --short --untracked-files=all` is clean, or every unstaged change
  is explained.

Final integration must satisfy:

```bash
uv run ruff check src/ tests/ evals/
uv run mypy src/
uv run pytest -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
uv run baseball-rag-ui
```

For the UI command, use the Codex in-app Browser at
`http://127.0.0.1:7861/`, run the default-query smoke test, and leave the dev
server running.

## Worker A: Claim Verification Evidence Module

### Ownership

Primary files:

- `src/baseball_rag/db/player_stat_claims.py`
- `src/baseball_rag/player_biography.py`
- `tests/test_player_stat_claims_consensus.py`
- `tests/test_player_bio_query.py`

Coordinate before editing:

- `src/baseball_rag/db/stat_registry.py`
- `src/baseball_rag/provenance.py`
- `data/secondary_sources/retrosheet/manifest.json`
- `README.md`
- `docs/architecture.md`

### Problem

The public claim-verification Interface is useful:
`verify_player_stat_claims_consensus(...)` compares Lahman primary evidence with
Retrosheet secondary evidence, and player biographies consume that Interface.
The current Implementation is doing too much in one file: Lahman lookup,
Retrosheet lookup, optional schema probing, source-specific SQL construction,
and consensus status policy all live inside `player_stat_claims.py`.

Deletion test: deleting the current claim-verification Module would push claim
status, source lookup, SQL, and warning behavior into `player_biography.py` and
tests. The Module earns its keep, but the internal seams are now real because
Lahman and Retrosheet are two concrete evidence Adapters.

Do not reopen the completed biography claim verification presentation slice.
This worker owns evidence lookup and consensus policy locality, not a
user-facing rewrite of the wording.

### Target Shape

Keep the existing public claim-verification seam stable. Deepen the Module by
concentrating source-specific behavior behind internal Lahman and Retrosheet
evidence Adapters, then leave consensus status policy in one local place.

The worker should not propose or implement a new public claim-verification
Interface unless a failing behavior test proves the current public seam cannot
support the refactor.

### TDD Slices

1. RED: add a public-behavior test proving consensus still calls both Lahman and
   Retrosheet evidence paths and preserves the existing row shape for
   `verified_by_all`, `verified_primary_only`, `verified_secondary_only`,
   `contradicted_by_all`, and `conflict`.
   GREEN: move only enough lookup behavior behind internal Adapters to pass.
2. RED: add a behavior test for optional Retrosheet absence that preserves the
   current primary-only status and warning behavior.
   GREEN: move missing-table and missing-column probing behind the Retrosheet
   Adapter.
3. RED: add a behavior test for Retrosheet SQL using `retroID`, season, and
   `stattype`/`gametype` filters where those columns exist.
   GREEN: keep source-specific SQL construction local to the Retrosheet Adapter.
4. RED: add or retain a supplied-biography query test proving the player
   biography route still exposes consensus rows and warnings through the public
   answer payload.
   GREEN: update `PlayerBiographyCaseAnswerer` only if needed for compatibility.
5. REFACTOR: remove duplicate source lookup helpers that are no longer needed.
   Keep compatibility helpers if tests or callers intentionally import them.

### Verification

Run:

```bash
uv run pytest tests/test_player_stat_claims_consensus.py tests/test_player_bio_query.py -q
uv run pytest tests/test_service.py tests/test_api.py -q
```

Run the deterministic eval gate if source rows, warnings, SQL, or metadata
change:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- Retrosheet data is optional. Missing files, missing columns, and missing
  `people.retroID` mappings must remain explainable, not fatal.
- SQL text changes can affect audit hashes and eval baselines. Treat those as
  visible behavior changes.

## Worker B: Source Provenance Module

### Ownership

Primary files:

- `src/baseball_rag/provenance.py`
- `src/baseball_rag/db/player_stat_claims.py`
- `src/baseball_rag/db/secondary_sources/retrosheet.py`
- `tests/test_provenance.py`
- `tests/test_player_stat_claims_consensus.py`
- `tests/test_retrosheet_downloader.py`

Coordinate before editing:

- `data/manifest.json`
- `data/secondary_sources/retrosheet/manifest.json`
- `src/baseball_rag/api/server.py`
- `docs/api.md`
- `README.md`
- `docs/architecture.md`

### Problem

`compact_data_manifest()` reads only `data/manifest.json`, which describes the
primary Lahman-derived data. Consensus answers then mutate that compact primary
manifest with a synthetic `consensus_sources` list. Meanwhile Retrosheet has its
own downloader and manifest path. The provenance Interface is shallower than
current runtime behavior: answers can claim Lahman plus Retrosheet consensus,
but source manifest locality lives across provenance, claim verification, and
secondary-source download code.

Deletion test: deleting the provenance Module would scatter dataset name,
download metadata, file checksums, coverage, and source attribution into answer
builders and API code. The Module is valuable, but it should hide multi-source
manifest shape behind one Interface.

### Target Shape

Deepen provenance so primary and secondary source manifests are shaped in one
place. Lahman remains the primary structured-stat provenance. Retrosheet is
optional secondary consensus provenance and should be represented only when the
manifest or availability evidence exists.

Do not promote Retrosheet to the source of truth for all stat answers. Its
scope is biography stat-claim consensus unless a future ADR changes that.

### TDD Slices

1. RED: add a provenance behavior test showing a compact primary manifest keeps
   the current dataset, download, coverage, and file fields.
   GREEN: preserve the existing `compact_data_manifest()` behavior.
2. RED: add a behavior test showing consensus provenance can include a compact
   secondary Retrosheet manifest when `data/secondary_sources/retrosheet/manifest.json`
   is present.
   GREEN: add the smallest provenance helper needed by claim verification.
3. RED: add a behavior test showing missing or placeholder Retrosheet manifest
   state does not break answer generation and is represented as optional or
   unavailable, not as primary provenance.
   GREEN: make secondary manifest loading tolerant and explicit.
4. RED: add a player-claim consensus presentation test proving answer sources
   expose Lahman primary plus Retrosheet secondary provenance through the public
   `SourceRecord.data_manifest` payload.
   GREEN: route `consensus_data_manifest()` through the deeper provenance Module.
5. REFACTOR: remove synthetic provenance shaping from claim verification where
   provenance can own it.

### Verification

Run:

```bash
uv run pytest tests/test_provenance.py tests/test_player_stat_claims_consensus.py tests/test_retrosheet_downloader.py -q
uv run pytest tests/test_api.py::TestApi::test_sources_endpoint_returns_manifest -q
```

Run the deterministic eval gate if source metadata changes:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- API clients may already inspect `sources[].data_manifest`. Preserve existing
  primary manifest fields.
- The checked-in Retrosheet manifest may be empty or generated from optional
  local data. Do not make deterministic tests depend on network downloads.

## Worker C: Routing Decision Module

### Ownership

Primary files:

- `src/baseball_rag/routing/query_router.py`
- `src/baseball_rag/routing/grounded_database_ownership.py`
- `src/baseball_rag/routing/__init__.py`
- `src/baseball_rag/query_scope.py`
- `tests/test_router.py`
- `tests/test_router_player_bio.py`
- `tests/test_router_player_detection.py`
- `tests/test_query_scope.py`

Coordinate before editing:

- `src/baseball_rag/request_dispatch.py`
- `src/baseball_rag/stat_query.py`
- `src/baseball_rag/db/grounded_database_runtime.py`
- `evals/questions.yaml`

### Problem

Public route facts such as `TimePeriod`, `StatQueryCase`, and
`PlayerBiographyCase` live inside `query_router.py`, the same file that owns
deterministic biography checks, supplied-claim verification routing, heuristic
stat and explanation extraction, grounded database precedence, LLM JSON parsing,
and fallback ordering. Downstream Modules import public facts from an
Implementation-heavy Module.

Deletion test: deleting `query_router.py` would not remove route facts or
routing rules; it would force them into request dispatch, query scope, stat
query planning, and tests. The routing Module is earning its keep, but its
Interface and Implementation are tangled.

This is not a redo of completed grounded/freeform ownership work. That work
created a thin ownership helper for deterministic grounded database questions.
The fresh friction is overall routing decision ordering and public route facts.

### Target Shape

Deepen routing around stable route facts and ordered route decisions. Keep
`route(question)` as the public seam while moving public facts and internal
decision rules into clearer local Modules as needed.

Treat LLM routing, deterministic routing, and heuristic fallback as internal
Adapters producing the same route facts.

### TDD Slices

1. RED: add or sharpen a routing behavior test proving route facts can be
   imported from a stable routing contract without importing implementation
   helpers.
   GREEN: move route fact dataclasses and `TimePeriod` types behind a stable
   routing contract while preserving compatibility imports.
2. RED: add a behavior test covering the ordered precedence of supplied claim
   verification, player biography, deterministic stat query, grounded database
   ownership, LLM routing, and heuristic fallback.
   GREEN: extract ordering into a route decision Module without changing public
   outcomes.
3. RED: add a behavior test for a query where deterministic grounded database
   ownership must beat a competing stat route.
   GREEN: keep the grounded database ownership seam intact while making its role
   explicit in the route decision chain.
4. RED: add a query-scope test proving `resolve_query_scope(...)` depends on
   stable route facts, not router Implementation details.
   GREEN: update imports and compatibility re-exports.
5. REFACTOR: remove dead route helper coupling only after compatibility tests
   are green.

### Verification

Run:

```bash
uv run pytest tests/test_router.py tests/test_router_player_bio.py tests/test_router_player_detection.py tests/test_query_scope.py -q
uv run pytest tests/test_service.py tests/test_eval_questions.py -q
```

Run the deterministic eval gate if route outcomes change:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- Route precedence is user-visible. A refactor that changes intent is behavior
  alignment, not cleanup.
- Compatibility imports may be needed for tests and callers. Preserve them
  until the integration lead removes them deliberately.

## Worker D: Request Lifecycle Ordering Module

### Ownership

Primary files:

- `src/baseball_rag/request_execution.py`
- `src/baseball_rag/service.py`
- `src/baseball_rag/request_dispatch.py`
- `tests/test_request_execution.py`
- `tests/test_service.py`

Coordinate before editing:

- `src/baseball_rag/query_governance.py`
- `src/baseball_rag/audit.py`
- `src/baseball_rag/review_queue.py`
- `src/baseball_rag/api/server.py`
- `src/baseball_rag/ui/query_transaction.py`

### Problem

One user request is ordered across tracing, answer-mode validation, follow-up
resolution, unsupported policy, routing, answer dispatch, LLM flavoring,
metadata mutation, and governance observation. Today that ordering crosses
`execute_request(...)`, `service.answer(...)`, and `RequestAnswerDispatcher`.

Deletion test: deleting any one of these Modules would not remove lifecycle
complexity; it would move ordering rules into the other two. The Modules are
useful, but their Interfaces overlap enough that request-lifecycle bugs require
maintainers to reason across all three.

Do not reopen the completed Query Governance or Support State work. This worker
owns request ordering and locality, not a rewrite of audit/review behavior.

### Target Shape

Deepen the request lifecycle so callers get one stable Interface for "run one
question" while ordering details remain local. Preserve the current public
`answer(...)` and `execute_request(...)` behavior unless a test proves a
compatibility Adapter is needed.

### TDD Slices

1. RED: add a public behavior test proving answer mode is validated once and is
   present in final metadata for both `answer(...)` and `execute_request(...)`.
   GREEN: localize answer-mode ordering without changing payloads.
2. RED: add a behavior test proving unsupported policy runs after follow-up
   resolution and before route dispatch.
   GREEN: make the lifecycle order explicit behind a deeper Module.
3. RED: add a trace behavior test proving `execute_request(...)` owns trace
   start/finish only when no trace already exists, and preserves route type.
   GREEN: keep trace ownership local to the lifecycle.
4. RED: add a governance observation test proving audit/review flags still
   observe the completed answer after metadata and trace are available.
   GREEN: preserve `QueryGovernance` as the observer, not the lifecycle owner.
5. REFACTOR: remove duplicate metadata mutations and dispatcher construction if
   the deeper lifecycle Interface makes them redundant.

### Verification

Run:

```bash
uv run pytest tests/test_request_execution.py tests/test_service.py tests/test_audit.py tests/test_review_queue.py -q
uv run pytest tests/test_api.py tests/test_query_transaction.py -q
```

Run the deterministic eval gate if answer metadata, unsupported behavior, or
route dispatch changes:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- Ordering bugs are subtle and usually visible through API/UI behavior, not
  helper tests. Keep tests at public seams.
- Nested tracing behavior matters for API and Gradio adapters. Preserve it.

## Worker E: Visible Evidence Presentation Module

### Ownership

Primary files:

- `src/baseball_rag/ui/presentation.py`
- `src/baseball_rag/ui/query_transaction.py`
- `src/baseball_rag/ui/gradio_adapter.py`
- `tests/test_answer_presentation.py`
- `tests/test_query_transaction.py`
- `tests/test_browser_contract.py`

Coordinate before editing:

- `src/baseball_rag/web_app.py`
- `src/baseball_rag/player_biography.py`
- `src/baseball_rag/db/player_stat_claims.py`
- `docs/demo-checklist.md`

### Problem

`AnswerPresenter` is a promising Module, but its current Interface flattens the
first source into rows and SQL. That gives good leverage for common DuckDB stat
answers, but it is shallow for multi-source biography and consensus evidence.
Those answers may include player identity, LLM prose, stat-claim verification
rows, warnings, Lahman evidence, Retrosheet evidence, and multiple provenance
facts. The Browser contract mostly covers the happy stat path.

Deletion test: deleting `AnswerPresenter` would push row shaping, SQL choice,
source JSON safety, chat text, and conversation-turn shaping back into
`QueryTransaction` and `web_app.py`. The Module is earning its keep, but its
visible evidence Interface needs more depth.

Do not reopen the completed Gradio Query Adapter slice. This worker owns visible
evidence presentation, not page-builder wiring.

### Target Shape

Deepen visible evidence around the user-facing question: what rows, SQL,
sources, warnings, and verification details should be visible for each answer
type? Gradio remains a concrete Adapter that maps presented evidence into
Gradio outputs.

### TDD Slices

1. RED: add an answer-presentation test proving a normal DuckDB stat answer
   still displays rows and SQL from the primary source exactly as today.
   GREEN: preserve current common-path behavior.
2. RED: add a presentation test for a biography consensus answer with
   verification rows and warnings, proving visible rows are useful and not lost
   behind first-source assumptions.
   GREEN: deepen row selection while preserving source JSON.
3. RED: add a presentation test proving SQL selection remains explicit when
   multiple sources exist or when only verification SQL is available.
   GREEN: localize SQL visibility policy in `AnswerPresenter`.
4. RED: add a browser-contract or query-transaction test proving stale/failed
   turns clear visible evidence panels and do not leak old rows or SQL.
   GREEN: preserve transaction behavior through the deeper presenter.
5. REFACTOR: remove evidence-shaping assumptions from query transaction or
   Gradio adapter if they become redundant.

### Verification

Run:

```bash
uv run pytest tests/test_answer_presentation.py tests/test_query_transaction.py tests/test_gradio_query_adapter.py -q
uv run pytest tests/test_browser_contract.py tests/test_gradio.py -q
```

If UI behavior changes, run the Browser smoke:

```bash
uv run baseball-rag-ui
```

Open `http://127.0.0.1:7861/` in the Codex in-app Browser, run the default
query, confirm Davis/Tommy rows, sources, and SQL, and keep the server running.

### Risks

- Rows and SQL are portfolio/demo surfaces. Preserve the default stat-query
  display exactly unless behavior alignment is explicit.
- Multi-source evidence can become noisy. Favor a small, predictable visible
  Interface over dumping every internal detail into the table.

## Worker F: Eval Reporting Module

### Ownership

Primary files:

- `evals/questions.py`
- `evals/questions.yaml`
- `src/baseball_rag/api/server.py`
- `tests/test_eval_questions.py`
- `tests/test_api.py`

Coordinate before editing:

- `evals/baseline.json`
- `docs/eval-report.md`
- `docs/eval-report.json`
- `docs/guardrail-coverage.md`
- `.github/workflows/ci.yml`

### Problem

The eval gate is high-value, but one file currently owns case selection,
execution, validation, Markdown rendering, JSON artifact shaping, guardrail
coverage, baseline comparison, CLI parsing, and API endpoint payload support.
The API endpoint rebuilds parts of the payload shape separately.

Deletion test: deleting `evals/questions.py` would scatter release-gate rules
across CI, API, docs, and tests. The Module earns its keep, but its Interface is
nearly as complex as its Implementation.

### Target Shape

Deepen the eval/reporting Module so "run the deterministic release gate and
produce report artifacts" is the stable Interface. CLI, API, Markdown, JSON,
guardrail coverage, and baseline comparison should behave like Adapters around
that Interface.

Do not change eval semantics to make the gate easier. If expected behavior
changes, update fixtures and baselines only after a visible behavior decision.

### TDD Slices

1. RED: add an eval test proving the same report artifact shape can drive both
   CLI writes and API payloads.
   GREEN: introduce a shared report payload builder without changing output.
2. RED: add a test proving deterministic case selection, live-case skipping,
   and service requirements remain unchanged.
   GREEN: localize selection policy behind the deeper eval Interface.
3. RED: add a test proving validation failures, unsupported expectations, SQL
   checks, row checks, and manifest checks still produce the same failure text.
   GREEN: preserve validation behavior while separating validation from report
   rendering.
4. RED: add a guardrail coverage test proving Markdown and API guardrail payload
   derive from the same coverage model.
   GREEN: extract shared guardrail coverage shaping.
5. RED: add a baseline comparison test proving `PASS`, `WARN`, and `BLOCK`
   recommendations remain compatible.
   GREEN: keep comparison policy local to the eval Module.
6. REFACTOR: split rendering/adapters only after the public artifact and API
   tests are green.

### Verification

Run:

```bash
uv run pytest tests/test_eval_questions.py tests/test_api.py -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

If reports or baselines change, include the generated docs in the worker commit
and explain the behavior alignment.

### Risks

- The eval gate is a release contract. Refactors that alter case selection,
  recommendation labels, or failure text can hide regressions.
- API governance consumers may depend on the current `/evals/report` shape.
  Preserve compatibility or document the change explicitly.

## Integration Lead Checklist

Historical checklist used for the `148ddd3` integration:

1. Rebase or merge workers in wave order.
2. Resolve conflicts without reverting unrelated user changes.
3. Audit public payload compatibility for API, CLI, Gradio, source rows, SQL,
   metadata, review payloads, and eval artifacts.
4. Run focused suites for every worker-owned area.
5. Run full verification:

   ```bash
   uv run ruff check src/ tests/ evals/
   uv run mypy src/
   uv run pytest -q
   uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
   ```

6. Run the Gradio Browser smoke at `http://127.0.0.1:7861/` and keep the server
   running.
7. Run a final code-review subagent over the integrated diff.
8. Address actionable review findings.
9. Commit the integration state.
10. Explain any remaining unstaged changes.
11. If pushed, confirm GitHub CI is green before declaring done.
