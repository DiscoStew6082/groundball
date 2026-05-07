# Architecture Deepening Plan

## Goal

Create a future implementation handoff for deepening Baseball RAG's existing
modules without changing product behavior first.

This plan should be handed to a new Codex conversation as the starting prompt.
The coordinator should use TDD, subagents wherever possible, and a code-review
subagent after every phase. Each completed phase must end in a commit with no
unexplained unstaged changes.

The six deepening opportunities are sequenced foundations first:

1. Request-to-answer spine
2. Structured unsupported/review reasons
3. Corpus document and lifecycle module
4. Retrieval decision module
5. `stat_query` module
6. `freeform_query` planning seam

## Operating Rules

- Use the TDD skill for all implementation work: write one behavior-focused
  tracer test, make it pass, then continue vertically.
- Use subagents wherever possible. The coordinator owns sequencing and
  integration; implementation subagents own disjoint write sets.
- Run a code-review subagent after every phase. Do not commit until review
  findings are addressed or explicitly deferred in the phase notes.
- Preserve user changes. If the worktree is dirty, identify unrelated changes
  before editing and never revert them without explicit instruction.
- Commit each completed phase before starting the next phase. The commit message
  should name the deepened module.
- Explain any unstaged changes at the end of every phase.
- If a branch is pushed to GitHub, wait for CI to come back green before
  declaring the pushed work complete.

## Compatibility Defaults

- Public response changes are additive only.
- Preserve existing response fields, CLI output, Gradio behavior, eval IDs, and
  deterministic eval behavior unless a phase explicitly changes them with tests.
- New typed fields may be added to internal models and public payloads, but
  existing callers must continue to work.
- Prefer deeper modules over broad new seams. One adapter is hypothetical; two
  adapters make the seam real.
- The interface is the test surface. Tests should verify behavior through public
  interfaces, not private helper shape.

## Subagent Model

Use this model in the future conversation:

- Coordinator: reads the plan, checks `git status`, opens the relevant files,
  creates a phase checklist, and integrates all work.
- Implementation subagent: owns one phase or one disjoint slice of a phase. It
  must edit files directly, list changed files, list tests added/updated, and
  report verification commands.
- Explorer subagent: answers narrow questions before edits when a phase has
  uncertain call sites or hidden coupling.
- Code-review subagent: runs after every phase. It should review for behavior
  regressions, public interface drift, missing tests, accidental broad seams,
  and whether the module is actually deeper.

Every subagent handoff should include:

- Phase goal
- Files or responsibility it owns
- Existing behavior that must stay compatible
- Required tests or verification
- Instruction not to revert others' edits

## Sequencing

The phases intentionally start with answer lifecycle foundations before the
domain-specific query modules. Later phases can then use shared request
execution, structured reasons, and corpus/retrieval contracts instead of
inventing local variants.

Do not run phases in parallel unless their write sets are disjoint and the
coordinator can integrate them before tests. Safe parallel exploration is fine;
parallel implementation should be conservative.

## Phase 1: Request-To-Answer Spine

### Goal

Introduce one shared request execution path for CLI, FastAPI, and Gradio so a
question becomes one routed, traced, audited answer.

### Intended Module Depth

The request-to-answer module should hide lifecycle complexity behind a small
interface. Callers should not need to know how trace start/finish, audit
metadata, review attachment, route dispatch, and text rendering are ordered.

### Likely Files

- `src/baseball_rag/service.py`
- `src/baseball_rag/api/server.py`
- `src/baseball_rag/cli.py`
- `src/baseball_rag/web_app.py`
- `tests/test_api.py`
- `tests/test_dashboard.py`
- `tests/test_pipeline_tracing_integration.py`

### TDD Starting Tests

- Add a behavior test proving Gradio structured response with a diagram runs the
  answer path once and still records a trace.
- Add or update an API behavior test proving `/query` still returns existing
  metadata and review payload shape.
- Add or update a CLI behavior test proving CLI text rendering still delegates
  through the shared answer path.

### Implementation Notes

- Create a first-class request execution module or function that owns answer
  lifecycle for one question.
- Keep CLI as a thin text adapter.
- Keep FastAPI as a thin HTTP adapter that returns the existing response shape.
- Keep Gradio as a thin UI adapter that reuses the same execution result for
  answer display and architecture trace animation.
- Preserve existing `StructuredAnswer.to_dict()` fields.

### Verification

- Run targeted request, API, dashboard, and tracing tests.
- Run the full test suite before the phase commit.

### Done Criteria

- CLI, FastAPI, and Gradio share one request execution path.
- Gradio does not answer the same question twice only to animate the diagram.
- Existing public response fields still exist.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that lifecycle ordering is local to the new request-to-answer module.
- Check that no public response fields were removed or renamed.
- Check that trace, audit, and review are attached exactly once.
- Check that tests verify observable behavior, not private helper names.

## Phase 2: Structured Unsupported/Review Reasons

### Goal

Make unsupported and review reasons structured data instead of inferred prose.

### Intended Module Depth

The answer model should expose a stable reason interface. Audit and review queue
adapters should consume that interface instead of parsing answer text or warning
phrases.

### Likely Files

- `src/baseball_rag/provenance.py`
- `src/baseball_rag/audit.py`
- `src/baseball_rag/review_queue.py`
- `src/baseball_rag/service.py`
- `tests/test_audit.py`
- `tests/test_review_queue.py`
- `tests/test_api.py`

### TDD Starting Tests

- Add a review queue behavior test where an ambiguous unsupported answer is
  queued as `ambiguous` without relying on the word "ambiguous" in prose.
- Add an audit behavior test proving unsupported reason metadata comes from the
  structured reason when present.
- Add an API behavior test proving new reason fields are additive and existing
  fields remain present.

### Implementation Notes

- Add typed unsupported/review reason data additively to the answer model.
- Preserve `unsupported`, `warnings`, `review`, and existing metadata fields.
- Map current unsupported branches to structured reason codes.
- Keep freeform unsupported SQL row behavior working, but translate it into the
  structured reason interface when building the answer.
- Review reasons should remain compatible with existing values:
  `unsupported`, `ambiguous`, and `low_confidence`.

### Verification

- Run audit, review queue, API, and eval tests touched by unsupported handling.
- Run deterministic evals before committing the phase.

### Done Criteria

- Review queue no longer sniffs prose to detect ambiguous answers.
- Audit unsupported reason uses structured data first.
- Existing clients can ignore the new fields.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check for remaining string-sniffing that controls review reason behavior.
- Check that public payload changes are additive only.
- Check unsupported branches for stable reason codes.
- Check eval baseline compatibility.

## Phase 3: Corpus Document And Lifecycle Module

### Goal

Make corpus document contracts, Chroma metadata, manifest entries, collection
lifecycle, and diagnostics local to one deeper module.

### Intended Module Depth

The corpus lifecycle module should turn source documents and generated player
profiles into validated records. Ingest, retrieval, and diagnostics should not
repeat frontmatter, manifest, collection name, or persist-dir conventions.

### Likely Files

- `src/baseball_rag/corpus/frontmatter.py`
- `src/baseball_rag/corpus/player_bios.py`
- `src/baseball_rag/corpus/ingest.py`
- `src/baseball_rag/corpus/diagnostics.py`
- `src/baseball_rag/retrieval/chroma_store.py`
- `tests/test_ingest_player_bios.py`
- `tests/test_corpus_diagnostics.py`

### TDD Starting Tests

- Add a corpus record behavior test proving a generated player profile produces
  one validated text payload, Chroma metadata, and manifest entry.
- Add a negative behavior test for missing required frontmatter in a generated
  player profile.
- Add a diagnostics behavior test proving missing or partial Chroma state is
  reported without raising.

### Implementation Notes

- Keep Markdown corpus source as the durable source of truth.
- Keep ChromaDB as generated local state.
- Centralize collection name and persist-dir resolution.
- Centralize corpus manifest read/write and document counts.
- Avoid rewriting corpus content unless required to satisfy the new validation
  contract.

### Verification

- Run corpus ingest/player bio/diagnostics tests.
- Run a static-only corpus build locally if the environment supports it.

### Done Criteria

- Ingest no longer hand-builds metadata and manifest entries in multiple places.
- Diagnostics and retrieval use the same lifecycle constants.
- Generated player profile source provenance remains intact.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that corpus conventions live in one module.
- Check that missing/partial Chroma states remain tolerant.
- Check that generated player profile provenance still includes source tables.
- Check that no generated Chroma state is committed.

## Phase 4: Retrieval Decision Module

### Goal

Move routed intent-to-retrieval behavior behind one retrieval decision module,
leaving Chroma as an adapter.

### Intended Module Depth

Callers should ask for grounded chunks for a routed case. They should not need
to know Chroma `where` filters, category strings, exact player ID lookup order,
static vocabulary fallbacks, thresholds, or `top_k` defaults.

### Likely Files

- `src/baseball_rag/service.py`
- `src/baseball_rag/retrieval/strategies.py`
- `src/baseball_rag/retrieval/chroma_store.py`
- `src/baseball_rag/retrieval/static_vocab.py`
- `evals/questions.py`
- `tests/test_retrieval_strategies.py`
- `tests/test_player_bio_query.py`

### TDD Starting Tests

- Add a behavior test proving a resolved `player_biography` query retrieves by
  player ID before semantic fallback.
- Add a behavior test proving a stat explanation query can retrieve an exact
  static stat definition without requiring service-level Chroma filters.
- Update eval strategy tests to assert retrieval outcome and strategy metadata,
  not low-level Chroma call choreography.

### Implementation Notes

- Keep benchmarkable retrieval strategies, but move decision policy out of
  request handling.
- Make Chroma calls an adapter detail.
- Preserve retrieval strategy names used by evals.
- Preserve `RetrievedChunk` fields used by provenance.
- Keep missing corpus and embedding mismatch failures recoverable.

### Verification

- Run retrieval strategy, Chroma store, player biography, and relevant eval tests.
- Run retrieval-only evals when the local Chroma index is available.

### Done Criteria

- Request handling does not pass raw Chroma filters.
- Player biography and explanation retrieval policy is local to retrieval.
- Existing strategy eval flags still work.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that category/filter constants are not spread into request handling.
- Check that strategy names and eval behavior remain compatible.
- Check that Chroma remains an adapter, not the public retrieval interface.
- Check that tests cover exact, semantic, and fallback behavior.

## Phase 5: stat_query Module

### Goal

Make deterministic `stat_query` handling own stat table choice, fielding
support, executed SQL/provenance, row formatting, and unsupported results.

### Intended Module Depth

The `stat_query` module should hide stat registry, time-period resolution,
player lookup, leaderboard execution, fielding support, parameterized SQL, and
source provenance behind a compact interface.

### Likely Files

- `src/baseball_rag/service.py`
- `src/baseball_rag/db/queries.py`
- `src/baseball_rag/db/stat_registry.py`
- `src/baseball_rag/routing/query_router.py`
- `tests/test_queries.py`
- `tests/test_cli_stat_query_integration.py`
- `tests/test_api.py`

### TDD Starting Tests

- Add an end-to-end behavior test for a fielding `PO` query through the normal
  answer path.
- Add a provenance behavior test proving stat source SQL comes from the executed
  parameterized query, not a shadow template.
- Add a behavior test for AVG or OPS preserving sample guards in provenance.

### Implementation Notes

- Do not add a broad database seam just to make storage swappable.
- Keep DuckDB as the structured data adapter.
- Return provenance-ready query results from deterministic stat execution.
- Use stat registry table ownership when choosing batting, pitching, or fielding
  execution.
- Preserve existing answer wording unless tests intentionally update it.

### Verification

- Run query, CLI stat integration, API, audit, and deterministic eval tests.
- Include the confirmed fielding path in targeted verification.

### Done Criteria

- `PO` and position-aware fielding queries work through the normal answer path.
- Stat SQL provenance cannot drift from executed SQL.
- Existing batting and pitching stat queries still pass.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that stat table choice is not hard-coded in request handling.
- Check that executed SQL and provenance use the same source.
- Check fielding, batting, pitching, player, range, and career paths.
- Check deterministic eval compatibility.

## Phase 6: freeform_query Planning Seam

### Goal

Align deterministic templates and LLM-backed freeform extraction behind one
planning seam before SQL assembly.

### Intended Module Depth

The `freeform_query` module should hide whether a question matched a
deterministic template or an LLM-backed typed extraction. SQL assembly, safety
validation, source detail, unsupported reasons, and historical team identity
should stay local.

### Likely Files

- `src/baseball_rag/db/freeform_runtime.py`
- `src/baseball_rag/db/freeform_templates.py`
- `src/baseball_rag/db/freeform_intent.py`
- `src/baseball_rag/db/freeform_assembler.py`
- `src/baseball_rag/db/team_history.py`
- `tests/test_freeform.py`
- `tests/test_eval_questions.py`

### TDD Starting Tests

- Add a planning behavior test proving a deterministic template and an
  LLM-backed intent produce the same kind of planned query object before SQL
  execution.
- Add a historical team behavior test proving a year-specific franchise mention
  resolves before SQL assembly instead of relying on English hints.
- Add an unsupported freeform behavior test proving the structured reason from
  Phase 2 is preserved.

### Implementation Notes

- Keep deterministic templates bypassing live LLM calls.
- Keep SQL parameterized.
- Keep validation and row-limit guardrails.
- Preserve compatibility facade exports until tests and callers no longer need
  them.
- Resolve historical team identity into typed data before SQL assembly.

### Verification

- Run freeform tests and deterministic evals.
- Run SQL safety and provenance-related tests.

### Done Criteria

- Template and LLM paths converge on one planning interface.
- Historical franchise handling is typed before assembly.
- Unsupported freeform results use structured reasons.
- Code-review subagent has no blocking findings.
- Phase is committed.

### Code-Review Subagent Checklist

- Check that templates do not return raw SQL through a separate path.
- Check that LLM output is still constrained before SQL assembly.
- Check historical team identity behavior for old franchise names.
- Check that private compatibility exports are not expanded unnecessarily.

## Verification Matrix

Run targeted tests during each phase, then run the full local gate before each
phase commit when feasible:

```bash
uv run ruff check src/ tests/
uv run mypy src/
uv run pytest tests/ -v
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
```

Additional optional checks:

```bash
uv run python -m baseball_rag.corpus --static-only
uv run python -m baseball_rag.corpus diagnostics --persist-dir data
uv run python -m evals.questions --all-strategies --retrieval-only
```

For this plan document itself, verify:

- `docs/architecture-deepening-plan.md` exists.
- All six opportunities are covered.
- Subagent usage and code-review subagent expectations are explicit.
- TDD, commit, unstaged-change, and CI expectations are explicit.
- Public compatibility defaults are additive only.

## Commit And CI Expectations

Each phase should end with:

1. Targeted tests for the changed behavior.
2. Full local verification, or a written explanation for any command not run.
3. A code-review subagent report with findings addressed or explicitly
   deferred.
4. `git status --short` reviewed.
5. A commit containing only the phase work.
6. A summary of any remaining unstaged changes.

If changes are pushed to GitHub:

- Monitor GitHub Actions for the branch.
- Do not report pushed work complete until CI is green.
- If CI fails, inspect logs, fix with TDD, rerun relevant local checks, commit,
  push, and wait again.
