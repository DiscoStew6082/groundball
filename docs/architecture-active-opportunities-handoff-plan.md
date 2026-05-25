# Active Architecture Opportunities Handoff Plan

Status: Completed implementation. This document turns the 2026-05-25 current
architecture opportunities in `CONTEXT.md` into the implementation ledger for
`/Volumes/Envoy/projects/baseball-rag`.

`CONTEXT.md` remains the canonical front door. Use this ledger for completion
evidence only when details are needed.

## Scope

This completed ledger covers three Modules, implemented in this order:

1. Routing Decision Evidence Module.
2. Grounded Database Template Catalog Module.
3. Context-Aware Stat Mention Vocabulary Module.

Preserve the completed Routing Decision Module, LLM Router Adapter Module,
Grounded Database Planning Module, DuckDB Result Answer Assembly Module,
Biography Stat Claim Vocabulary Module, Verified Evidence Read Model Module,
and Architecture Ledger Registry unless a fresh public-behavior test proves a
new delta.

## Global Working Rules

- Use the TDD skill for every code-changing slice: one public-behavior test,
  minimal implementation, refactor while green, then repeat.
- Tests should cross public Interfaces. Private-helper tests are acceptable only
  when the helper is a deliberate compatibility Adapter or new inspectable
  Interface.
- Use subagents wherever possible. Run a code-review subagent after every worker task
  and after final integration.
- DuckDB/Lahman remains the primary factual/stat authority. LLM output may
  classify or narrate, but structured facts must remain verified against local
  evidence.
- Preserve `route(question)` caller behavior, deterministic route precedence,
  malformed LLM fallback, public CLI/FastAPI/Gradio payload shapes, source JSON,
  SQL text, SQL params, audit template hashes, review metadata, and eval output
  unless a public-behavior test proves an intentional change.
- For UI-affecting changes, start the local UI with `uv run baseball-rag-ui`,
  open `http://127.0.0.1:7861/` in the Codex in-app Browser, run
  `who had the most RBIs in 1962`, confirm rows, source JSON, SQL, and enabled
  Ask button state, and keep the dev server running.
- A task is not complete until changes are committed and any unstaged changes
  are explained. If a branch is pushed to GitHub, wait for CI and confirm it is
  green.

## Work Order

| Wave | Worker | Scope | Notes |
| --- | --- | --- | --- |
| 1 | Worker A | Routing Decision Evidence Module | Do first. Evidence makes route drift visible before template and vocabulary work. |
| 2 | Worker B | Grounded Database Template Catalog Module | Use routing evidence from Worker A to prove route ownership stays stable. |
| 3 | Worker C | Context-Aware Stat Mention Vocabulary Module | Use route/template evidence to catch alias drift, especially strikeouts. |
| 4 | Integration lead | Docs, eval, Browser smoke, final review, commit | Reconcile ledgers and verify no completed Module was reopened by accident. |

Suggested branch names:

- `disco/routing-decision-evidence`
- `disco/grounded-template-catalog`
- `disco/stat-mention-vocabulary`
- `disco/active-architecture-opportunities`

## Worker A: Routing Decision Evidence Module

Status: Implemented and reviewed locally.

### Decision

Use both a new inspectable helper and trace visibility, but do them in that
order.

The first public behavior should live behind `RouteDecisionChain`, not inside
each router heuristic. Add named decision steps and a helper such as
`RouteDecisionChain.decide_with_evidence()`, returning a small read model with:

- `routed_case`: the same route facts returned by `route(question)`.
- `winner`: the Adapter label that matched.
- `steps`: ordered decision attempts with Adapter label, outcome, reason, and
  routed intent when present.
- `fallback_reason`: populated when malformed LLM fallback or model I/O fallback
  chooses the heuristic route.

Keep `RouteDecisionChain.decide()` as a thin delegate that returns only the
route facts. If callers need router-level evidence after that, add
`route_with_evidence(question)` while keeping `route(question)` unchanged. After
the helper is green, attach a compact winner summary to trace metadata through
the existing query-router trace stage output. Do not make the trace carry the
only copy of the evidence; tests need an inspectable helper that does not
require a full request lifecycle.

End state: decision evidence is returned from the new inspectable helper and
attached to trace metadata in compact form.

### Smallest Useful First Test

Add one focused test for `RouteDecisionChain` in `tests/test_router.py` or a
small new routing-decisions test file.

Expected behavior:

- Step 1 has a name and returns `None`.
- Step 2 has a name and returns a `RoutedCase`.
- The fallback callable is not called.
- `decide()` still returns the unchanged `RoutedCase`.
- `decide_with_evidence()` records attempted and selected step names.

That first test proves the evidence path without model I/O, Lahman data, or
router heuristic setup. It also keeps the first change inside the existing
decision-chain Module before touching `route(question)`.

### Follow-Up TDD Slices

1. RED: deterministic grounded database evidence.
   Use `who won the Triple Crown and which years`; prove `route(question)`
   still returns `GroundedDatabaseQuestionCase`, router evidence shows earlier
   Adapters declined, and the LLM router is not called.
2. RED: claim verification precedence.
   Use `Can DuckDB verify this claim? Babe Ruth hit 60 HR in 1927 and led everyone.`
   and prove claim verification still wins before stat and grounded routes.
3. RED: simple stat query precedence.
   Use `who had the most RBIs in 1962` and prove deterministic stat routing
   still wins with stat `RBI` and single-year `1962`.
4. RED: player biography deterministic route.
   Use `who was Babe Ruth` and prove the explicit biography Adapter wins before
   LLM routing.
5. RED: malformed LLM fallback.
   Use an invalid LLM JSON payload and prove fallback evidence records the
   model failure while `route(question)` still returns the heuristic
   `general_explanation`.
6. RED: valid LLM route.
   Use a valid mocked LLM payload and prove the LLM Adapter can still win when
   deterministic Adapters decline.

### Routes That Must Be Proven Unchanged

- Claim verification questions stay `player_biography`.
- Explicit player biography questions stay `player_biography`.
- Player biography follow-ups stay `player_biography`.
- Simple leaderboard stat questions stay `stat_query`.
- Plain career home run leaderboards stay `stat_query` when grounded database
  ownership should not steal them.
- Deterministic template questions stay `grounded_database_question`.
- Ambiguous deterministic templates such as `who is in the 500 club` still
  route to `grounded_database_question` so unsupported policy can fail closed.
- Local stat-definition questions such as `what is OPS` stay
  `general_explanation`.
- Valid LLM routing payloads still produce typed route facts.
- Empty, malformed, or timeout LLM routing still uses the heuristic fallback.

### Owned Files

- `src/baseball_rag/routing/decisions.py`
- `src/baseball_rag/routing/query_router.py`
- `src/baseball_rag/routing/__init__.py`
- `tests/test_router.py`
- `tests/test_pipeline_tracing.py` if trace-stage visibility changes.

### Verification

```bash
uv run pytest tests/test_router.py -q
uv run pytest tests/test_pipeline_tracing.py -q
uv run pytest tests/test_project_cleanup.py -q
```

## Worker B: Grounded Database Template Catalog Module

Status: Implemented and reviewed locally.

### Decision

Make templates small objects, not a larger pile of richer functions. The current
`MatchedTemplate` read model already points in that direction with assembled
SQL, `source_detail`, `route_owner`, and optional `query_spec`. Deepen that into
a catalog of frozen template records with local match facts and SQL assembly.

Avoid inheritance. A light record plus callables is enough:

- `template_id`
- `description`
- `route_owner`
- `match(question_facts) -> TemplateMatch | None`
- `assemble(match) -> AssembledSQL`
- `source_detail(match) -> str`
- `query_spec(match) -> QuerySpec | None`
- `unsupported_reason(match) -> str | None`

Keep `match_template(question)`, `can_plan_deterministically(question)`, and
`should_route_deterministic_grounded_database(question, competing_stat=...)` as
compatibility Interfaces while the catalog lands.

### Tracer Bullet

Use the 30-30 club template as the tracer bullet.

It is deterministic, parameterized, and has no year/team identity enrichment or
unsupported-path semantics. That makes it the safest first slice for the
catalog record shape. The first RED should keep the expected SQL params,
source detail, route ownership, and generated rows unchanged through
`match_template(...)` or `plan_query(...)`.

Use the team-season roster template as the second or third slice once the
catalog shape exists; it is the better proof that templates can own match
facts, year extraction, team identity, `QuerySpec`, provenance detail, SQL
params, and missing-year unsupported policy.

### Mandatory Template Fields

Every catalog template should make these facts local and inspectable:

- Stable `template_id`.
- Human-facing source detail or source-detail builder.
- Route ownership policy.
- Match facts used to explain why the template matched.
- SQL assembly callable returning the same `AssembledSQL` text and params as
  today.
- Unsupported policy, including reason text and reason code.
- Optional `QuerySpec` builder, made explicit even when it returns `None`.

### Follow-Up TDD Slices

1. RED: 30-30 club tracer bullet preserves source detail, SQL params, generated
   rows, and route ownership.
2. RED: roster template preserves `QuerySpec`, source detail, SQL params, and
   route ownership.
3. RED: roster missing-year question still returns unsupported SQL with the same
   unsupported reason.
4. RED: `who is in the 500 club` still routes to deterministic grounded
   database and still fails closed as ambiguous.
5. RED: plain `career home run leaders` is still not stolen from `stat_query`
   when a competing `HR` stat route exists.
6. RED: a simple SQL-only template proves catalog entries do not require
   `QuerySpec`.

### Preserve

- Grounded Database Planning Module behavior through `plan_query(...)` and
  `query(...)`.
- SQL text and params unless an intentional audit-hash update is explicitly
  approved.
- Source labels, source detail, rows, unsupported answers, and review payloads.
- Template hashes in metadata for unchanged SQL.
- User-facing grounded answers and eval expectations.

### Owned Files

- `src/baseball_rag/db/grounded_database_templates.py`
- `src/baseball_rag/db/grounded_database_runtime.py` only if catalog metadata
  must flow through planning.
- `src/baseball_rag/routing/grounded_database_ownership.py` only if route
  ownership reads new evidence.
- `tests/test_grounded_database.py`
- `tests/test_router.py`
- `tests/test_audit.py` if SQL template hash behavior is touched.

### Verification

```bash
uv run pytest tests/test_grounded_database.py -q
uv run pytest tests/test_router.py -q
uv run pytest tests/test_audit.py -q
uv run pytest tests/test_project_cleanup.py -q
```

## Worker C: Context-Aware Stat Mention Vocabulary Module

Status: Implemented and reviewed locally.

### Decision

Do not create one flat alias table. Create a vocabulary Module that exposes
context-specific views while sharing canonical definitions and unambiguous
aliases.

The first public Interface should be small, for example:

- `stat_mentions.for_routing()`
- `stat_mentions.for_biography_claims()`
- `stat_mentions.for_narration_verification()`
- `stat_mentions.for_stat_definition_lookup()`

Each view should expose aliases, canonical stat, allowed tables, and ambiguity
policy. The existing SQL registry remains the factual authority for supported
stats and formulas; the new Module owns mention grammar and context policy.

### Context Views

The distinct vocabulary views are routing, biography claims, narration
verification, and stat-definition lookup.

Required views: routing, biography claims, narration verification, and stat-definition lookup.

- Routing needs leaderboard terms, player-stat phrases, prompt aliases, and
  conservative ownership behavior.
- Biography claims need supported claim stats, regex-friendly supplied-claim
  aliases, Retrosheet column availability, and context hints.
- Narration verification needs broad stat-unit aliases so LLM prose can be
  checked against verified source rows.
- Stat-definition lookup needs only local document IDs; it should not import
  broad narration-only terms that would imply docs exist for unsupported stats.

### Shared And Context-Specific Aliases

Safe to share:

- `HR`, `home run`, `home runs`
- `RBI`, `run batted in`, `runs batted in`
- `AVG`, `batting average`
- `OPS`, `on-base plus slugging`
- `ERA`, `WHIP`
- `SB`, `stolen base`, `stolen bases`
- `PO`, `putout`, `putouts`

Context-specific or guarded:

- `hit` and `hits`: useful for biography claims and narration, but can be a
  verb in routing.
- `win` and `wins`: a pitching stat in claim/SQL contexts, but a generic event
  word elsewhere.
- One-letter aliases such as `H`, `W`, `K`, `R`, `G`, and `L`.
- `walk` and `walks`, which narration may need but routing/stat-definition
  lookup should not overclaim.
- `strikeout`, `strikeouts`, `SO`, `K`, and `Ks`, because table meaning depends
  on context.

### Strikeouts Policy

Represent strikeouts as a structured mention with canonical stat `SO` plus a
table hint:

- `table_hint="pitching"` when text says `as a pitcher`, `on the mound`,
  `pitched`, `batters`, or equivalent pitching context.
- `table_hint="batting"` when text says `as a batter`, `as a hitter`, `at the
  plate`, `batting strikeouts`, or equivalent batting context.
- `table_hint=None` when the text only says `strikeouts`, `SO`, `K`, or `Ks`.

Do not silently flatten ambiguous strikeouts to pitching. Preserve the current
biography behavior where context can return a pitching definition first while
retaining the batting fallback when no explicit table argument was supplied.

### Smallest Useful First Test

Add a focused test in `tests/test_stat_registry.py` that asks the
biography-claim view for `SO` mentions in:

- `struck out 200 batters as a pitcher`
- `89 batting strikeouts`
- `89 strikeouts`

The expected output should preserve the existing `infer_stat_table(...)`
behavior: pitching, batting, and ambiguous `None`, respectively. Then move only
the alias/context logic needed for that view.

### Follow-Up TDD Slices

1. RED: biography claim aliases and regex output stay stable.
2. RED: routing stat detection still finds `RBI`, `HR`, `AVG`, `ERA`, `WHIP`,
   `SO`, `SB`, and `PO` where today it does.
3. RED: narration verification still recognizes broad unit aliases such as
   walks, losses, games, starts, doubles, triples, and strikeouts.
4. RED: stat-definition lookup still returns only local document IDs and does
   not claim a document for unsupported narration-only aliases.
5. RED: `what is OPS` and `who had the most RBIs in 1962` keep their routes.

### Preserve

- DuckDB/Lahman as factual/stat authority.
- Biography claim verification behavior, including Retrosheet pitching
  strikeout support.
- Narration safety over verified evidence.
- Route behavior and deterministic route precedence.
- Static stat-definition document lookup behavior.

### Owned Files

- New vocabulary Module under `src/baseball_rag/`, likely
  `src/baseball_rag/stat_mentions.py`.
- `src/baseball_rag/db/stat_registry.py`
- `src/baseball_rag/db/biography_stat_vocabulary.py`
- `src/baseball_rag/biography_contract.py`
- `src/baseball_rag/player_biography.py`
- `src/baseball_rag/llm_narration_guard.py`
- `src/baseball_rag/corpus/static_vocab.py`
- `tests/test_stat_registry.py`
- `tests/test_static_vocab.py`
- `tests/test_router.py`
- `tests/test_service.py`
- `tests/test_player_bio_query.py`

### Verification

```bash
uv run pytest tests/test_stat_registry.py -q
uv run pytest tests/test_static_vocab.py -q
uv run pytest tests/test_router.py -q
uv run pytest tests/test_service.py -q
uv run pytest tests/test_player_bio_query.py -q
uv run pytest tests/test_project_cleanup.py -q
```

## Integration Definition Of Done

Final integration must run:

```bash
uv run ruff check src/ tests/ evals/
uv run mypy src/
uv run pytest -q
uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
uv run baseball-rag-ui
```

For the UI command, use the Codex in-app Browser at
`http://127.0.0.1:7861/`, run `who had the most RBIs in 1962`, confirm rows,
source JSON, SQL, and enabled Ask button state, make the Browser visible, and
leave the dev server running.

Before commit:

- Update this ledger with implementation evidence.
- Update `CONTEXT.md` completed/current opportunity entries.
- Run a code-review subagent and address actionable findings.
- Commit the completed slice.
- Explain any unstaged changes.

## Implementation Ledger

Implemented in the documented order with TDD slices and review passes:

- Worker A added inspectable routing evidence behind `RouteDecisionChain` and
  exported `route_with_evidence(...)` while keeping `route(question)` as the
  stable public route Interface. Query-router traces now include a compact
  decision winner summary. Review found and fixed a valid-LLM evidence bug so
  `fallback_reason` is reserved for degraded heuristic use.
- Worker B converted deterministic grounded database templates into small
  catalog records with stable template ids, match facts, route ownership
  policy, source detail, SQL assembly, and optional `QuerySpec` builders. SQL
  text, params, source details, unsupported policy, and route ownership behavior
  were preserved for existing templates.
- Worker C added `stat_mentions` context-specific vocabulary views for routing,
  biography claims, narration verification, and static stat-definition lookup.
  Review found and fixed static lookup overclaiming from substring matching,
  while preserving supported plural abbreviations such as HRs and RBIs.

Focused verification during implementation:

- `uv run pytest tests/test_router.py tests/test_router_player_bio.py tests/test_routing_decisions.py -q`
- `uv run pytest tests/test_pipeline_tracing.py tests/test_pipeline_tracing_integration.py -q`
- `uv run pytest tests/test_grounded_database.py -q`
- `uv run pytest tests/test_router.py tests/test_routing_decisions.py tests/test_audit.py -q`
- `uv run pytest tests/test_stat_registry.py tests/test_static_vocab.py tests/test_router.py tests/test_service.py tests/test_player_bio_query.py tests/test_biography_contract.py tests/test_player_stat_claims_consensus.py -q`
- `uv run pytest tests/test_grounded_database.py tests/test_router.py tests/test_routing_decisions.py tests/test_stat_registry.py tests/test_static_vocab.py tests/test_service.py tests/test_player_bio_query.py tests/test_biography_contract.py tests/test_player_stat_claims_consensus.py tests/test_project_cleanup.py -q`
- `uv run ruff check` on touched source and test files passed.
- `uv run mypy src/` passed.
- `git diff --check` passed.

## Historical Coordinator Handoff Prompt

This was the coordinator prompt used for the completed 2026-05-25 architecture
opportunity implementation recorded in
`docs/architecture-active-opportunities-handoff-plan.md` for
`/Volumes/Envoy/projects/baseball-rag`.

Start by reading:

- `AGENTS.md`
- `CONTEXT.md`
- `docs/architecture.md`
- `docs/architecture-active-opportunities-handoff-plan.md`
- `src/baseball_rag/routing/query_router.py`
- `src/baseball_rag/routing/decisions.py`
- `src/baseball_rag/db/grounded_database_templates.py`
- `src/baseball_rag/db/stat_registry.py`
- `src/baseball_rag/db/biography_stat_vocabulary.py`

Use vertical TDD slices through public Interfaces. Start with Worker A
Routing Decision Evidence, then Worker B Grounded Database Template Catalog,
then Worker C Context-Aware Stat Mention Vocabulary. Preserve `route(question)`
caller behavior, deterministic route precedence, malformed LLM fallback,
DuckDB/Lahman factual authority, grounded answer payloads, SQL/source behavior,
and current user-facing answers. Use subagents wherever possible, run a
code-review subagent after each task, update the ledger as work lands, run
focused verification plus the final verification set when scope warrants, and
commit before calling the task complete.
