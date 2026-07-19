# Ground Ball Context

This is the canonical current architecture and domain context. Historical implementation ledgers live under `docs/archive/architecture/`; they are evidence, not current interfaces.

## Product contract

- Ground Ball is a local-first historical MLB query engine.
- Every loaded primary Lahman field and row is discoverable and reachable through filtering, stable pagination, or export. The synthesized TeamReference source has the same guarantee.
- The Published Query Catalog is the only structured-query capability authority.
- A Query Recipe is the visible, editable request. It may be incomplete or ambiguous.
- Query Plan v1 is the closed, deterministic, serializable meaning of a validated recipe. It contains no user SQL and no executable code.
- The compiler owns identifiers and emits parameterized DuckDB SQL. User values are bound data.
- QueryEvidence binds every factual outcome to the canonical plan, catalog revision, data release, SQL, bound values, immutable result fingerprint, and source fingerprints.
- A factual adapter result is available only when the checked-in Coverage Report passes and matches the runtime exactly.
- Retrosheet event queries are separately governed and do not extend the Lahman query catalog implicitly.
- Biography generation and open explanation are auxiliary. Lahman/DuckDB remains primary for extractable biography stat claims; Retrosheet may contribute optional consensus evidence.
- There is no backwards-compatibility contract for deleted request, routing, stat-registry, grounded-template, review-queue, eval-manifest, or Go-verifier surfaces.

## Current delivery

The active delivery effort is the zero-Mac deterministic public release. Its execution source is `docs/public-release-implementation-ledger.md`; the completed Wayfinder map is supporting decision evidence, not an active ticket frontier.

- Continuation branch: `implementation/public-deterministic-groundball-release`, with current `origin/main` at `0afd947` integrated after preserving handoff commit `5ada351`.
- Completed foundation: the immutable Release Bundle and offline container proof merged in PR #23 at `a4084f1`.
- Completed on this branch: Wave 2 Public Admission Policy core, including shared-store and stable-key configuration seams, fail-closed readiness, hard-stop public execution, and common protection for both deterministic POST routes.
- Current opportunity: implement the Wave 3 Vercel Blob coordination Adapter, then the public result envelope, deterministic parity, candidate proof, and release preparation.
- External deployment, Blob or secret creation, production promotion, website cutover, paid services, Cloudflare activation, and Mac or tunnel operations remain outside current authorization until Stewart approves the exact action.

## Current modules

- `src/baseball_rag/query/contracts.py`: recipe, plan, outcomes, and evidence types.
- `src/baseball_rag/query/registry.py`: catalog-backed discovery and semantic bindings.
- `src/baseball_rag/query/recipe_adapter.py`: reviewed natural-language and named-recipe interpretation.
- `src/baseball_rag/query/service.py`: plan and execute entry points.
- `src/baseball_rag/query/compiler.py`: constrained SQL compiler.
- `src/baseball_rag/query/runtime.py`: packaged DuckDB data runtime and compatibility enforcement.
- `src/baseball_rag/query/coverage.py`: proof identity, validation, and verification binding.
- `src/baseball_rag/query/adapters.py`: shared rendering-neutral HTTP, CLI, and browser payloads.
- `src/baseball_rag/retrosheet_query.py`: separate deterministic Retrosheet adapter.
- `src/baseball_rag/api/server.py`: FastAPI routes, public admission boundary, and built Svelte application.
- `src/baseball_rag/public_admission.py`: pure CAS admission state, leases, rates, monthly budget, Visitor digest, and readiness checks.
- `src/baseball_rag/public_execution.py`: isolated child-process execution with a ten-second hard-stop outcome.
- `src/baseball_rag/release_bundle.py`: immutable Release Bundle identity, assembly, and verification.
- `src/baseball_rag/release_runtime.py`: offline release startup and readiness checks.

## Architecture ledger registry

### Current opportunities

- 2026-07-19: Public Deterministic Ground Ball release. Continue from the completed server-owned admission seam with the shared coordination Adapter, bounded public results and exports, named parity corpus, candidate identity, all-or-nothing gates, protected proof, and separately approved cutover. Preserve the Query contracts, exact Coverage Report, Release Bundle, dark Svelte/FastAPI shell, `$0` Vercel Hobby boundary, and zero-Mac rule. Detailed work and verification live in `docs/public-release-implementation-ledger.md`.

### Completed work

- 2026-07-18, merge `f77b1df`: Queryable Ground Ball clean cutover. Public contract: Published Query Catalog to Query Recipe to Query Plan to Query Run is the only structured-query path; deleted compatibility surfaces stay deleted.
- 2026-07-19, merge `a4084f1`: Public Release Bundle foundation. Public contract: one immutable offline bundle contains the approved Lahman, catalog, proof, compact Retrosheet, provenance, and license payload and exposes only bundle-backed deterministic capabilities.

### Frozen seams

- Preserve the Published Query Catalog, Query Recipe, Query Plan, Query Run, QueryEvidence, and Coverage Report contracts.
- Preserve the provider-neutral Release Bundle and provider-specific Deployment Attestation split.
- Preserve one Svelte/FastAPI application for local and hosted use; public mode disables local-only capabilities at the server.
- Do not add a Mac, tunnel, LLM, paid plan, alternate host, queue, hidden retry, legacy Adapter, or second query Interface as a fallback.

### Update rule

As a release wave lands, record its commit and evidence in the implementation ledger. Move the opportunity here to completed only when no repository implementation, candidate proof, or approved release action remains.

## Release gates

The generated Coverage Report is the deterministic query proof. It contains six fixed gates and currently covers 5,253 obligations with zero uncovered. Its identity includes the report schema, complete catalog assets, semantic data manifest, query compiler contract sources, deterministic eval matrix, source row fingerprints, and data release.

The public release adds all-or-nothing bundle, admission, parity, performance, resource, security, live Browser, candidate-identity, attestation, and cutover gates. The canonical checklist is `docs/public-release-implementation-ledger.md`; the commands below are the baseline, not the complete release proof.

Required checks:

```bash
uv run python -m baseball_rag.query.generate_catalog_compatibility --check
uv run python -m baseball_rag.query.generate_raw_inventory --check
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python -m baseball_rag.query.eval_matrix
uv run pytest tests/ -m 'not llm' -q
npm --prefix web test
npm --prefix web run build
```

## Working rules

- Do not restore a deleted compatibility facade without an explicit product decision.
- Regenerate the Coverage Report after any catalog, query implementation, or eval-matrix change.
- Treat the current `AGENTS.md` as the instruction source; do not resurrect removed workflow mandates from historical branches or files.
- Preserve unrelated worktree changes and use the active release ledger as the continuation source.
