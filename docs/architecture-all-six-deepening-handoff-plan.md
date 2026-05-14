# Architecture All-Six Deepening Handoff Plan

This plan turns the latest architecture review into parallel worker-agent
handoffs. It covers all six selected deepening opportunities:

1. General Explanation Policy Module
2. Support Policy / Query Governance Module
3. Conversation Transcript Module
4. Biography LLM Contract Module
5. Claim Evidence Adapter Module
6. Freeform Template Stat Semantics Module

No `CONTEXT.md` or `docs/adr/` existed when this plan was written. Workers
should use `README.md`, `docs/architecture.md`,
`docs/architecture-deepening-handoff.md`, and
`docs/architecture-worker-handoff-plan.md` as the current project vocabulary
and decision record. The prior handoffs completed these slices and should not
be reopened by default:

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

Workers must treat this plan as a follow-up plan. If a slice appears to repeat
the completed work above, stop and narrow the slice to the fresh delta called
out in this file. Do not re-extract completed Modules just to match old plan
language.

This plan deliberately includes behavior alignment where runtime behavior,
tests, docs, or evals disagree. Behavior alignment must be explicit in the
worker handoff notes and in any commit message.

## Global Working Rules

- Use the TDD skill for every code-changing slice: one behavior test, minimal
  implementation, then refactor while green.
- Tests must verify public behavior through public Interfaces. Avoid tests that
  lock to private helper names unless preserving a compatibility Adapter is the
  point of that slice.
- Use the architecture vocabulary consistently: Module, Interface,
  Implementation, Depth, Seam, Adapter, Leverage, and Locality.
- Preserve public API, CLI, Gradio, source, SQL, metadata, review, and eval
  shapes unless a task explicitly calls out behavior alignment.
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
| 1 | Worker A, Worker C, Worker F | Mostly disjoint write sets. Worker C and Worker F are audit-first follow-ups to completed Modules; they should not edit until they have a failing behavior test for the remaining delta. |
| 2 | Worker D, Worker E | Can run in parallel only if Worker D owns biography contract normalization and Worker E owns claim evidence lookup. Shared changes to `PlayerStatClaim` require an integration lead lock. |
| 3 | Worker B | Run after Worker A and Worker C so query governance sees final explanation and conversation behavior. |
| 4 | Integration lead | Resolve cross-worker conflicts, update docs/evals, run full verification and browser smoke, then commit the integration state. |

Suggested branch/worktree layout:

- `codex/general-explanation-policy`
- `codex/conversation-transcript`
- `codex/freeform-template-stat-semantics`
- `codex/biography-llm-contract`
- `codex/claim-evidence-adapters`
- `codex/support-query-governance`
- `codex/all-six-integration`

## Shared Definition Of Done

Every worker must satisfy:

- TDD red-green-refactor cycles are visible in the work notes.
- Behavior tests pass for the worker-owned Module.
- Public payload compatibility is preserved or behavior alignment is documented.
- A code-review subagent has reviewed the worker changes.
- Actionable review findings are fixed.
- Changes are committed.
- `git status --short` is clean, or every unstaged change is explained.

Final integration must satisfy:

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
uv run baseball-rag-ui
```

For the UI command, use the Codex in-app Browser at
`http://127.0.0.1:7861/`, run the default-query smoke test, and leave the dev
server running.

## Worker A: General Explanation Policy Module

Status: implemented in this integration branch. Local stat definitions now route
through `GeneralExplanationPolicy`, broader explanations still use open LLM
fallback, docs/eval fixtures now describe corpus-backed stat definitions, and
focused tests cover local definition, open LLM, `llm_unavailable`, service
wiring, and legacy grounded-generation isolation. Worker review findings were
fixed, final integration verification passed, and this status is ready to commit.

### Ownership

Primary files:

- `src/baseball_rag/service.py`
- `src/baseball_rag/generation/prompt.py`
- `src/baseball_rag/generation/answer.py`
- `src/baseball_rag/corpus/stat_definitions/*.md`
- `src/baseball_rag/retrieval/static_vocab.py`
- `tests/test_generation.py`
- `tests/test_player_bio_query.py`
- `tests/test_api.py`
- `tests/test_eval_questions.py`
- `README.md`
- `docs/architecture.md`

Coordinate before editing:

- `evals/questions.yaml`
- `evals/baseline.json`
- `docs/eval-report.*`
- `docs/guardrail-coverage.md`

### Problem

Runtime behavior and docs disagree. `README.md` and `docs/architecture.md` say
stat explanations such as "what is OPS?" are open LLM answers with no Markdown
or vector-index lookup, but `service.py` first serves local Markdown stat
definitions. That makes the current Interface shallow: callers and tests must
know whether an explanation question is corpus-backed, LLM-backed, or both.

Deletion test: deleting the local stat-definition path would push provenance,
fallback, and docs/eval decisions into callers and tests. The behavior is
load-bearing, but it needs one Module with a clear policy.

### Behavior Alignment Decision

Default alignment for this plan: keep local stat definitions as the deterministic
first path for supported stat-definition questions, then update docs/evals so
they tell the truth. Open LLM answers remain the fallback for general
explanations that are not local stat definitions.

If the product owner instead wants all stat explanations to be open LLM answers,
pause this worker and record that decision before changing tests. That would be
a behavior change, not just a refactor.

### Target Shape

Deepen the general explanation policy Module so local stat-definition lookup,
open LLM generation, unavailable-LLM outcomes, source shaping, and docs/eval
expectations have one home. Keep the route intent `general_explanation`.

The Interface should hide whether the answer came from local stat definitions
or open LLM generation. Callers should receive only a `StructuredAnswer`.

### TDD Slices

1. RED: add or sharpen a behavior test showing `what is OPS` returns a local
   stat-definition answer without calling the LLM and includes corpus source
   provenance.
   GREEN: route the current behavior through the deeper Module.
2. RED: add a behavior test showing a non-local baseball explanation calls the
   open LLM path and preserves `llm_unavailable` when LM Studio fails.
   GREEN: move open explanation orchestration into the Module.
3. RED: add a docs/eval alignment test or fixture expectation proving the
   project describes local stat-definition behavior accurately.
   GREEN: update `README.md`, `docs/architecture.md`, and eval expectations as
   needed.
4. RED: add a test proving retrieval-era grounded generation helpers are not
   part of runtime explanation routing.
   GREEN: retire, isolate, or mark legacy helpers without breaking imports that
   tests still intentionally cover.
5. REFACTOR: remove duplicated wording and keep source labels stable.

### Verification

Run:

```bash
uv run pytest tests/test_generation.py tests/test_player_bio_query.py tests/test_api.py -q
uv run pytest tests/test_eval_questions.py -q
```

Run the deterministic eval gate if docs/eval fixtures change:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- Changing the default from local stat definitions to open LLM answers would
  reduce deterministic behavior and may make CI/live behavior less stable.
- Source type and source label changes can affect API and UI expectations.

## Worker B: Query Governance Follow-Up To Support State

Status: implemented in this integration branch. `execute_request()` now keeps
trace ownership and answer execution local while `QueryGovernance` observes the
completed request and owns audit metadata attachment, audit logging, review
queue application, and public review payload attachment. Existing support-state
behavior is preserved for ambiguous, no-data, unsupported, and
`llm_unavailable` answers. Worker review passed, final integration verification
passed, and this status is ready to commit.

### Ownership

Primary files:

- `src/baseball_rag/unsupported_policy.py`
- `src/baseball_rag/outcomes.py`
- `src/baseball_rag/support_state.py`
- `src/baseball_rag/request_execution.py`
- `src/baseball_rag/audit.py`
- `src/baseball_rag/review_queue.py`
- `src/baseball_rag/api/server.py`
- `tests/test_request_execution.py`
- `tests/test_audit.py`
- `tests/test_review_queue.py`
- `tests/test_support_state.py`
- `tests/test_api.py`

Coordinate before editing:

- `src/baseball_rag/conversation.py`
- `src/baseball_rag/ui/query_transaction.py`
- `evals/questions.py`

### Problem

The Support State And Human Review Module already exists and must be preserved.
The fresh friction is query governance sequencing. `execute_request()` still
coordinates audit and review with boolean flags and metadata mutation order,
while API callers must know which flags to set for governance behavior.

Deletion test: deleting `support_state.py` would spread completed support rules
back into audit and review queue callers, so do not do that. Deleting the
current boolean governance choreography would move sequencing rules into API,
CLI, and UI callers. That remaining choreography is the target.

### Behavior Alignment Decision

Preserve current public response shapes and the existing `answer_support_state`
Interface by default. Align behavior only where governance sequencing causes
the same answer to produce different audit or review snapshots. In those cases,
prefer structured `StructuredAnswer` fields over warning text or source-row
sniffing.

### Target Shape

Deepen a query governance Module so a completed request can be observed once and
enriched consistently. The Module should consume the existing support-state
Interface and own audit metadata attachment, review queue application, logging,
and public review payload construction.

`support_state.py` stays the support-policy Module. `audit.py` and
`review_queue.py` may remain internal Implementation details used by governance.

### TDD Slices

1. RED: add a support-state regression test proving ambiguous, no-data,
   unsupported, and `llm_unavailable` answers keep their current reviewability
   and audit reason behavior.
   GREEN: preserve or minimally adjust `answer_support_state()`.
2. RED: add a request-execution behavior test proving audit and review
   enrichment do not depend on callers remembering boolean ordering.
   GREEN: introduce the governance Module and keep API response shape stable.
3. RED: add an API behavior test for review item ID stability after governance
   metadata enrichment.
   GREEN: make review snapshot construction consume the existing support state.
4. RED: add a test proving CLI and Gradio request paths can use no-governance or
   trace-only behavior without persisting review items.
   GREEN: make governance an Adapter choice at the request-execution Seam.
5. REFACTOR: keep `execute_request()` focused on tracing, answer execution, and
   governance observation.

### Verification

Run:

```bash
uv run pytest tests/test_request_execution.py tests/test_audit.py tests/test_review_queue.py tests/test_support_state.py tests/test_api.py -q
```

If eval metadata changes, also run:

```bash
uv run pytest tests/test_eval_questions.py -q
```

### Risks

- Review IDs may change if stable ID inputs change. Treat that as behavior
  alignment and document it.
- API consumers depend on `unsupported_reason`, `review_reason`, `metadata`,
  and `review` fields.

## Worker C: Typed Conversation Transcript Follow-Up

Status: implemented in this integration branch. Raw API/UI transcript payloads
now normalize through `conversation_transcript.py` before follow-up resolution,
existing `conversation_turn()` shaping remains in `conversation.py`, pronoun
resolution prefers explicit context metadata, and malformed transcript entries
are ignored at adapter seams. Integrated review added `nameFirst`/`nameLast`
follow-up coverage, final verification passed, and this status is ready to
commit.

### Ownership

Primary files:

- `src/baseball_rag/conversation.py`
- `src/baseball_rag/request_dispatch.py`
- `src/baseball_rag/ui/presentation.py`
- `src/baseball_rag/ui/query_transaction.py`
- `src/baseball_rag/ui/query_session.py`
- `src/baseball_rag/api/server.py`
- `tests/test_conversation.py`
- `tests/test_request_execution.py`
- `tests/test_query_transaction.py`
- `tests/test_query_session.py`
- `tests/test_answer_presentation.py`
- `tests/test_api.py`

Coordinate before editing:

- `src/baseball_rag/provenance.py`
- `src/baseball_rag/service.py`

### Problem

The Conversation Context Module already owns turn shaping and follow-up
metadata policy. The fresh friction is that the transcript Interface remains an
implicit `list[dict[str, Any]]` shared by FastAPI, Gradio, follow-up resolution,
and presentation. Hidden row keys such as `name`, `player_name`, `full_name`,
`year`, `team`, and `stat_value` still determine whether follow-up questions
work.

Deletion test: deleting the existing `conversation_turn()` helper would
recreate completed work in Gradio and presentation callers, so do not do that.
Deleting the raw-dict transcript convention would force normalization rules
into API and UI Adapters. That convention is the target.

### Behavior Alignment Decision

Preserve tolerance for existing raw dict transcripts at API and Gradio Adapter
seams. Behavior alignment should make transcript shape explicit internally, not
break old request payloads or duplicate completed turn shaping.

### Target Shape

Deepen the conversation transcript Module so raw API/UI payloads normalize into
typed transcript facts before follow-up resolution. Existing compact-turn
construction stays in `conversation.py`; this follow-up adds a deeper internal
Interface around the accepted transcript shape.

### TDD Slices

1. RED: add a behavior test proving a raw API conversation payload is normalized
   and still resolves "tell me about the fifth player".
   GREEN: add the transcript normalization path.
2. RED: add a behavior test proving Gradio conversation turns still keep only
   the row facts needed for follow-up resolution.
   GREEN: route that behavior through the typed transcript path without moving
   the already-completed compact-turn helper out of `conversation.py`.
3. RED: add a test proving active-player pronoun resolution uses explicit
   context metadata before falling back to first result row.
   GREEN: centralize active player lookup.
4. RED: add a regression test for malformed transcript entries being ignored
   instead of crashing.
   GREEN: make normalization tolerant at Adapter seams.
5. REFACTOR: reduce raw `list[dict[str, Any]]` knowledge in request dispatch,
   UI presentation, and query transaction code.

### Verification

Run:

```bash
uv run pytest tests/test_conversation.py tests/test_request_execution.py tests/test_query_transaction.py tests/test_query_session.py tests/test_answer_presentation.py tests/test_api.py -q
```

Run one CLI/API behavior smoke if follow-up wording changes:

```bash
uv run pytest tests/test_cli_player_query.py tests/test_player_bio_query.py -q
```

### Risks

- API clients may send old raw dict conversations. Keep external Adapters
  tolerant.
- Query UI state and conversation state are separate; do not merge them unless
  a test proves the behavior.

## Worker D: Biography LLM Contract Follow-Up

Status: implemented in this integration branch. Biography JSON parsing, final
contract extraction from fenced/chattery output, repair retry prompting, claim
payload validation, and typed contract failure now live in
`biography_contract.py`; `PlayerBiographyCaseAnswerer` remains the route-case
orchestrator and service compatibility aliases remain patchable. Worker review
findings were fixed, final verification passed, and this status is ready to
commit.

### Ownership

Primary files:

- `src/baseball_rag/player_biography.py`
- `src/baseball_rag/generation/prompt.py`
- new biography contract Module if needed
- `tests/test_player_bio_query.py`
- `tests/test_player_biography_case.py`
- `tests/test_generation.py`
- `tests/test_request_execution.py`

Coordinate before editing:

- `src/baseball_rag/db/player_stat_claims.py`
- `src/baseball_rag/service.py`
- `src/baseball_rag/provenance.py`

### Problem

The Player Biography Answer Module already extracted route-case orchestration
from `service.py`, including player resolution, supplied claims, LLM JSON
repair, verification, and source shaping. The fresh friction is that the LLM
contract itself is still embedded in the broad biography Module: prompt
wording, response repair, JSON extraction, stat-claim validation, and typed
contract failure behavior are not named as a deep Module.

Deletion test: deleting `PlayerBiographyCaseAnswerer` or moving orchestration
back into `service.py` would reopen completed work, so do not do that. Deleting
the current contract helpers would push repair and validation details back into
the answerer. That contract Seam is the target.

### Behavior Alignment Decision

Preserve the current biography JSON contract fields:

- `answer`
- `stat_claims`
- stat claim fields `stat`, `value`, `scope`, `year`, `text`, and `table`

Behavior alignment is allowed only for currently accepted malformed LLM output
that contradicts the documented contract. Any tightening must preserve the
existing retry-on-malformed behavior.

### Target Shape

Deepen the biography LLM contract Module so prompt construction, response
repair, JSON extraction, stat-claim validation, and typed failure behavior sit
behind one Seam. The existing player biography answerer remains the route-case
orchestrator.

### TDD Slices

1. RED: add a behavior test for valid biography JSON with supported stat claims
   through the new contract Module while `PlayerBiographyCaseAnswerer` remains
   the public route-case Interface.
   GREEN: route parsing through the contract Module.
2. RED: add a behavior test proving markdown-fenced JSON and planning chatter
   are handled the same way as today.
   GREEN: move JSON extraction and fence stripping into the contract path.
3. RED: add a behavior test proving malformed first response triggers one repair
   request and returns the repaired contract.
   GREEN: move repair prompt and retry into the contract Module.
4. RED: add a behavior test proving invalid claim payloads become typed contract
   failures and map to `llm_unavailable` at the answerer level.
   GREEN: centralize failure mapping without changing answer shape.
5. REFACTOR: keep service-level compatibility aliases only if existing tests or
   callers still require them, and do not move route-case orchestration back
   into `service.py`.

### Verification

Run:

```bash
uv run pytest tests/test_player_bio_query.py tests/test_player_biography_case.py tests/test_generation.py tests/test_request_execution.py -q
```

If compatibility aliases are changed, run:

```bash
uv run pytest tests/test_api.py tests/test_cli_player_query.py -q
```

### Risks

- Live LLM output is messy. Do not make parsing stricter without a regression
  test showing why.
- `PlayerStatClaim` is also used by Worker E. Shared type changes need the
  integration lead lock.

## Worker E: Claim Evidence Adapter Module

Status: implemented in this integration branch. Lahman and Retrosheet
source-specific lookup now sit behind internal `ClaimEvidence` Adapter seams,
while consensus combination, row keys, source labels, warnings, and biography
presentation vocabulary remain in `player_stat_claims.py`. Focused tests cover
adapter combination plus existing primary-only and Retrosheet SQL behavior;
worker review passed, final verification passed, and this status is ready to
commit.

### Ownership

Primary files:

- `src/baseball_rag/db/player_stat_claims.py`
- `src/baseball_rag/db/stat_registry.py`
- `tests/test_player_stat_claims_consensus.py`
- `tests/test_player_bio_query.py`
- `tests/test_stat_registry.py`

Coordinate before editing:

- `src/baseball_rag/player_biography.py`
- `src/baseball_rag/db/secondary_sources/retrosheet.py`
- `data/secondary_sources/retrosheet/manifest.json`

### Problem

Lahman and Retrosheet are real evidence Adapters, but the current
Implementation mixes primary lookup, secondary lookup, source availability,
Retrosheet column discovery, stat expression adaptation, consensus status, row
shape, warning text, and presentation helpers in one large Module.

Deletion test: deleting the Retrosheet helpers would not remove complexity; it
would reappear inside consensus verification.

### Behavior Alignment Decision

Preserve current consensus categories, row keys, source labels, warnings, and
presentation shape. `player_stat_claims.py` remains the owner of
Lahman/Retrosheet presentation vocabulary and row keys from the completed
claim-verification presentation slice. This task is architectural unless a
source-specific bug is discovered and covered with a behavior test.

### Target Shape

Deepen the claim evidence Module so Lahman and Retrosheet source-specific lookup
sit behind evidence Adapters at one Seam. The consensus Implementation should
combine evidence results and choose consensus status; it should not own every
source's schema-probing details.

Use Adapter vocabulary only for the concrete Lahman and Retrosheet evidence
providers, because this is a real two-Adapter Seam.

### TDD Slices

1. RED: add a behavior test proving Lahman-only evidence produces the same
   primary-only consensus row and warning behavior as today.
   GREEN: move Lahman lookup behind an internal evidence Adapter.
2. RED: add a behavior test proving Retrosheet missing-table and missing-column
   cases preserve current unsupported warnings.
   GREEN: move Retrosheet schema probing behind its Adapter.
3. RED: add a behavior test proving conflicting Lahman/Retrosheet values still
   produce `conflict` with the same row keys.
   GREEN: make consensus combine evidence Adapter outputs.
4. RED: add a behavior test proving Retrosheet SQL uses the expected player id
   and season filters.
   GREEN: keep SQL generation source-local and provenance-ready.
5. REFACTOR: leave presentation helpers stable. If a future task wants to move
   presentation ownership, it needs a separate design decision because the prior
   handoff deliberately placed that vocabulary in `player_stat_claims.py`.

### Verification

Run:

```bash
uv run pytest tests/test_player_stat_claims_consensus.py tests/test_player_bio_query.py tests/test_stat_registry.py -q
```

If SQL text changes, also run:

```bash
uv run pytest tests/test_api.py::TestApi::test_query_endpoint_preserves_pitching_rate_stat_provenance -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- Retrosheet schemas are intentionally tolerant. Preserve optional-source
  behavior.
- Worker F may also touch `stat_registry.py`; coordinate expression/Adapter
  changes.

## Worker F: Freeform Template Stat Semantics Follow-Up

Status: implemented in this integration branch. The audit found remaining AVG
and ERA formula/qualification duplication in deterministic templates, so those
templates now render formula and guard fragments through the completed
`stat_registry` semantics while keeping phrase matching, achievement facts,
route ownership, and template source detail local. SQL text changed by
construction but behavior-focused rows/source-detail tests remain green; worker
review findings were fixed, eval gate passed, and this status is ready to
commit.

### Ownership

Primary files:

- `src/baseball_rag/db/freeform_templates.py`
- `src/baseball_rag/db/freeform_assembler.py`
- `src/baseball_rag/db/freeform_types.py`
- `src/baseball_rag/db/stat_registry.py`
- `tests/test_freeform.py`
- `tests/test_stat_registry.py`
- `tests/test_eval_questions.py`

Coordinate before editing:

- `src/baseball_rag/db/queries.py`
- `src/baseball_rag/db/player_stat_claims.py`
- `evals/baseline.json`

### Problem

The Stat Semantics Module and Deterministic Freeform Template Specs are already
complete. The fresh friction must be proven before editing: current templates
may still contain formula, guard, threshold, or ranking knowledge that now
belongs behind completed stat semantics. Achievement templates also still mix
domain facts, matching phrases, SQL assembly, and source detail in one Module.

Deletion test: if a candidate duplicate can be deleted from templates and the
complexity reappears in multiple callers, it belongs in the stat semantics
Module. If deletion simply removes dead duplication with no behavior effect,
prefer a small cleanup or no-op handoff note instead of a new abstraction.

### Behavior Alignment Decision

Preserve user-visible answers and source labels by default. SQL text may change
only after an audit-first test proves a real remaining duplicate after the
completed stat semantics work. If SQL changes, update audit/eval baselines only
after the deterministic eval gate proves behavior is stable.

Keep achievement facts in template code: Triple Crown means HR, RBI, and AVG
league leaders; 30-30 means at least 30 HR and 30 SB. Move shared stat math and
qualification semantics behind the stat semantics Module.

### Target Shape

Deepen only the remaining freeform template stat-semantics delta. Templates
should keep phrase matching and achievement definitions local to deterministic
freeform, while any reusable stat math or qualification semantics should come
from the completed stat semantics Module.

### TDD Slices

1. RED: add an audit-first test or assertion that identifies one remaining
   duplicated stat semantic in deterministic templates and proves the current
   behavior that must be preserved.
   GREEN: make the smallest change that routes that semantic through the
   completed stat semantics Module.
2. RED: add a behavior test proving qualified ERA or Triple Crown behavior
   remains unchanged after the semantic moves.
   GREEN: replace only the duplicated formula/guard/ranking fragment covered by
   the test.
3. RED: add a behavior test proving source detail still says which local
   deterministic template matched.
   GREEN: keep template provenance stable while changing internals.
4. RED: add a deterministic eval or fixture check if SQL text changes.
   GREEN: update baseline artifacts only after reviewing the SQL/provenance
   diff.
5. REFACTOR: if no real duplicate remains after the audit-first test, commit a
   documentation-only note or close the worker with no code changes rather than
   inventing a shallow Module.

### Verification

Run:

```bash
uv run pytest tests/test_freeform.py tests/test_stat_registry.py tests/test_eval_questions.py -q
uv run pytest tests/test_api.py::TestApi::test_query_endpoint_preserves_ambiguous_freeform_unsupported_reason -q
```

If SQL or eval artifacts change, run:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

### Risks

- SQL text changes alter audit hashes even when answers are unchanged.
- Worker E may also need stat semantics changes. Coordinate before changing the
  registry Interface.

## Integration Lead Checklist

The integration lead owns cross-worker consistency and final delivery.

1. Confirm no worker reopened completed prior handoff slices without an explicit
   behavior reason.
2. Resolve shared-file conflicts in this order:
   - `stat_registry.py`
   - `player_stat_claims.py`
   - `service.py`
   - `request_execution.py`
   - docs/eval artifacts
3. Run focused tests from each worker.
4. Run full static checks and tests:

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest -q
```

5. Run deterministic eval gate:

```bash
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

6. Run Gradio browser smoke:

```bash
uv run baseball-rag-ui
```

Open `http://127.0.0.1:7861/` in the Codex in-app Browser, make the Browser
visible, run the default query, and confirm:

- The answer names Davis, Tommy for the 1962 RBI default query.
- Rows render in the evidence table.
- Sources JSON renders without download/file-path issues.
- SQL is visible.
- The Architecture tab reflects the latest default-query path.
- The dev server remains running.

7. Run a code-review subagent on the integrated diff.
8. Fix actionable review findings.
9. Commit the integration state.
10. Explain any remaining unstaged changes. If pushed, wait for GitHub CI and
    confirm it is green.

## Final Handoff Template

Each worker final message should use this shape:

```markdown
## Worker <letter>: <module>

Changed files:
- ...

Behavior alignment:
- Preserved ...
- Changed ... because ...

TDD cycles:
- RED ...
- GREEN ...
- REFACTOR ...

Verification:
- `...` passed

Review:
- Code-review subagent: no findings / findings fixed

Remaining risk:
- ...

Git:
- Commit: `<sha> <message>`
- Unstaged changes: none / explained
```
