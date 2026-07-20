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

- Current Wave 7 repository-tooling branch: `implementation/public-deterministic-groundball-protected-proof`, based exactly on PR #30's Wave 6 merge `2a732f24d7bddbd1f3bd21ac4bbdcb66b60c259f`; post-merge ordinary CI and Release Proof passed.
- Completed foundation: the immutable Release Bundle and offline container proof merged in PR #23 at `a4084f1`.
- Completed Wave 2: the Public Admission Policy core merged in PR #26 at `427e189`, including shared-store and stable-key configuration seams, fail-closed readiness, hard-stop public execution, and common protection for both deterministic POST routes.
- Completed Wave 3: the shared coordination Adapter merged in PR #27 at `30a2bc5`, with a strict schema-v1 state codec and project-owned private Vercel Blob HTTP Adapter. Its proof remains fake/scripted transport evidence only; it does not prove live provider compatibility.
- Completed Wave 4: the public 25/50/100 result envelope, complete-or-refused exports, and separated Browser completed-run/attempt state merged in PR #28 at `91d1dfa6c3473481068fa8985a1f5b37f31ce3fc`.
- Completed Wave 5: deterministic parity closure merged in PR #29 at `17d972d`, including the exact Ohtani natural/structured/follow-up contracts and 26-case Lahman/Retrosheet parity matrix.
- Completed Wave 6: strict canonical candidate identity with an exact 1 GiB ceiling, source-then-bundle topology, actual-policy/runtime digests, fixed all-or-nothing gates, provider image binding, a local no-deployment template, and exact-head candidate-container CI merged in PR #30 at `2a732f2`.
- Corrected Wave 7 repository scope: request-scoped Vercel OIDC with an optional startup/local fallback, strict protected-provider environment modes, the pinned `@vercel/blob` 2.4.2 API-v12 query-parameter write contract, immutable warm/Browser manifests, guarded HTTP/proof-Blob probes, and exact Hobby memory-unavailable gate derivation. Credentials are absent from Blob config/evidence and resolved per provider operation. Supplied live evidence exposed four repository blockers in sequence: mixed-case store IDs must preserve their header value while deriving a lowercase canonical host; provider lifespan must yield before heavyweight readiness; deployed custom-container startup cannot require process-environment `VERCEL_OIDC_TOKEN` because the reliable credential is incoming request header `x-vercel-oidc-token`; and a direct mobile Browser can reach a different cold runtime than an operator-warmed invocation. Provider startup is TCP-invocable promptly because lifespan yields after starting one process-wide local Bundle/DuckDB initializer. While that exact cached local readiness is initializing, `/health` returns immediately with fixed `503` and every non-health request waits at most 30 seconds on the same completion signal before proceeding or returning the fixed sanitized `503`; request timeout or cancellation never starts or cancels the initializer. Query body, CORS, request OIDC, Blob admission, and the ten-second execution deadline remain downstream of local readiness. `/api/release-readiness` and Query Runs still require request-scoped Blob operations. Application readiness for an exact protected candidate requires successful root HTML, capabilities, and request-scoped release readiness from the real Browser/request path; TCP acceptance, initializing health, or a separately warmed invocation is insufficient. A rebuilt candidate still needs fresh live proof.
- Vercel exposes deployment-filterable `vercel.function_invocation.peak_memory_mb` only through Observability Plus, which Hobby cannot enable. The 2 GB provisioned limit is not peak use. For the actual no-cost Ground Ball run, `provider_peak_memory` remains blocked with `provider_metric_unavailable_on_hobby`, eligibility remains false, and no Deployment Attestation can be emitted. The reusable strict tooling still validates genuine provider-reported measurements and all-pass attestations for an otherwise eligible candidate.
- This Pi pass creates no provider or external resource. Hermes may separately collect authorized free evidence, derive the exact blocked report, and must stop before Wave 8. Production promotion, website/domain cutover, paid-plan activation, Cloudflare, and Mac/tunnel operations remain forbidden.

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
- `src/baseball_rag/public_admission.py`: provider-neutral opaque CAS snapshots, admission state, leases, rates, monthly budget, Visitor digest, trusted snapshot-time routing, and readiness checks.
- `src/baseball_rag/public_admission_state.py`: strict deterministic schema-v1 JSON codec and provider-state bounds.
- `src/baseball_rag/public_admission_blob.py`: private Vercel Blob raw-HTTP transport contract, namespace/configuration validation, ETag CAS Adapter, and local operation counters.
- `src/baseball_rag/public_execution.py`: isolated child-process execution with a ten-second hard-stop outcome.
- `src/baseball_rag/public_results.py`: public-only interactive page metadata, page validation, compact response encoding, and complete-export ceiling policy over the unchanged local Query Adapter.
- `src/baseball_rag/release_bundle.py`: immutable Release Bundle identity, assembly, and verification.
- `src/baseball_rag/release_runtime.py`: offline release startup and readiness checks.
- `src/baseball_rag/public_release_config.py`: actual Public Admission Policy read model, generated policy check, strict non-secret runtime configuration, and release-environment allowlist.
- `src/baseball_rag/release_candidate.py`: canonical candidate, gate-report, and Deployment Attestation assembly and validation.
- `src/baseball_rag/candidate_container_probe.py`: packaged Wave 5 HTTP corpus used only by network-disabled candidate proof.

## Architecture ledger registry

### Current opportunities

- 2026-07-19: Public Deterministic Ground Ball release. Continue from the completed server-owned admission seam with the shared coordination Adapter, bounded public results and exports, named parity corpus, candidate identity, all-or-nothing gates, protected proof, and separately approved cutover. Preserve the Query contracts, exact Coverage Report, Release Bundle, dark Svelte/FastAPI shell, `$0` Vercel Hobby boundary, and zero-Mac rule. Detailed work and verification live in `docs/public-release-implementation-ledger.md`.

### Completed work

- 2026-07-18, merge `f77b1df`: Queryable Ground Ball clean cutover. Public contract: Published Query Catalog to Query Recipe to Query Plan to Query Run is the only structured-query path; deleted compatibility surfaces stay deleted.
- 2026-07-19, merge `a4084f1`: Public Release Bundle foundation. Public contract: one immutable offline bundle contains the approved Lahman, catalog, proof, compact Retrosheet, provenance, and license payload and exposes only bundle-backed deterministic capabilities.
- 2026-07-19, merge `427e189`: Public Admission Policy core. Public contract: every public deterministic POST route shares one fail-closed CAS admission decision and ten-second hard-stop execution seam; process-local state is never deployment authority.
- 2026-07-19, merge `30a2bc5`: Shared coordination Adapter contract. One private schema-v1 object uses canonical provider HTTP `Date`, exact private uncached reads, current raw write protocol, and opaque ETags for bounded CAS; this is fake-transport proof only until a separately approved protected Blob exercise passes.
- 2026-07-19, merge `91d1dfa`: Public result and Browser contract. Public-only 25/50/100 paging and complete-or-refused exports preserve the unchanged local/exhaustive Query path; Browser attempt outcomes cannot replace a completed Query Run.
- 2026-07-19, merge `17d972d`: Deterministic parity closure. Catalog-owned hidden name-match projections survive composed fact plans; exact natural/structured Ohtani parity and recipe-only deterministic follow-up are covered across Adapter, API/child, Browser, eval, Retrosheet, Coverage Report, and immutable release-runtime seams. Repository and local DOM/API proof do not establish live provider compatibility, deployment, protected Browser behavior, or cutover.
- 2026-07-20, merge `2a732f2` (PR #30): candidate identity and gate tooling. Candidate IDs bind exact source/artifact topology, bundle, local image, runtime, actual admission policy, and evidence identities; every fixed release gate is pass/fail/blocked, and the local Deployment Attestation template explicitly records that no deployment exists. Provider gates remain blocked.
- 2026-07-20, corrected Wave 7 repository tooling: strict request OIDC, Blob API-v12 wire pin, protected/static environment separation, immutable manifests, guarded probes, Hobby-truth gate derivation, and reusable measured-provider attestation validation. No fixture is live proof; the actual Ground Ball provider peak-memory and Deployment Attestation gates remain explicitly blocked on Hobby.

### Frozen seams

- Preserve the Published Query Catalog, Query Recipe, Query Plan, Query Run, QueryEvidence, and Coverage Report contracts.
- Preserve the provider-neutral Release Bundle and provider-specific Deployment Attestation split.
- Preserve one Svelte/FastAPI application for local and hosted use; public mode disables local-only capabilities at the server.
- Do not add a Mac, tunnel, LLM, paid plan, alternate host, queue, hidden retry, legacy Adapter, or second query Interface as a fallback.

### Update rule

As a release wave lands, record its commit and evidence in the implementation ledger. Move the opportunity here to completed only when no repository implementation, candidate proof, or approved release action remains.

## Release gates

The generated Coverage Report is the deterministic query proof. It contains six fixed gates and currently covers 5,253 obligations with zero uncovered. Its identity includes the report schema, complete catalog assets, semantic data manifest, query compiler contract sources, deterministic eval matrix, source row fingerprints, and data release.

The public release adds all-or-nothing bundle, admission, parity, performance, resource, security, live Browser, candidate-identity, attestation, and cutover gates. The checked-in deterministic eval/parity matrix now contains 26 passing cases, including the exact natural and structured Ohtani paths, the two-turn follow-up, and all six public Retrosheet positive/negative boundaries. The canonical checklist is `docs/public-release-implementation-ledger.md`; the commands below are the baseline, not the complete release proof.

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
