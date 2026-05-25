# Baseball RAG Context

This file is the current architecture and domain context for Baseball RAG. Use it with `README.md`, `docs/architecture.md`, and the completed architecture ledgers under `docs/` when doing architecture review or worker handoff planning.

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

There is no `docs/adr/` directory in this repo yet. Treat these as the current decision record:

- `README.md` for the product contract and demo vocabulary.
- `docs/architecture.md` for the active architecture overview.
- `docs/architecture-followup-worker-handoff-plan.md`, `docs/architecture-next-deepening-plan.md`, and `docs/architecture-fresh-deepening-handoff-plan.md` as completed implementation ledgers.

Do not reopen completed Modules without fresh public-behavior evidence. Prior ledgers mark routing decision order, request lifecycle ordering, visible evidence presentation, eval reporting, Grounded Database Planning, DuckDB Result Answer Assembly, Biography Stat Claim Vocabulary, LLM Narration Guard, Player Identity Authority, Query Output Contract, and Verified Evidence Read Model as landed.

## Current Deepening Findings

### Routing Decision Evidence Module

Fresh friction: `route(question)` is a stable public Interface, but the current Implementation discards which routing Adapter won and why. `RouteDecisionChain` and deterministic grounded database ownership are Shallow because deleting them mostly moves a loop and thin import wrapper back into `query_router.py`.

Deepening direction: keep route precedence and `route(question)` stable, but make routing decisions preserve labeled evidence that tests and traces can inspect.

Expected benefits: Locality for route-precedence bugs and Leverage for router tests, Architecture Explorer traces, and future route-miss debugging.

### Grounded Database Template Catalog Module

Fresh friction: deterministic template matching, route ownership, unsupported/ambiguous policy, source detail, and SQL templates live together in the grounded database template file. Each new template increases the caller-facing knowledge needed to reason about the Module.

Deepening direction: keep the completed Grounded Database Planning Module stable, but deepen the template catalog so each template owns match facts, route ownership, provenance detail, and SQL assembly locally.

Expected benefits: Locality for template additions and Leverage from focused tests that target one template's behavior.

### Context-Aware Stat Mention Vocabulary Module

Fresh friction: stat aliases and mention grammar are repeated across stat routing, biography claim vocabulary, LLM narration verification, and static stat-definition lookup. A single flat alias table would be too blunt because each Seam needs different policy, but the current duplication invites drift.

Deepening direction: create a context-aware vocabulary Module that exposes tailored views for routing, biography claims, narration verification, and stat-definition document lookup.

Expected benefits: Locality for alias changes and Leverage across tests for routing, claim extraction, and narration safety.

### Architecture Ledger Registry

Fresh friction: the completed architecture ledgers are valuable, but the current status of landed Modules and fresh-delta rules is spread across several documents.

Deepening direction: add a small current registry that names completed Modules, active vocabulary sources, fresh-delta rules, verification commands, and Browser smoke expectations while leaving historical handoffs intact.

Expected benefits: Locality for future architecture review context and Leverage for worker handoffs.

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
