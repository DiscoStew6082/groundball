# Baseball RAG Context

This file is the canonical current architecture and domain context for Baseball RAG. Start here for architecture review or worker handoff planning; open `README.md`, `docs/architecture.md`, or the completed architecture ledgers under `docs/` only when you need supporting detail.

## Architecture Vocabulary

Use these words consistently:

- Module: anything with an Interface and Implementation.
- Interface: everything a caller must know to use the Module correctly, including invariants, ordering, error modes, configuration, and performance expectations.
- Implementation: the code inside a Module.
- Depth: Leverage at the Interface. Deep Modules hide substantial behavior behind a small Interface. Shallow Modules expose an Interface nearly as complex as their Implementation.
- Seam: where an Interface lives; behavior can change there without editing callers.
- Adapter: a concrete thing satisfying an Interface at a Seam.
- Leverage: what callers get from Depth.
- Locality: what maintainers get from Depth.

## Domain Contract

- Baseball RAG answers historical MLB questions with natural language in and grounded evidence out.
- DuckDB/Lahman remains the primary factual/stat authority for structured stat answers, grounded database answers, player identity, and primary biography stat-claim verification.
- Retrosheet remains optional secondary consensus evidence for biography stat claims, not a replacement factual authority for all query paths.
- LLMs may classify, narrate, and generate biography prose, but structured baseball facts must stay verified against DuckDB/Lahman and optional Retrosheet evidence where supported.
- Grounded database questions become typed specs or deterministic templates; Python assembles constrained SQL with bound parameters.
- Unsupported or ambiguous questions fail closed and can enter the human-review queue through the HTTP Adapter.
- Do not add a stored corpus, vector index, or Chroma replacement unless the product contract changes explicitly.

## Current Decision Sources

There is no `docs/adr/` directory in this repo yet. Treat this file as the current decision record and use these sources only for supporting detail:

- `README.md` for expanded product contract and demo vocabulary.
- `docs/architecture.md` for the fuller architecture overview.
- `docs/architecture-active-opportunities-handoff-plan.md` for the completed implementation ledger covering the 2026-05-25 active-opportunity set.
- `docs/architecture-followup-worker-handoff-plan.md`, `docs/architecture-next-deepening-plan.md`, and `docs/architecture-fresh-deepening-handoff-plan.md` for completed implementation evidence.

Do not reopen completed Modules without fresh public-behavior evidence. Prior ledgers mark routing decision order, request lifecycle ordering, visible evidence presentation, eval reporting, Grounded Database Planning, DuckDB Result Answer Assembly, Biography Stat Claim Vocabulary, LLM Narration Guard, Player Identity Authority, Query Output Contract, and Verified Evidence Read Model as landed.

## Architecture Ledger Registry

Audience: future Codex sessions.
Authority: canonical current truth for architecture-deepening context.
Purpose: lower startup context by listing all active opportunities, completed Modules, and frozen Seams in one small front door.

### Current Opportunities

- No active architecture-deepening opportunities are open from the 2026-05-25
  active-opportunities handoff. Add a new opportunity only when fresh
  public-behavior evidence or an explicit product decision shows a real delta.

### Completed Modules

Completed entries must not ask future agents to finish anything. If future work remains, the item belongs under Current Opportunities instead.

#### Claim Verification and Source Provenance

- 2026-05-23, commit `148ddd3`: Claim Verification Evidence Module and Source Provenance Module. Public contract: keep the consensus verifier stable, preserve Lahman plus optional Retrosheet evidence rows, SQL, params, warnings, compatibility payloads, and source authority catalog shaping. Verification is recorded in `docs/architecture-followup-worker-handoff-plan.md`.
- 2026-05-24, commits `fee989d` and `8f569f1`: Biography Contract Completeness Guard Module and Verified Evidence Read Model Module. Public contract: generated biography JSON must include supported stat claims, unsupported prose still passes, and narration checks consume verified evidence instead of rendered answer text. Verification is recorded in `docs/architecture-fresh-deepening-handoff-plan.md`.

#### Routing and Request Lifecycle

- 2026-05-25, commit `pending`: Routing Decision Evidence Module. Public contract: `route(question)` caller behavior, deterministic route precedence, valid LLM routes, malformed LLM heuristic handling, and query-router tracing stay stable while `route_with_evidence(...)` and `RouteDecisionChain.decide_with_evidence()` expose inspectable ordered Adapter evidence.
- 2026-05-23, commit `148ddd3`: Routing Decision Module and Request Lifecycle Ordering Module. Public contract: deterministic route precedence stays stable, compatibility exports remain available from `query_router.py`, and `execute_request(...)` remains the public request Adapter over `request_lifecycle.py`.
- 2026-05-24, commits `fee989d` and `8f569f1`: LLM Router Adapter Module. Public contract: `route(question)` stays stable while malformed LLM output and deterministic precedence stay local to the router Adapter.

#### Grounded Database and Stat Answers

- 2026-05-25, commit `pending`: Grounded Database Template Catalog Module. Public contract: deterministic template SQL text, params, source detail, route ownership, unsupported policy, and user-facing grounded answers stay stable while each template owns stable `template_id`, match facts, route ownership, SQL assembly, source detail, and optional `QuerySpec` locally.
- 2026-05-23, commit `d86086c`: LLM-Flavored Narration Guard Module, Grounded Database Planning Module, DuckDB Result Answer Assembly Module, and Biography Stat Claim Vocabulary Module. Public contract: DuckDB-backed stat and grounded database answers keep verified SQL/row/source behavior; LLM prose is fallback or narration only after structured facts are verified. Verification is recorded in `docs/architecture-next-deepening-plan.md`.
- 2026-05-24, commits `fee989d` and `8f569f1`: Player Identity Authority Module. Public contract: Lahman player resolution, display metadata, ambiguity policy, suffix handling, and optional Retrosheet ID mapping live behind one authority while compatibility facades remain.

#### Stat Vocabulary and Narration Safety

- 2026-05-25, commit `pending`: Context-Aware Stat Mention Vocabulary Module. Public contract: stat routing, biography claim extraction and verification, narration verification, and static stat-definition lookup keep existing behavior while `stat_mentions` exposes context-specific vocabulary views and ambiguous strikeouts remain represented as canonical `SO` plus contextual table hints.

#### UI and Output Presentation

- 2026-05-23, commit `148ddd3`: Visible Evidence Presentation Module. Public contract: `AnswerPresenter` owns useful verification rows and SQL selection for multi-source answers while preserving common DuckDB stat display.
- 2026-05-24, commits `fee989d` and `8f569f1`: Query Output Contract Module. Public contract: Gradio pending, completed, and stale callback payload order lives behind a named output Adapter and the Browser smoke remains the visible proof.

#### Eval and Operational Verification

- 2026-05-23, commit `148ddd3`: Eval Reporting Module. Public contract: CLI artifacts and API governance payloads share `build_eval_report_payload` for summary and case-list data without claiming identical top-level schemas.
- 2026-05-24, commits `fee989d` and `8f569f1`: Operational verification health checks. Public contract: `GET /health/verification` reports data manifest, DuckDB core tables, guardrail manifest readiness, and the verification command set.

#### Architecture Context

- 2026-05-25, commit `f9eeef2`: Baseball RAG Context. Public contract: this file is the root architecture context, vocabulary source, active-opportunity front door, and working-rules summary for future improvement rounds.
- 2026-05-25, commit `5417b46`: Architecture Ledger Registry. Public contract: Current Opportunities list all active opportunities by domain area and date; Completed Modules record completed work by domain area, date, and commit hash; Frozen Seams and the Update Rule keep future context ingestion small.

### Frozen Seams

- Preserve `route(question)` caller behavior and deterministic route precedence unless a fresh public-behavior test or explicit product decision requires a change.
- Preserve DuckDB/Lahman as the primary factual/stat authority.
- Preserve Retrosheet as optional secondary consensus evidence, not a replacement authority for all query paths.
- Preserve CLI, FastAPI, Gradio, source JSON, SQL, metadata, review, and eval payload shapes unless a public-behavior test proves intentional alignment.
- Preserve `execute_request(...)` as the public request Adapter over the shared request lifecycle.
- Do not add a stored corpus, vector index, or Chroma replacement unless the product contract changes explicitly.
- Preserve the Browser smoke at `http://127.0.0.1:7861/` with `who had the most RBIs in 1962` for UI-affecting changes.

### Update Rule

Move a landed opportunity from Current Opportunities to Completed Modules in the same domain area, sorted by date, and include the commit hash. Keep the entry to the smallest useful contract summary plus a pointer to the detailed ledger. Do not leave future-worker instructions in completed entries. Add a new active opportunity only when fresh public-behavior evidence or an explicit product decision shows a real delta.

## Filtered Findings

These candidates were reviewed but should not be reopened without a fresh public-behavior failure or explicit product decision:

- Biography Claim Consensus Presentation Module: dropped because biography claim verification presentation is already completed and current code has `BiographyStatClaimConsensusPresentation`.
- Eval Gate Runner Module: dropped because Eval Reporting is already completed and CLI/HTTP payloads share `build_eval_report_payload`.
- Verification Readiness Ledger Module: dropped unless the product decision is to make readiness commands/status a single source. `GET /health/verification` already covers operational verification readiness.

## Working Rules

- Use TDD for code-changing slices: one public-behavior test, minimal implementation, then refactor while green.
- Use subagents wherever possible, and run a code-review subagent after every task.
- Keep DuckDB/Lahman as the primary factual/stat authority.
- Preserve CLI, HTTP Adapter, Gradio, source JSON, SQL, metadata, review, and eval payload shapes unless a public-behavior test proves an intentional change.
- Run focused verification after each slice. For broader changes, run `uv run ruff check src/ tests/ evals/`, `uv run mypy src/`, `uv run pytest -q`, and the deterministic eval gate.
- For UI-affecting changes, start the local UI when needed with `uv run baseball-rag-ui`, use the Codex in-app Browser at `http://127.0.0.1:7861/`, smoke `who had the most RBIs in 1962`, and keep the dev server running.
- A code-changing task is complete only after review, commit, and an explanation of any unstaged changes.
