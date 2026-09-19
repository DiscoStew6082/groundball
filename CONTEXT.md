# Ground Ball Context

This is the canonical current architecture and domain context. Historical implementation notes are not current interfaces.

## Product contract

- Ground Ball combines a local-first historical MLB query engine with a bounded sourced baseball assistant in the same chat.
- Every loaded primary Lahman field and row is discoverable and reachable through filtering, stable pagination, or export. The synthesized TeamReference source has the same guarantee.
- The Published Query Catalog is the only structured-query capability authority.
- A Query Recipe is the visible, editable request. Query Plan v1 is its closed, deterministic, serializable meaning and contains no user SQL or executable code.
- The compiler owns identifiers and emits parameterized DuckDB SQL. User values are bound data.
- QueryEvidence binds factual outcomes to the plan, catalog revision, data release, SQL, bound values, immutable result fingerprint, and source fingerprints.
- Factual adapter results are available only when the checked-in Coverage Report passes and matches the runtime exactly.
- Retrosheet event queries are separately governed. Assistant statistics reuse verified immutable Query Runs; external records do not extend the Published Query Catalog.
- Assistant answers use `ground-ball-assistant-answer-v1`, with at most five sourced facts, source records, observation times, fingerprints, scope limits, and required attribution.
- Assistant scope includes team history through 2025, next-game context, historical World Series follow-ups, ten reviewed definitions, current regular-season MLB batting leaders (HR/RBI/SB), and probable pitchers for the next scheduled fixture. Current records require injected sources, freshness and retained evidence; probable pitchers remain tentative. Injuries, news and other unsupported conditions are rejected rather than dropped.
- Bounded compound plans use two or three tool steps and at most one statistical query, composing no more than five sourced facts. Any unavailable step prevents a partial answer. Browser follow-up context contains only validated references; facts are retrieved again.

## Public composition

`baseball_rag.public_app.create_app` is the public composition boundary. Local construction needs no bindings. Public construction accepts only injected `PublicAppBindings`: a deployment-shared CAS store, stable digest key, initializer, and hard-stop execution runner. Missing or unsafe bindings fail closed. The public repository contains no concrete hosting adapter or environment-driven hosting construction.

The direct-import `baseball_rag.api.server.app` remains available for local use and offline release proof. Its local-CI runtime configuration is network-disabled and cannot claim shared deployment authority.

Public source owns the interpretation prompt, response schema, validation, `run_question_input`, and factual answer construction. Optional model transport and bounded external source callbacks are injected by the outer runtime. `QuestionBindings` supplies optional local interpretation; public execution injects these dependencies within its existing hard-stop boundary. No transport or source callback owns product prompts, query semantics, or factual prose.

Ordinary statistics use catalog-derived typed intent slots translated into the existing Query Recipe. Complex filters, raw rows, windows, qualifications and exports retain the direct recipe path. Typed season scopes are checked against immutable release coverage.

Interpretation grammar derives field operators and literal types from the Published Query Catalog. Natural-language player filters share the people identity resolver across equality, alternatives and exclusions, preserving disambiguated IDs. Explicit-name and season checks can reject missing or contradictory scope; these are partial safeguards, not proof of complete language understanding. QueryEvidence verifies execution of the visible recipe, not that a model preserved every condition in the original question.

Interpretation guidance explicitly treats listed seasons as alternatives and one World Series meeting as one research request, including both teams. These instructions remain model-independent; injected transports own endpoint and model configuration.

## Release model

- `release/bundle/` is the immutable deterministic payload.
- `baseball_rag.release_bundle` assembles and verifies the bundle against an exact source commit.
- `baseball_rag.release_artifact` binds the source commit, artifact-only child commit, bundle, Public Admission Policy, Coverage Report, and public interface revision.
- Source changes are committed first. The next commit may change only `release/bundle/**`, and its direct parent must be the source commit.
- Public CI proves the same source-to-artifact topology without deployment or external runtime evidence.

## Completed work, 2026-09-18

- Shared sourced answers and visible data attribution landed in `74910a9`; natural-language identity resolution was consolidated in `49aab9b` and `733d1cb`.
- Typed statistics, bounded compound plans, current-source callback contracts and reference-only follow-ups landed in `e0b169c`. Later corrections preserve definition references and World Series scope and require explicit research identity fields (`e034e0d`, `3a953f5`, `3a6e548`).
- Dependency fixes landed in `aac74e3`, followed by release artifact `99a46c8`. Root and nested Python locks and the web lock passed complete dependency audits. These are dated results, not a guarantee about future advisories.
- The implementation is a bounded model-and-tool workflow. One interpretation can choose multiple supported operations; the model does not consume tool results to plan another autonomous iteration. Evidence proves the returned operation and sources, not universal language understanding.

The architecture and assistant guides describe the current implementation. Earlier experiments are evidence for decisions, not unimplemented work. Broader news, injuries, unrestricted live statistics and autonomous research remain outside the supported scope. See [the implementation ledger](docs/public-release-implementation-ledger.md).

## Current modules

- `src/baseball_rag/query/`: catalog-backed planning, compilation, execution, evidence, and coverage.
- `src/baseball_rag/query_intent.py`: catalog-derived statistics slots and deterministic recipe translation.
- `src/baseball_rag/question_interpretation.py`: public interpretation contract and same-endpoint dispatch to validated queries or bounded research.
- `src/baseball_rag/assistant.py`: sourced answer construction, verified Query Run reuse, and `ResearchSources` callback interfaces.
- `src/baseball_rag/source_attribution.py`: application-owned source credits, including the required Retrosheet notice.
- `src/baseball_rag/public_admission.py`: opaque CAS state, admission, leases, rates, and monthly budget.
- `src/baseball_rag/public_app.py`: injected public application bindings and fail-closed initialization.
- `src/baseball_rag/public_execution.py`: isolated child-process execution with a ten-second hard stop.
- `src/baseball_rag/public_results.py`: bounded public pages and complete-or-refused exports.
- `src/baseball_rag/public_release_config.py`: Public Admission Policy and strict local release configuration.
- `src/baseball_rag/release_bundle.py`: deterministic Release Bundle assembly and verification.
- `src/baseball_rag/release_runtime.py`: offline startup and readiness checks.
- `src/baseball_rag/release_artifact.py`: canonical public Release Artifact identity.

## Frozen seams

- Preserve the Query contracts and exact Coverage Report.
- Preserve one Svelte/FastAPI application for local and public composition.
- Preserve safe text rendering, adjacent source citations, visible attribution, and evidence-complete local JSON downloads for assistant answers.
- Preserve a ten-second execution deadline, lease accounting, fail-closed public mode, and immutable runtime caching.
- Do not add a second query interface, hidden retry, local machine fallback, or public hosting implementation.

## Baseline checks

```bash
uv run python -m baseball_rag.query.generate_catalog_compatibility --check
uv run python -m baseball_rag.query.generate_raw_inventory --check
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python -m baseball_rag.query.eval_matrix
uv run python scripts/check_provider_neutrality.py --root .
uv run python -m pytest tests/ -m 'not release_proof' -q
npm --prefix web test
npm --prefix web run build
npm --prefix web run package:check
```
