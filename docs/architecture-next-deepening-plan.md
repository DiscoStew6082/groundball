# Next Architecture Deepening Implementation Plan

Status: Planned. This document is the handoff record for the four fresh
deepening opportunities identified after the completed 2026-05-23 architecture
follow-up in `docs/architecture-followup-worker-handoff-plan.md`.

No `CONTEXT.md` or `docs/adr/` exists in this repo. Workers should use
`README.md`, `docs/architecture.md`, and this file as the active vocabulary and
decision context. The prior handoff record is a completed ledger, not an open
plan.

## Scope

This plan covers four Modules:

1. LLM-Flavored Narration Guard Module
2. Grounded Database Planning Module
3. DuckDB Result Answer Assembly Module
4. Biography Stat Claim Vocabulary Module

Do not reopen these completed Modules unless a failing public-behavior test
shows a fresh delta: Claim Verification Evidence, Source Provenance, Routing
Decision, Request Lifecycle Ordering, Visible Evidence Presentation, Eval
Reporting, Freeform Planning And Routing Ownership, Biography Claim
Verification Presentation, Deterministic Stat SQL Execution, Architecture
Explorer Read Model Versus Gradio Rendering, Stat Semantics, Query Scope,
Deterministic Freeform Template Specs, Player Biography Answer, Support State
And Human Review, Conversation Context, or Gradio Query Adapter.

## Global Working Rules

- Use the TDD skill for each code-changing slice. Work in vertical
  red-green-refactor loops: one behavior test, minimal implementation, refactor
  while green, then repeat.
- Tests must cross public Interfaces. Avoid tests that lock to private helper
  names unless a compatibility Adapter is the behavior under test.
- Use the architecture vocabulary consistently: Module, Interface,
  Implementation, Depth, Seam, Adapter, Leverage, and Locality.
- Keep DuckDB/Lahman as the primary factual/stat authority. Use the LLM for
  narration and biography prose, not as the source of structured stat facts.
- Do not add a stored corpus, vector index, or Chroma replacement.
- Preserve public CLI, FastAPI, Gradio, source, SQL, metadata, review, and eval
  shapes unless a test proves an intentional behavior alignment.
- Preserve compatibility Adapters first. Delete or deprecate only after all
  callers and behavior tests have moved to the deeper Interface.
- Update this document as the implementation ledger as each slice lands.
- Run a code-review subagent after every worker task and after final
  integration. Address actionable findings before commit.
- A task is not complete until changes are committed and any unstaged changes
  are explained.
- If any branch is pushed to GitHub, wait for CI and confirm it is green.

## Parallelization Strategy

All workers may orient in parallel. Code edits should use this sequence unless
the integration lead narrows write locks further:

| Wave | Workers | Notes |
| --- | --- | --- |
| 1 | Worker A, Worker C | Mostly disjoint. Worker A owns LLM-flavored narration in `service.py`; Worker C owns biography stat-claim vocabulary and should avoid consensus presentation rewrites. |
| 2 | Worker B | Grounded database planning touches planning/runtime files and should run after vocabulary work has not changed stat registry semantics. |
| 3 | Worker D | DuckDB answer assembly coordinates with Worker A and Worker B because it may move grounded/stat result shaping out of `service.py` and `stat_query.py`. |
| 4 | Integration lead | Resolve conflicts, update this ledger, run full verification, run Browser smoke, review, and commit. |

Suggested branch names:

- `disco/llm-flavored-narration-guard`
- `disco/grounded-database-planning`
- `disco/duckdb-result-answer-assembly`
- `disco/biography-stat-claim-vocabulary`
- `disco/architecture-next-deepening-integration`

## Shared Definition Of Done

Every worker final report must include:

- Files changed.
- TDD slices completed, including the first failing behavior for each slice.
- Tests run.
- Public behavior preserved or intentionally aligned.
- Review subagent findings and fixes.
- Remaining risk.
- Unstaged changes, if any.

Final integration must run:

```bash
uv run ruff check src/ tests/ evals/
uv run mypy src/
uv run pytest -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
uv run baseball-rag-ui
```

For the UI command, use the Codex in-app Browser at
`http://127.0.0.1:7861/`, run the default query
`who had the most RBIs in 1962`, confirm Davis, Tommy plus rows, source JSON,
SQL, and an enabled Ask button, make the Browser visible, and leave the dev
server running.

## Worker A: LLM-Flavored Narration Guard Module

### Ownership

Primary files:

- `src/baseball_rag/service.py`
- `tests/test_service.py`
- `tests/test_api.py`
- `tests/test_grounded_database.py`

Coordinate before editing:

- `src/baseball_rag/provenance.py`
- `src/baseball_rag/stat_query.py`
- `src/baseball_rag/db/grounded_database_runtime.py`
- `docs/architecture.md`
- `README.md`

### Problem

The `answer_mode="llm_flavored"` path for `stat_query` and
`grounded_database_question` has useful behavior: DuckDB supplies verified rows
and the LLM may only narrate facts already present in that evidence. The current
Implementation sits inside `service.py` alongside request dispatch, answer-mode
metadata, grounded database answering, and terminal rendering. It includes
prompt construction, numeric token extraction, stat-claim extraction,
name-to-row matching, and fallback wording.

Deletion test: deleting the narration guard would push prompt, verification,
and fallback policy into stat and grounded database callers. The behavior earns
its keep, but keeping it inside the broad answer Module weakens Locality.

### Target Shape

Deepen a focused Module for verified LLM narration over DuckDB-backed answers.
Keep DuckDB/Lahman as the factual authority. Keep the existing public
`answer(..., answer_mode="llm_flavored")` Interface and API payload behavior
stable unless a behavior test proves a needed alignment.

Do not include player biographies or general explanations in this Module.
Biographies already use the biography JSON contract plus stat-claim
verification, and general explanations are intentionally open LLM answers.

### TDD Slices

1. RED: add or refactor a public-behavior test proving a verified narration for
   `stat_query` can use only row-backed facts and keeps metadata
   `answer_mode="llm_flavored"`.
   GREEN: move only enough prompt and narration policy behind the deeper Module
   to pass.
2. RED: add a public-behavior test proving a grounded database template answer
   rejects a cross-row year/stat/name claim and falls back to the verified
   DuckDB answer.
   GREEN: move row/name/stat validation behind the same Module.
3. RED: add a behavior test for LLM unavailability that preserves the current
   verified-DuckDB fallback wording and source payload.
   GREEN: concentrate error handling in the narration guard.
4. RED: add an API-level test proving `answer_mode="llm_flavored"` still
   exposes the same response fields and audit metadata.
   GREEN: preserve the public adapter behavior.
5. REFACTOR: reduce `service.py` to orchestration for this path. Keep
   compatibility helpers only if tests or import callers require them.

### Verification

Run:

```bash
uv run pytest tests/test_service.py tests/test_api.py tests/test_grounded_database.py -q
uv run pytest tests/test_request_execution.py -q
```

Run the deterministic eval gate if answer wording, source payloads, metadata,
or SQL visibility changes.

### Risks

- Tests around verified narration are intentionally strict because the guard
  prevents plausible LLM hallucinations.
- Do not loosen the guard by allowing reused numbers with wrong stats or
  misattributed names.
- Do not solve failures with token caps.

## Worker B: Grounded Database Planning Module

### Ownership

Primary files:

- `src/baseball_rag/db/grounded_database_runtime.py`
- `src/baseball_rag/db/grounded_database_intent.py`
- `src/baseball_rag/db/grounded_database_assembler.py`
- `src/baseball_rag/db/grounded_database_templates.py`
- `src/baseball_rag/db/grounded_database_types.py`
- `tests/test_grounded_database.py`

Coordinate before editing:

- `src/baseball_rag/routing/grounded_database_ownership.py`
- `src/baseball_rag/routing/query_router.py`
- `src/baseball_rag/service.py`
- `src/baseball_rag/db/stat_registry.py`
- `docs/architecture.md`

### Problem

Grounded database planning already has a valuable public Interface:
`query(...)` and `plan_query(...)` convert natural-language database questions
into constrained SQL results. The Implementation still requires maintainers to
understand deterministic templates, schema loading, LLM `QuerySpec` extraction,
team identity resolution, SQL assembly, SQL validation, and execution timeout
policy inside one runtime Module. The runtime imports underscored planning
helpers, and tests often reach into those helpers directly.

Deletion test: deleting the runtime Module would scatter planning, validation,
execution, and formatting across callers. It has Depth. Deleting the private
helper imports would mostly reveal missing public seams inside the planning
Implementation.

### Target Shape

Preserve the existing `query(...)` and `plan_query(...)` Interface. Deepen the
planning Implementation so deterministic templates, LLM-backed spec extraction,
team identity enrichment, and SQL assembly are local behind a clearer planning
Module. Keep execution and formatting behavior stable until a public-behavior
test proves a change.

Do not reopen completed routing-decision work. The router may still call the
grounded database ownership Adapter, but this worker owns planning Locality, not
route precedence.

### TDD Slices

1. RED: add a behavior test through `plan_query(...)` proving deterministic
   templates bypass the LLM and expose the same plan fields, params, and source
   detail.
   GREEN: move only enough template planning behind the deeper Module to pass.
2. RED: add a behavior test through `query(...)` proving LLM-backed planning
   still applies team identity and year enrichment before SQL assembly.
   GREEN: concentrate enrichment policy behind the planning Module.
3. RED: add a behavior test proving unsupported or ambiguous deterministic
   templates still return the existing unsupported result shape.
   GREEN: preserve unsupported plan/result behavior.
4. RED: add or adjust tests so callers stop importing private planning helpers
   when public behavior can cover the same rule.
   GREEN: keep compatibility helpers only where they are intentionally public
   enough for tests.
5. REFACTOR: keep SQL validation/execution readable, and do not change SQL text
   unless the behavior test names the expected visible change.

### Verification

Run:

```bash
uv run pytest tests/test_grounded_database.py tests/test_router.py -q
uv run pytest tests/test_request_execution.py tests/test_api.py -q
```

Run the deterministic eval gate if SQL text, query source labels, unsupported
reasoning, or row shapes change.

### Risks

- SQL text changes can affect audit hashes and eval baselines.
- Grounded database answers must remain parameterized/template assembled; do
  not accept model-written raw SQL.
- Keep old team-name behavior and historical team identity hints intact.

## Worker D: DuckDB Result Answer Assembly Module

### Ownership

Primary files:

- `src/baseball_rag/stat_query.py`
- `src/baseball_rag/service.py`
- `src/baseball_rag/db/queries.py`
- `src/baseball_rag/db/grounded_database_runtime.py`
- `src/baseball_rag/provenance.py`
- `tests/test_queries.py`
- `tests/test_grounded_database.py`
- `tests/test_answer_presentation.py`
- `tests/test_request_execution.py`

Coordinate before editing:

- Worker A if `service.py` narration code has moved.
- Worker B if grounded database plan/result objects have changed.
- `src/baseball_rag/outcomes.py`
- `src/baseball_rag/ui/presentation.py`
- `docs/api.md`

### Problem

Deterministic stat queries and grounded database questions both execute
DuckDB-backed plans and return `StructuredAnswer` payloads with sources, rows,
SQL, warnings, and unsupported/no-data outcomes. Their result-to-answer rules
are separate: `stat_query.py` owns stat answer text and no-data policy, while
`service.py` owns grounded database source shaping, truncation warning, and
unsupported reason mapping.

Deletion test: deleting the current result assembly helpers would push
`SourceRecord` construction, SQL visibility, row shaping, and unsupported/no-data
policy into multiple callers. The behavior deserves a deeper Module with a
small Interface.

### Target Shape

Deepen a DuckDB result answer assembly Module for public answer policy over
DuckDB-backed results. Do not reopen the completed `AnswerPresenter` visible
evidence Module; this work is about domain answer/source/outcome assembly before
UI presentation.

Keep public answer text, sources, SQL visibility, warning behavior, and
unsupported/no-data payloads stable unless a behavior test proves an intended
alignment.

### TDD Slices

1. RED: add a behavior test proving stat leaderboard answers still include the
   same answer text, rows, SQL, manifest, and intent after result assembly.
   GREEN: move only enough stat result shaping behind the deeper Module.
2. RED: add a behavior test proving grounded database zero-row answers preserve
   unsupported/no-data/ambiguous semantics and review reason.
   GREEN: move unsupported mapping behind the deeper Module.
3. RED: add a behavior test proving truncated grounded database answers keep
   the visible truncation warning and first-100 row behavior.
   GREEN: localize truncation and row shaping.
4. RED: add a behavior test proving player-specific stat no-data answers keep
   their no-alternate-leaderboard warning and source.
   GREEN: preserve special case policy.
5. REFACTOR: share source construction only where it increases Depth. Avoid a
   pass-through Module that simply renames `StructuredAnswer(...)`.

### Verification

Run:

```bash
uv run pytest tests/test_queries.py tests/test_grounded_database.py tests/test_answer_presentation.py tests/test_request_execution.py -q
uv run pytest tests/test_service.py tests/test_api.py -q
```

Run the deterministic eval gate if answer text, source JSON, SQL visibility,
warnings, metadata, or unsupported payloads change.

### Risks

- This slice overlaps with Worker A and Worker B. Start after their public
  Interfaces settle.
- Avoid hiding differences that are meaningful to users, such as player
  no-data warnings versus grounded database unsupported guidance.
- Keep manifest provenance attached to DuckDB-backed sources.

## Worker C: Biography Stat Claim Vocabulary Module

### Ownership

Primary files:

- `src/baseball_rag/db/stat_registry.py`
- `src/baseball_rag/biography_contract.py`
- `src/baseball_rag/player_biography.py`
- `src/baseball_rag/db/player_stat_claims.py`
- `tests/test_stat_registry.py`
- `tests/test_biography_contract.py`
- `tests/test_player_bio_query.py`
- `tests/test_player_stat_claims_consensus.py`

Coordinate before editing:

- `src/baseball_rag/db/secondary_sources/retrosheet.py`
- `src/baseball_rag/generation/prompt.py`
- `README.md`
- `docs/architecture.md`

### Problem

Biography stat-claim support is spread across several Modules:

- SQL stat definitions and aliases in `stat_registry.py`.
- The biography JSON repair prompt in `biography_contract.py`.
- Supplied-claim extraction regexes in `player_biography.py`.
- Contextual claim table inference and Retrosheet column mapping in
  `player_stat_claims.py`.

Some divergence is intentional: not every SQL-addressable stat is necessarily a
good biography-claim stat, and Retrosheet may not cover every Lahman stat. The
current Interface does not make the intended overlap and divergence explicit.

Deletion test: deleting `stat_registry.py` would spread formulas, aliases, and
sample rules everywhere, so it has real Depth. Deleting hardcoded prompt and
regex stat lists removes duplicated policy, which shows weaker Locality for
biography claim vocabulary.

### Target Shape

Deepen a biography stat-claim vocabulary Module that documents and serves the
stats supported by the biography JSON contract, supplied-claim extraction, claim
verification, and optional Retrosheet consensus evidence. Keep already-completed
SQL stat semantics, ranking direction, and Retrosheet formula adapter behavior
out of scope unless a public behavior test exposes drift.

Do not change the source-of-truth policy: Lahman/DuckDB remains primary, and
Retrosheet remains optional secondary consensus evidence.

### TDD Slices

1. RED: add a behavior test through a stable vocabulary Interface proving the
   intended biography claim stat set and its relationship to
   `stat_registry.supported_stats()`.
   GREEN: introduce only enough vocabulary locality to make the contract
   explicit.
2. RED: add a biography-contract behavior test proving repaired biography JSON
   accepts the same supported claim stats exposed by the vocabulary Interface,
   without asserting exact prompt prose.
   GREEN: route prompt construction through the shared vocabulary.
3. RED: add a supplied-biography query behavior test proving explicit supported
   claims are extracted into the answer payload and unsupported/non-verifiable
   claims keep the current unsupported or ignored behavior.
   GREEN: route extraction through the shared vocabulary without changing
   user-facing behavior.
4. RED: add a public consensus-verifier test proving ambiguous stats such as
   `SO` still use explicit or inferred table context correctly through
   `verify_player_stat_claims_consensus(...)`.
   GREEN: keep contextual table inference local and documented.
5. RED: add a public consensus-verifier test proving stats without optional
   Retrosheet coverage remain primary-only and explainable, while covered stats
   can still produce secondary evidence when local Retrosheet tables exist.
   GREEN: connect Retrosheet column coverage to the vocabulary without making
   Retrosheet required.
6. REFACTOR: remove duplicated hardcoded lists only after behavior tests cover
   the public contract.

### Verification

Run:

```bash
uv run pytest tests/test_stat_registry.py tests/test_biography_contract.py tests/test_player_bio_query.py tests/test_player_stat_claims_consensus.py -q
uv run pytest tests/test_service.py tests/test_api.py -q
```

Run the deterministic eval gate if biography warning text, metadata, source
rows, or supported-stat behavior changes.

### Risks

- Do not broaden biography claim support accidentally. Unsupported claims should
  stay explainable rather than silently trusted.
- Do not turn prompt wording into the source of truth; prompt wording should
  follow the vocabulary Module.
- Retrosheet coverage is optional and may be unavailable locally.

## Integration Lead Checklist

1. Read this plan, `README.md`, `docs/architecture.md`, and the completed
   `docs/architecture-followup-worker-handoff-plan.md`.
2. Confirm no worker is reopening completed Modules without a failing
   public-behavior test.
3. Assign write locks for overlapping files, especially `service.py`,
   `player_stat_claims.py`, `stat_query.py`, and `grounded_database_runtime.py`.
4. Require each worker to update this ledger as slices land.
5. Run focused tests after each worker merge.
6. Run a code-review subagent after each worker and after final integration.
7. Run the shared Definition Of Done, including Browser smoke.
8. Commit the final integrated state.
9. Explain any unstaged changes.
10. If pushed, verify GitHub CI is green.

## New Session Handoff Prompt

Use this prompt to start a new implementation session:

```text
We are in /Volumes/Envoy/projects/baseball-rag. Use the TDD skill for all
code-changing work. Use subagents wherever possible, and run a code-review
subagent after every worker task and after final integration. Do not call the
task complete until changes are committed and any unstaged changes are
explained. If you push to GitHub, wait for CI and confirm it is green.

Implement docs/architecture-next-deepening-plan.md end to end. Start by reading:

- AGENTS.md
- README.md
- docs/architecture.md
- docs/architecture-followup-worker-handoff-plan.md
- docs/architecture-next-deepening-plan.md

Important repo decisions:

- DuckDB/Lahman is the primary factual/stat authority.
- The LLM may narrate grounded results and generate biography prose, but it is
  not a source of structured stat facts.
- Do not add a stored corpus, vector index, Chroma replacement, or hidden
  compatibility surface.
- Do not reopen completed Modules from the previous architecture handoff unless
  a failing public-behavior test proves fresh friction.

Follow the Parallelization Strategy and write locks in the plan. Work through
the four planned Modules in the intended waves:

1. Wave 1: LLM-Flavored Narration Guard Module and Biography Stat Claim
   Vocabulary Module.
2. Wave 2: Grounded Database Planning Module.
3. Wave 3: DuckDB Result Answer Assembly Module.
4. Wave 4: final integration, review, verification, Browser smoke, and commit.

Use vertical red-green-refactor slices through public Interfaces. Keep the plan
document updated as the execution ledger. Preserve public CLI, FastAPI, Gradio,
source, SQL, metadata, review, and eval shapes unless a behavior test names an
intentional alignment.

After implementation, run:

uv run ruff check src/ tests/ evals/
uv run mypy src/
uv run pytest -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json

Then start or reuse the local UI with `uv run baseball-rag-ui`, open
http://127.0.0.1:7861/ in the Codex in-app Browser, run the default query
`who had the most RBIs in 1962`, confirm Davis, Tommy plus rows, source JSON,
SQL, and an enabled Ask button, make the Browser visible, and leave the dev
server running.

Commit the completed changes and report changed files, tests, Browser evidence,
review findings, remaining risk, and any unstaged changes.
```
