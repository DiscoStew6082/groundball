# Public Deterministic Ground Ball Implementation and Release Ledger

Status: Active.

This is the execution handoff for the completed Public Deterministic Ground Ball Wayfinder map. It governs repository implementation, candidate proof, and release preparation. It does not itself authorize an external deployment or public cutover.

## Canonical continuation

- Working directory: `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-release`
- Branch: `implementation/public-deterministic-groundball-candidate-gates`
- Integrated baseline: `origin/main` at PR #29 Wave 5 merge commit `17d972d2c4a2c7f601c5908e707e7714e6fd7c35`
- Completed planning source: `.scratch/public-deterministic-groundball/map.md` on `wayfinder/queryable-ground-ball` at `6675ad1`
- Current context: `CONTEXT.md`
- Current instructions: this worktree's `AGENTS.md`, aligned with the root worktree's removal of the former TDD, subagent, mandatory-review, auto-commit, CI-wait, and forced-browser directives

Do not work from the root checkout; it is behind `origin/main` and contains unrelated user changes.

## Scope and authorization

This ledger authorizes repository implementation and local validation of the deterministic public release. It preserves the approved application and query contracts while adding the public admission, output, evidence, and release seams needed for one release candidate.

The following actions still require Stewart's separate explicit approval at the point of action:

- creating or changing a Vercel Blob store, project secret, credential, or account setting;
- deploying a protected or production candidate;
- deleting or replacing retained deployments to isolate the Hobby scope;
- promoting a deployment, changing a production domain, or changing the website launcher;
- enabling a paid plan, add-on, on-demand usage, Cloudflare, or another host; and
- inspecting, stopping, reconfiguring, or deleting any Mac, LaunchAgent, tunnel, or Mac-side configuration.

Stewart must receive the final protected candidate link, open it, and explicitly report that it works before any website cutover is considered.

## Current implementation state

### Landed on `main`

- `944180a`: immutable Release Bundle runtime, offline startup, readiness, and container packaging.
- `7a6adbe`: the checked-in Release Bundle payload.
- `6106dd6`: offline release-container CI proof.
- `b3c20e6`: Release Manifest binding to the reviewed source commit.
- `a4084f1`: PR #23 merge containing the complete Release Bundle foundation.
- `0639c23`: Wave 2 Public Admission Policy core.
- `a56fbe0`: Wave 2 UTC monthly retry-boundary correction.
- `427e189`: PR #26 merge containing the complete Wave 2 public admission seam.
- `30a2bc5`: PR #27 merge containing the complete Wave 3 shared coordination Adapter contract.
- `91d1dfa`: PR #28 merge containing the complete Wave 4 public result and Browser contract.
- `17d972d`: PR #29 merge containing the complete Wave 5 deterministic parity closure; post-merge ordinary CI and Release Proof passed.

The landed foundation packages the four Lahman tables, catalog and registry assets, generated raw inventory, team references, exact Coverage Report, compact strikeout-side Retrosheet projection, provenance, licenses, and canonical Release Manifest. It boots without acquiring data and advertises only the three bundle-backed Retrosheet families.

This is foundation evidence, not final release evidence. It does not yet prove shared public admission, final parity, performance, live Browser behavior, real Blob coordination, a Deployment Attestation, or public cutover.

### Landed Public Admission Policy

Wave 2 ported and completed the useful behavior from the previous worktree's five uncommitted files and merged it in PR #26 at `427e189`. That source remains preserved and read-only at:

- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/src/baseball_rag/api/server.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/src/baseball_rag/public_admission.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/tests/test_query_api_v1.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/tests/test_public_admission.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/tests/test_release_runtime.py`

The completed port preserves the upstream `release_proof` marker on `tests/test_release_runtime.py` and supersedes the draft's process-local production defaults. `InMemoryCasStore` is explicitly proof-only; production configuration rejects it and requires a declared deployment-shared store plus an injected stable digest key. Wave 3 now supplies the local Vercel Blob Adapter contract, but no real Blob store, secret, budget state, deployment, or attestation exists.

Do not commit more source work on the old `implementation/public-deterministic-groundball` branch. Its release-container CI assumes an artifact-only tip and is hard-coded to that retired branch name. Leave the old dirty worktree intact until outside-Pi verification confirms this port.

## Frozen decisions and seams

- One dark, mobile-capable Svelte application is served by FastAPI in both local and hosted modes.
- The public runtime is deterministic Python and DuckDB only. Local LLM, Architecture Explorer, and developer capabilities stay server-disabled in public mode.
- The only structured query path is Published Query Catalog to Query Recipe to Query Plan to Query Run, bound to the exact Coverage Report.
- Do not restore Gradio, legacy request models, compatibility Adapters, special-case query lanes, a second hosted UI, or a hosted-only query contract.
- Vercel Hobby at `$0` is the selected personal, non-commercial host. Cloudflare is a fresh decision only after evidence proves a required Vercel gate impossible without weakening the product, spending money, or violating zero-Mac.
- The Release Bundle is immutable, offline, provider-neutral, and limited to the reviewed deterministic surface. No full Retrosheet archives, persistent DuckDB authority, cache authority, or build/runtime data downloads.
- Public use is anonymous and human-paced: no accounts, server-side history, bulk API contract, queue, hidden retry, silent truncation, paid fallback, Mac fallback, tunnel fallback, or LLM fallback.
- Website integration owns only its surrounding frame and launcher target. It must not proxy or reimplement query execution.

## Work waves

| Wave | Status | Deliverable | Completion evidence |
| --- | --- | --- | --- |
| 1. Release Bundle foundation | Complete | Immutable payload, manifest, offline runtime, exact Coverage Report, restricted Retrosheet surface, container proof | Commits `944180a`, `7a6adbe`, `6106dd6`, `b3c20e6`, merged as `a4084f1` |
| 2. Public Admission Policy core | Complete on `main` in PR #26 (`427e189`) | Pure CAS state model, shared-store/stable-key configuration seam, 500-character and 16,384-byte limits, Visitor/deployment concurrency, rolling rates, 15-second leases, nonrefundable UTC-month budget, common primary/Retrosheet admission, exact retries, fail-closed readiness, and isolated ten-second hard-stop execution | Focused policy/API/runtime proof passes; `InMemoryCasStore` rejected as deployment authority; no Blob or deployment claim |
| 3. Shared coordination Adapter | Complete on `main` in PR #27 (`30a2bc5`) | Exact private Vercel Blob `?cache=0` read plus current raw control-plane ETag CAS, canonical provider time, strict store identity, stable keyed Visitor digest configuration, strict schema/versioning, create-if-absent initialization, redirect refusal, readiness, namespace isolation, and local operation accounting | Injected fake/scripted transport contract proof only; real protected Blob compatibility/accounting remains blocked on external approval |
| 4. Public result and Browser contract | Complete on `main` in PR #28 (`91d1dfa`) | Preserve last completed run separately from attempt outcome; 25/50/100 paging; returned and total counts; complete-or-refused CSV/JSON; timeout and all refusal classes | Focused public Adapter/child/API tests, Browser DOM tests, full local fast suite, marked offline proof, static checks, generators, eval matrix, and web build; no live provider/deployment proof |
| 5. Deterministic parity closure | Complete on `main` in PR #29 (`17d972d`) | Exact Ohtani natural/structured parity, hidden composed name-match projections, recipe-only deterministic two-turn follow-up, and all bundled/unbundled Retrosheet boundaries | 26-case named eval/parity matrix; focused compiler/Adapter/API/child/Browser/Retrosheet proof; regenerated exact Coverage Report and Release Bundle; no live provider/deployment proof |
| 6. Candidate identity and gate tooling | Implemented on `implementation/public-deterministic-groundball-candidate-gates`; PR pending | Bind exact source/artifact topology, bundle, local image, actual admission policy, strict runtime config, evidence set, all-or-nothing gates, and a no-deployment attestation template; replace retired branch-only container CI | Canonical machine records and branch-independent exact-head candidate-container proof; protected/provider gates blocked and candidate ineligible |
| 7. Protected Vercel proof | Blocked on explicit external approval | Provision isolated proof coordination, deploy protected candidate, and run real Blob, restart, scale-to-zero, performance, security, and live Browser gates | All gates pass for one candidate; no promotion |
| 8. Production and website cutover | Blocked on gates and explicit approvals | Build and attest final production artifact, send Stewart its link, receive acceptance, then make one reversible launcher change and externally verify | Stewart acceptance, attestation, post-switch proof, rollback proof |

## Wave 2 completion details

The Public Admission Policy now sits immediately before deterministic execution and jointly decides every Wave 2 limit. The completed repository behavior is:

- natural-language question at most 500 characters;
- complete request body at most 16,384 bytes before parsing;
- one running Query Run per Visitor and four across the deployment;
- three starts per rolling minute and twelve per rolling hour per Visitor;
- ten-second end-to-end execution deadline and leases that recover safely after interruption;
- at most 100 admitted Query Runs per UTC calendar month;
- charge before execution and never refund after success, failure, timeout, interruption, restart, or replacement;
- do not charge rejected attempts;
- create-if-absent initialization, first partial month, atomic UTC rollover, no unused rollover, and no manual reset;
- missing, malformed, contradictory, or future-period budget state returns Allowance Pause;
- unavailable coordination or exhausted bounded CAS retries returns Provider Unavailable;
- refusal responses carry an exact retry time where one exists; and
- the separate public Retrosheet route receives the same admission protection or is routed through the same admitted execution seam.

The in-memory store remains a behavior-test Adapter only. Public startup and readiness fail closed when a declared shared store, stable digest key, or budget valid for the current period or one safe atomic older-period rollover is unavailable. A hard deadline runs admitted deterministic work in a child process that is killed and reaped on timeout; no continuing background thread is described as stopped or allowed to occupy process concurrency indefinitely.

### Wave 2 implementation evidence

- The natural-language request model accepts exactly 500 characters and rejects 501.
- Middleware measures the complete body before Pydantic parsing, accepts exactly 16,384 bytes, rejects 16,385 bytes, and preserves allowed-origin credentialed CORS headers on the early 413.
- One CAS transition jointly prunes expired leases and rolling history, checks Visitor/deployment concurrency, minute/hour rates, and monthly allowance, then creates a 15-second lease and charges the start.
- The 100th/101st and first-period initialization boundaries are tested with competing coordinators sharing one store.
- Missing, malformed, contradictory, negative, boolean, impossible-year, and future budget records pause allowance. Store errors and bounded contention remain distinct provider-unavailable outcomes.
- Success, deterministic failure, and timeout release only the lease. Starts and monthly charges remain; interrupted or restarted work relies on lease expiry and cannot refund.
- Both `/api/query-runs` and `/api/retrosheet/queries` use the same public admission and execution seam while local routes continue calling their existing deterministic Adapters directly.
- Query Recipe, Query Plan, Query Run, parameterized DuckDB, Coverage Report, Release Bundle, local mode, CLI, and eval contracts were not changed.

## Wave 3 shared coordination Adapter

Wave 3 commits `dc4a395` and `48f3158`, plus the narrow independent-review correction on PR #27, implement the provider contract behind the Wave 2 `CasStore` seam without changing Query Recipe, Query Plan, Query Run, compiler, Coverage Report, Release Bundle, public-result, or Browser contracts.

### State object and version

- Schema version: `1`.
- Production object key: `groundball/public-admission/v1/production/state.json`.
- Proof object-key template: `groundball/public-admission/v1/proof/<proof-id>/state.json`, where the proof identifier is a validated single path segment. The proof constructor cannot produce the production key.
- The canonical compact JSON object contains only `schema_version`, `monthly_budget`, `running`, and `starts_by_visitor`. It never contains a credential, digest key, raw Visitor cookie, result payload, or private filesystem path.
- Provider input is capped at 65,536 bytes before acceptance, duplicate JSON object keys are rejected, and leases, Visitors, per-Visitor starts, total starts, identifiers, UTC timestamp precision, field sets, types, ranges, uniqueness, and ordering are strictly validated. A budget cannot report fewer charges than retained starts from its own UTC period; retained earlier-period history and leases that cross a month boundary remain valid.
- `CasVersion` is opaque. `InMemoryCasStore` retains an internal process version, while the Blob Adapter retains the exact read ETag solely for the next `x-if-match` write.

### Private HTTP and time contract

The project owns a narrow `HttpTransport` protocol implemented with bounded `requests` streaming. It does not import `vercel._internal.*` and does not claim that the current public Python SDK supplies CAS. An authenticated private `GET` targets the internally derived object URL with exactly `?cache=0`, bearer Authorization, JSON Accept, a five-second timeout, and redirects disabled. It does not claim uncached semantics from request `Cache-Control` or invented Blob cache headers. Writes target `https://vercel.com/api/blob/<object-key>` and include bearer Authorization, `x-api-version: 12`, the normalized bare `x-vercel-blob-store-id`, a fresh opaque `x-api-blob-request-id`, `x-api-blob-request-attempt: 0`, private access, JSON content type, and no random suffix. Existing-object writes additionally use the exact ETag in `x-if-match` with overwrite enabled; missing-object initialization uses overwrite disabled and no ETag. Only HTTP 412 is a CAS conflict. Other auth, transport, service, size, content type, ETag, Date, and malformed-response failures raise one sanitized provider error. Writes are never automatically retried: an ambiguous outcome fails closed, and only a later coordinator attempt after a fresh read may write again.

Every Blob read snapshot must carry canonical IMF-fixdate provider HTTP `Date` text in GMT. That strict UTC observation drives the entire decision made from that snapshot: UTC month, both rolling windows, exact retries, and the 15-second lease. Each 412 contention retry rereads both state and time. In-memory policy proofs continue to use an injected deterministic clock. There is no shared mutable last-read clock.

### Configuration, readiness, and accounting

Strict startup configuration uses `GROUNDBALL_BLOB_NAMESPACE`, `GROUNDBALL_BLOB_STORE_ID`, `GROUNDBALL_BLOB_TOKEN`, `GROUNDBALL_VISITOR_DIGEST_KEY`, and, only for proof, `GROUNDBALL_BLOB_PROOF_ID`. The store ID strips one optional `store_` prefix while preserving case, accepts only a bounded alphanumeric bare ID, and internally derives `https://<bare-store-id>.private.blob.vercel-storage.com`; configuration cannot select a public Blob hostname, alternate host, port, userinfo, path, query, or fragment. `GROUNDBALL_BLOB_TOKEN` is the explicit bearer seam and may carry a read-write or OIDC bearer token paired with that explicit store ID. Token authentication and rotation against the live provider remain protected proof; token material is never parsed or rendered. The digest key is URL-safe base64 configuration that must decode to at least 32 bytes. Secret values are excluded from repr and sanitized errors. Missing or inconsistent fields fail startup closed. Initialization remains an explicit coordinator action against a genuinely missing object; an existing object, including one with a missing budget, is never rewritten as initialization.

Digest-key rotation truth: changing the key may map the same cookie to a new per-Visitor identity and therefore fresh per-Visitor running/rate identity. It cannot reset live deployment-wide leases or the UTC-month budget because those remain in the same shared state object. Rotation is not a budget reset mechanism.

Readiness performs a private uncached read and requires strict configuration, reachable coordination, supported schema, trusted Date, and either a current valid monthly budget or a valid older period that the next admitted CAS can roll forward safely. Malformed/unsupported state remains an Allowance Pause; transport/time/service failure remains Provider Unavailable.

`OperationCounts` records local attempted reads, conditional writes, and create-if-absent operations plus successes, missing reads, conflicts, and failures. These are expected application operation classes, not Vercel billing units. Real operation charging, failed-precondition accounting, transfer observations, and Hobby-limit fit remain protected-proof gates.

### Local-only proof boundary

All Wave 3 tests use a no-network fake session, `ScriptedTransport`, or an atomic `SharedScriptedBlobBackend` and monkeypatch socket connection entry points to fail on accidental network access. The proof covers bounded streaming, timeout propagation, and redirect refusal; deterministic codec round trips, duplicate-key rejection, cross-field budget consistency, and valid month-boundary history; exact private `?cache=0` GET and ETag capture; exact current control-plane conditional and create-if-absent PUTs with unique request IDs; no automatic write retry; 412-only conflict classification and sanitized failures; one initialization winner; same-Visitor and 100th/101st races across two coordinators; canonical provider-Date-driven rollover, minute/hour limits, retries, and lease expiry despite disagreeing local clocks; proof/production isolation; strict store identity; digest-key validation; readiness; and attempted-operation counts.

No real Blob store, token, credential, account, deployment, domain, website, Cloudflare service, Mac, tunnel, root checkout, or old draft worktree was contacted or changed. Live Python/raw-HTTP compatibility and operation accounting against an isolated protected Blob require separate explicit approval.

## Shared coordination rules

Use separate non-production and production Blob state namespaces. Proof activity must never consume, initialize, reset, or rewrite the production 100-start monthly budget. Production initialization is one create-if-absent record at zero for the current UTC month and must stop on conflict.

The candidate identity records the coordination schema and configuration without claiming that proof-state contents transfer to production. Secret values, Visitor cookie values, keyed digests, Blob credentials, and state contents must never enter the attestation or logs.

Implementation must narrowly choose and document:

- Blob object key and schema version;
- uncached read and conditional-write protocol;
- bounded CAS retry count;
- trusted coordinator clock source;
- lease expiry and retry-time calculation;
- digest-key provisioning and rotation behavior;
- proof versus production namespace separation; and
- readiness behavior and operation accounting.

## All-or-nothing release gates

Every result must belong to the same candidate. Evidence does not transfer across source commits, bundles, images, runtime configurations, admission configurations, previews, or production rebuilds.

### Deterministic parity

- Same canonical Query Recipe, Query Plan, baseball outcome, ordered rows, counts, pagination, exports, evidence, sources, and fingerprints locally and hosted, except an explicit volatile environment allowlist.
- Tommy Davis returns `153 RBI` for 1962.
- The exact Ohtani question returns 2022, 34 home runs, and 15 pitching wins.
- The equivalent friendly-name composed recipe preserves its hidden name-match projection and returns the same result.
- The exact two-turn Ohtani follow-up resolves deterministically and returns 34 home runs.
- All three bundled strikeout-side Retrosheet families execute; every unbundled family remains unadvertised, unmatched, and unexecutable.

### Performance and resources

- Five independent scaled-to-zero wakes; no discarded sample or hidden retry.
- Shell and capabilities ready within five seconds.
- First cold supported Query Run completes within ten seconds.
- Every run in a fixed, predeclared twenty-run warm manifest completes within three seconds.
- Image is at most 1 GB and peak runtime memory is at most 1.5 GB.
- Record image digest and size, peak memory, build duration, cold and warm timings, and provider observations.

### Bundle and readiness

- Recompute every payload digest, row count where applicable, release identity, schema/year coverage, license, notice, and provenance record.
- Boot with external data access disabled and materialize DuckDB only from the bundle.
- Match the exact passing Coverage Report and expose only bundle-backed capabilities.
- Readiness confirms bundle, Coverage Report, DuckDB, coordinator reachability, and a well-formed current UTC budget without exposing secrets.

### Admission, results, and exports

- Prove shared CAS semantics from packaged Python against real protected Blob coordination.
- Prove second same-Visitor and fifth deployment-wide Busy Rejections, both rate windows, the atomic 100th/101st boundary, nonrefund, noncharge, rollover, initialization, lease recovery, malformed state, store failure, and bounded contention.
- Default to 25 rows; allow 50 or 100; never exceed 100; report returned and total matched counts.
- Refuse a complete export at the first of 3,000 rows, 1,500,000 downloadable bytes, or 3,500,000 complete serialized response bytes. Remeasure against the final bundle; ceilings may be lowered but not raised without a new product decision.
- Preserve the last completed result while showing a separate actionable outcome for busy, rate-limited, timed out, export too large, allowance paused, provider unavailable, unsupported, and successful no-data cases.

### Security and live Browser proof

- Hosted egress is limited to approved Vercel coordination. No LLM, Mac, tunnel, data-download source, or alternate host is reachable.
- Local-only and legacy routes are unavailable before request processing.
- Oversized, malformed, adversarial, SQL-like, and non-finite input fails before execution; SQL values remain bound parameters.
- Responses and logs expose no credential, cookie, digest key, coordination key, filesystem path, or private source excerpt.
- Run desktop and 360-430 px mobile proof locally and against the protected candidate: named parity cases, Query Recipe editing, pagination, exports, every refusal class, last-result preservation, Coverage Report, and provenance.
- Record visible outcomes, console/page errors, network destinations, responsive evidence, and exact candidate identities.

## Verification commands

Focused admission work:

```bash
uv run pytest tests/test_public_admission.py tests/test_query_api_v1.py tests/test_release_runtime.py -q
uv run ruff check src/baseball_rag/public_admission.py src/baseball_rag/api/server.py tests/test_public_admission.py tests/test_query_api_v1.py tests/test_release_runtime.py
```

Candidate baseline:

```bash
uv run python -m baseball_rag.query.generate_catalog_compatibility --check
uv run python -m baseball_rag.query.generate_raw_inventory --check
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python -m baseball_rag.query.eval_matrix
uv run pytest tests/ -m 'not llm' -q
uv run ruff check src/ tests/
uv run mypy src/baseball_rag/
npm --prefix web test
npm --prefix web run build
```

These commands are necessary but do not replace the candidate-specific offline-container, real-Blob, resource, performance, security, and live Browser gates.

### Wave 2 local verification (2026-07-19)

- `uv run pytest tests/test_public_admission.py tests/test_public_execution.py tests/test_query_api_v1.py tests/test_release_runtime.py -q`: `55 passed`; one upstream Starlette/httpx deprecation warning. The marked offline release-runtime test remained included explicitly.
- `uv run ruff check src/ tests/`: passed.
- `uv run mypy src/baseball_rag/`: passed for `59` source files.
- `uv run pytest tests/ -m 'not llm and not release_proof' -q`: `335 passed, 1 deselected`; one upstream Starlette/httpx deprecation warning.
- `uv run python -m baseball_rag.query.generate_catalog_compatibility --check`: passed with no diff.
- `uv run python -m baseball_rag.query.generate_raw_inventory --check`: passed with no diff.
- `uv run python -m baseball_rag.query.generate_coverage_report --check`: passed with no diff.
- `uv run python -m baseball_rag.query.eval_matrix`: passing, `17/17` cases.
- The first `npm --prefix web test` and `npm --prefix web run build` attempts could not load Vite because this fresh worktree had no `web/node_modules`; this was classified as missing local dependency state. `npm --prefix web ci` installed the lockfile's `107` packages with `0` vulnerabilities. The rerun `npm --prefix web test` passed `4/4` tests, and `npm --prefix web run build` passed with `113` modules transformed.
- `git diff --check`: passed. The review found no credential or private-path material in source or test changes; key and cookie literals are synthetic proof values only.

This is local repository evidence only. It does not claim a real Blob Adapter, Blob initialization, deployment, provider operation accounting, candidate attestation, protected URL, Browser proof, performance/resource proof, account change, or public cutover.

### Wave 2 self-review

Pi had no subagent or review-agent facility, so Wave 2 received an explicit direct review of every changed enforcement path. The review verified that cookies, digest keys, keyed Visitor digests, provider errors, and child-process stderr do not enter public payloads or logs; every jointly enforced limit is decided in one successful CAS write; failed release CAS leaves a bounded expiring lease and never refunds; timeout kills and reaps the child rather than abandoning a thread; early 413 responses retain allowed-origin CORS; both public POST routes enter the same seam; and the old Query/compiler/runtime interfaces remain unchanged. Review fixes added impossible year-zero budget rejection, an explicit deployment-shared store declaration, hard-stop child reaping, and acceptance of only a well-formed older budget that the next admitted CAS can atomically roll forward. The stale-base `release_proof` marker remains present. No Wave 3 Adapter, external service, deployment, account, website, Cloudflare, or Mac behavior was added or touched.

### Wave 3 TDD and local verification (2026-07-19)

The vertical slices first failed for the missing codec module, missing Blob Adapter module, missing strict configuration loader, and missing server environment-integration seam, then passed after each smallest implementation. The cross-cutting review added `CasSnapshot.exists` after proving that an existing object with a null budget must not be rewritten as initialization; the marked offline release-runtime proof was updated to model a genuinely missing proof object and returned green. The first configured hook run reformatted four files and therefore exited nonzero as designed; the second run and both commit-time hook runs passed.

Final local outputs for implementation commit `dc4a395` and the documentation closeout were:

- Focused Adapter/codec/admission/execution/API/marked-runtime proof: `88 passed`; one upstream Starlette/httpx deprecation warning.
- `uv run pytest tests/ -m 'not llm and not release_proof' -q`: `370 passed, 1 deselected`; the same upstream warning.
- `uv run ruff check src/ tests/`: passed.
- `uv run mypy src/baseball_rag/`: passed for `61` source files.
- Catalog compatibility, raw inventory, and Coverage Report `--check` generators: passed with no output or diff.
- `uv run python -m baseball_rag.query.eval_matrix`: passing, `17/17` cases.
- `npm --prefix web test`: `4/4` tests passed.
- `npm --prefix web run build`: passed with `113` modules transformed.
- `git diff --check`: passed.
- Configured pre-commit hooks: ruff, ruff-format, mypy, whitespace, EOF, YAML where applicable, and merge-conflict checks passed.

The independent-review correction followed new red tests for the exact provider protocol, strict identity/time/codec contradictions, redirect refusal, and ambiguous-write handling. Final correction outputs were:

- Adapter/codec protocol proof: `58 passed` with all socket connection entry points denied.
- Focused Adapter/admission/execution/API/runtime proof: `113 passed`; one upstream Starlette/httpx deprecation warning.
- CI-equivalent fast Python suite with coverage: `395 passed, 1 deselected`; the same upstream warning; aggregate coverage `75%`.
- Relevant marked offline release proof: `1 passed`.
- Ruff passed; mypy passed for `61` source files; configured pre-commit hooks passed.
- Catalog compatibility, raw inventory, Coverage Report, and coverage proof validator checks passed with no generated diff.
- Deterministic eval matrix passed `17/17` cases.
- Web tests passed `4/4`; the web build passed with `113` modules transformed.
- Root and nested `uv lock --check`, `git diff --check`, and the final changed-file/stale-contract searches passed.

### Wave 3 self-review

No subagent or review-agent facility was available, so Wave 3 received an explicit direct review of the complete diff. Independent protocol/security review then identified stale provider assumptions, and the correction rechecked the exact authenticated private `?cache=0` GET, current `vercel.com/api/blob` write origin and API/store/request headers, five-second transport timeout, redirects disabled, bounded bodies, private JSON content type, random-suffix prohibition, overwrite modes, exact ETag retention, 412-only conflict classification, one-winner creation, no ambiguous-write retry, canonical Date flow, no mutable shared time, duplicate-key and cross-field codec contradictions, collection and identifier limits, store-derived private origin, proof/production key construction, decoded key length, secret-safe repr/errors, readiness distinctions, and attempted-operation counters. It also rechecked that both existing public POST routes still enter Wave 2 unchanged, the ten-second execution deadline and 15-second lease remain intact, and no Query/compiler/Coverage/Bundle/result/Browser contract moved.

This proof deliberately uses only injected fake/scripted transports and socket-denial guards. It does not establish that Vercel's live service accepts this raw-HTTP contract, how Vercel bills successful or failed operation attempts, or whether actual Hobby limits remain safe. Those are protected-proof gates requiring separate approval.

## Wave 4 public result and Browser contract

Wave 4 merged in PR #28 at `91d1dfa6c3473481068fa8985a1f5b37f31ce3fc`, after implementation on `implementation/public-deterministic-groundball-results-browser` from PR #27 merge `30a2bc590c9c0f0438a4c8b29175005103c2024d`. It did not alter Query Recipe, Query Plan, Query Run, compiler, Coverage Report, Release Bundle, Wave 2 admission, or Wave 3 coordination behavior. The existing local `run_query_input` Interface and exhaustive export behavior remain unchanged.

### Public result and export contract

- `public_results.py` is the narrow public-only Adapter used inside the existing hard-stopped query child. Natural-language and output-omitted public recipes default to 25 rows; structured interactive output accepts exactly 25, 50, or 100 with a nonnegative integer offset. Unsupported sizes and invalid offsets are rejected rather than clamped.
- Successful rows and no-data payloads expose top-level `returned_row_count`, `total_matched_count`, and `pagination` with `size`, `offset`, and `has_more`. An exhausted nonzero page remains `rows` with zero returned rows and a truthful nonzero total; zero matches remains successful `no_data`.
- Pagination keeps the completed published recipe unchanged except for its interactive output size and offset. No public page can exceed 100 rows. Clarification recipes receive the same 25-row public default.
- CSV and JSON exports are complete or refused. The first exceeded ceiling is checked in fixed order: 3,000 matched rows, 1,500,000 UTF-8 downloadable bytes, then 3,500,000 UTF-8 bytes for the complete compact response body. Equality is allowed; only a greater observed value is refused.
- The complete-response measurement uses the same deterministic `ensure_ascii=False`, compact JSON encoding emitted by successful public HTTP responses. Row-limit refusal occurs before encoding a large success to child stdout; no refusal payload contains `rows` or `export` material.
- Export refusal is a structured HTTP 422 with `error: export_too_large`, truthful total matched count, the named ceiling, configured maximum, observed value, detail, and filter guidance. Local exports remain unrestricted; the existing 3,613-row TeamReference proof stays green while the same public export is refused.

### Browser contract

- `lastCompletedRun` and `attemptOutcome` are separate state. Pending work, clarification, busy, rate limit, timeout, export ceiling, allowance pause, provider unavailability, unsupported/rejected, failure, malformed response, and other non-completed outcomes cannot erase or replace the completed rows/no-data run.
- Every request activates Query before transport begins. Clarification remains above the completed result; every latest non-clarification attempt is labeled and rendered before the preserved completed result, including requests initiated from Browse fields.
- Structured non-2xx JSON is retained rather than collapsed into a generic error. Exact `retry_at` values and export filter guidance are rendered. One user action produces one request; there is no queue, hidden retry, redirect, alternate endpoint, Mac, tunnel, LLM, paid fallback, or download on refusal.
- Completed rows and successful no-data update browser-local history. Details, evidence, recipe editing, exports, and pagination remain attached to the last completed run. Export success creates exactly one complete download without replacing that run; refused or malformed exports close Details, return focus to the result controls, and reveal the attempt above the preserved result.
- Public Browse-fields recipes begin at 25 rows while local Browse-fields recipes retain 100. Public paginated result titles report the returned page size rather than calling it the total matching count; legacy/local payloads without pagination metadata retain the matching-rows title.
- The result surface reports “returned X of Y matched,” including exhausted pages, and exposes labeled 25/50/100 page-size, Previous, and Next controls with deterministic offset-zero page-size changes. Responsive CSS stacks full-width controls below 600 px for the required 360–430 px range while preserving the dark shell and existing focus-trap/return behavior.

### Wave 4 TDD and local verification (2026-07-19)

Vertical slices first failed for the missing public Adapter, unsupported page validation, missing counts/pagination, each export ceiling boundary, child/API integration, completed-result preservation while pending, structured refusal parsing, pagination controls, and export refusal handling. Each slice received the smallest green implementation before the next behavior. No test-only production bypass was added.

Final local outputs before documentation closeout were:

- Focused public-result/admission/Blob/execution/API/marked-runtime proof: `143 passed`; one upstream Starlette/httpx deprecation warning.
- Focused public-result/execution/API proof after final boundary additions: `56 passed`; the same upstream warning.
- `uv run pytest tests/ -m 'not llm and not release_proof' -q`: `425 passed, 1 deselected`; the same upstream warning.
- Explicit `uv run pytest tests/test_release_runtime.py -m release_proof -q`: `1 passed`.
- `uv run ruff check src/ tests/`: passed. Ruff formatting check passed for all changed Python.
- `uv run mypy src/baseball_rag/`: passed for `62` source files.
- Catalog compatibility, raw inventory, Coverage Report regeneration check, and coverage proof validator: passed with no generated diff.
- Deterministic eval matrix: `17/17` passing.
- `npm --prefix web test`: `24/24` passing. Tests cover public/local Browse-fields defaults, truthful partial and exhausted page titles, pending state, every named refusal class, malformed and clarification outcomes, exact retries/guidance, cross-surface Query activation, latest-attempt order, Details teardown/focus, one-request actions, no-data/history, same-recipe request bodies, accessible labels, one successful download, and zero refused downloads.
- `npm --prefix web run build`: passed with `113` modules transformed.
- Configured pre-commit hooks passed: ruff, ruff-format, mypy, trailing whitespace, EOF, YAML, and merge-conflict checks.

Pi exposed no subagent or review-agent facility, so Wave 4 received an explicit direct review of the complete diff. The review checked public-only limit placement, off-by-one equality, UTF-8 rather than character counts, exact compact response encoding, row/content/response ceiling order, refusal material removal, exhausted/no-data truth, local 100-row and exhaustive export preservation, child stdout behavior, state separation, one-request actions, structured error retention, accessibility/mobile CSS, frozen seam preservation, and absence of secrets, cookies, private values, or fallback paths.

This Wave 4 evidence is repository and local no-network DOM/API evidence only. It does not prove live Vercel Blob compatibility, provider accounting, a deployment, protected or production Browser behavior, candidate parity, performance/resources, a Deployment Attestation, website integration, or cutover. Wave 5 addresses repository deterministic parity separately below; protected proof plus every external mutation still require separate explicit approval.

## Wave 5 deterministic parity closure

Wave 5 merged in PR #29 at `17d972d2c4a2c7f601c5908e707e7714e6fd7c35`. It was implemented from PR #28 merge `91d1dfa6c3473481068fa8985a1f5b37f31ce3fc` and preserves every Wave 1–4 query, admission, result, export, Browser-state, Release Bundle, and fail-closed boundary.

### Composed-plan and exact Ohtani parity

- The promoted compiler's internal fact subqueries can retain catalog-owned hidden match aliases for composed plans without exposing those aliases as result columns. The composed projection carries every hidden `player.name` match alias needed by the post-composition predicate; the name remains four bound values rather than SQL text.
- The exact question `how many home runs did ohtani hit in the year he had the most wins as a pitcher` resolves to the reviewed Batting/player-season recipe, ranks `pitching.W` highest with ties, and returns exactly Shohei Ohtani in 2022 with 34 home runs and 15 pitching wins.
- The equivalent structured recipe enters the same public 25-row Adapter and has equal stable recipe, plan, ordered rows, evidence, source fingerprints, verification, returned/total counts, and pagination fields. Volatile request/environment metadata is not part of the assertion.

### Explicit deterministic follow-up context

- `previous_recipe` is the only additive context field. It is optional, contains only one strictly parsed and currently valid preceding Query Recipe, and is accepted only beside `question`; it is rejected beside structured `recipe` input and cannot carry rows or unknown fields.
- The exact first turn `how many RBIs did Shohei Ohtani have in 2022` returns the verified 95-RBI row. The exact follow-up `what about his home runs in 2022?` requires one unambiguous prior `player.name equals <name>` predicate and returns the verified 34-HR row. Missing or ambiguous identity fails closed without an LLM or fallback.
- The Browser sends `lastCompletedRun.recipe` in the same single POST for a natural follow-up. It sends no rows or hidden conversation state, preserves the completed result while pending or refused, and replaces it only after a successful rows/no-data response. Local and public API paths and the isolated child share the same interpretation seam. The 16 KiB whole-body ceiling, one-action/one-request rule, ten-second deadline, and admission decision are unchanged.

### Named parity corpus and release boundaries

- The existing machine-readable `query/eval_matrix.json` is extended in place from 17 to 26 cases, preserving every prior case ID. It now names Tommy Davis 1962, exact Ohtani natural and structured parity inputs, the exact two-turn follow-up, all three bundle-backed strikeout-side templates, and all three unbundled Retrosheet negatives.
- Each unbundled family remains available to the complete local Retrosheet matcher but absent from public capabilities, unmatched by the public release matcher, and explicitly invalid under release-bound execution. No negative becomes no-data or falls back to local archives/full data.
- Public Retrosheet remains one advertised `pitcher_strikeout_side` capability backed only by the compact projection. The marked offline release proof executes all three positive templates and rejects all three negatives through the public API.

### Wave 5 local verification (2026-07-19)

- Focused compiler/Adapter/result/child/API/eval/Retrosheet/Release Bundle/runtime proof: `130 passed`; one upstream Starlette/httpx deprecation warning.
- Fast Python suite: `438 passed, 1 deselected`; the same upstream warning.
- Marked offline proof: `1 passed, 438 deselected`; the same upstream warning.
- Deterministic eval/parity matrix: `26/26` passing.
- Browser DOM suite: `25/25` passing.
- The Coverage Report still proves `5,253/5,253` obligations with zero uncovered; its compiler identity and proof ID were regenerated canonically. The canonical assembler bound the checked-in Release Bundle to source commit `7007d135e2fb8afa60589040b442577159404685` with bundle digest `ab88172bd1170e5b2d1a79c33e322c95d75ed5ee65abe8983ac199b46478d0c6`. Generated changes are limited to the root Coverage Report JSON/Markdown, the bundled Coverage Report copy, and the Release Manifest; catalog/data payloads and bundle scope are unchanged.
- Catalog compatibility, raw inventory, Coverage Report generation check and validator, full Ruff, changed-Python format check, mypy for `62` source files, web build with `113` transformed modules, configured pre-commit, and `git diff --check` all pass after final bundle assembly.

Pi exposed no subagent or review-agent facility, so Wave 5 received an explicit direct review. The review checked hidden aliases remain internal and catalog-owned, values stay bound, natural and structured plans stay canonical, context cannot accompany structured input or contain rows, pronouns fail closed without one name predicate, independent questions ignore context, Browser actions remain one request, completed results survive pending/refusal, public limits and hard-stop execution are unchanged, all Retrosheet negatives fail before runtime fallback, full local Retrosheet behavior remains intact, and no external/provider/Mac/deployment behavior was touched.

This remains repository and local no-network proof only. No live provider, Blob, deployment, protected Browser, performance/resource, website/domain, Cloudflare, Mac, tunnel, candidate attestation, or cutover proof occurred in Wave 5.

## Wave 6 candidate identity and gate tooling

Wave 6 is implemented on `implementation/public-deterministic-groundball-candidate-gates`, based exactly on PR #29 merge `17d972d2c4a2c7f601c5908e707e7714e6fd7c35`. It preserves the provider-neutral Release Manifest and non-circular source-then-bundle artifact freeze.

- `public_release_config.py` owns the rendering-neutral read model derived from the actual enforced limits, cookie flags, state schema, digest-key minimum, deadline, lease, and bounded CAS constants. `release/config/public-admission-policy.json` is canonical generated JSON and its `--check` command fails on drift.
- `release/config/local-ci-runtime.json` is strict non-secret configuration. It says `local_ci`, `provider_deployment: false`, `network_policy: none`, and `local_ci_ephemeral`; unknown fields, unknown release environment keys, secret values, or a provider claim fail closed.
- `release_candidate.py` emits and validates canonical candidate identity, the fixed Release Gate inventory, and Deployment Attestation records. It rejects duplicate keys or evidence IDs, unknown fields, booleans used as integers, malformed or truncated identities, secret/path content, topology and binding mismatches, and foreign evidence. Candidate ID hashing excludes only its own field.
- Every gate is exactly `pass`, `fail`, or `blocked`; a pass requires candidate evidence, and eligibility requires all fixed gates to pass for that candidate. Local CI passes only topology/identity, bundle/Coverage Report, deterministic public-envelope parity, offline/prohibited-surface, preliminary local image-size, and runtime/admission-config gates. Protected/provider gates remain blocked, so the report is intentionally ineligible.
- A Wave 6 local Deployment Attestation template explicitly says no provider deployment exists and cannot be promotion-eligible. No Vercel attestation is fabricated. Protected/production validation later requires exact provider deployment/image identity, unchanged bundle/config/gate bindings, observations, all-pass gates, and external evidence.
- `.github/workflows/candidate-proof.yml` replaces the dormant retired-branch job. It checks out the exact PR head with full history, derives source/artifact topology from the Release Manifest and Git commits, requires an artifact-only bundle commit, builds the exact-source Dockerfile, records local Docker ID/size, enforces 1 GB, boots with `--network none`, exercises the Wave 5 natural/structured/follow-up/paging/export/Retrosheet corpus, checks prohibited files and persistent authority, then uploads candidate, gate, template, evidence, and summary artifacts even on safe failures.

Exact artifact meanings, freeze steps, and pasteable assembly/validation commands are in `docs/release-candidates.md`. Local Docker ID/size are explicitly not future provider OCI digest/size. No Blob, credential, preview, deployment, provider accounting, protected Browser, performance, restart, scale-to-zero, memory, website, domain, Cloudflare, Mac, or tunnel state is contacted or changed in Wave 6.

### Wave 6 TDD, review, and local verification (2026-07-20)

Vertical tests first failed for the missing actual-policy/config module, candidate/gate/attestation module, and candidate workflow. Final pre-freeze source results were:

- Focused policy/candidate/gate/attestation/workflow plus admission/API/runtime proof: `149 passed`; one upstream Starlette/httpx deprecation warning.
- Fast Python suite: `472 passed, 1 deselected`; the same upstream warning.
- Marked offline Release Proof: `1 passed, 472 deselected`; the same upstream warning.
- Deterministic eval/parity matrix: `26/26` passing. Catalog compatibility, raw inventory, Coverage Report generation check, and Coverage Report validator passed with no generated diff.
- Ruff lint and full format check passed; mypy passed for `65` source files; configured pre-commit passed all hooks.
- Browser DOM suite: `25/25` passing. Web production build passed with `113` transformed modules.
- A synthetic aggregate CLI dry run emitted and revalidated all three canonical records with `6` local passes, `9` protected/provider blocks, `eligible: false`, and `deployment_exists: false`.
- Docker Engine `29.4.3` was reachable, but the exact local build could not acquire uncached `python:3.12-slim` and `node:22-alpine` base images because the host Docker credential helper terminated. No credential configuration was inspected or changed. Therefore no local image ID/size or container result is claimed; the fresh exact-head GitHub candidate-container job is mandatory before PR readiness.

Pi exposed no subagent/review-agent facility. Direct self-review covered canonical/duplicate-key behavior, integer-versus-boolean checks, secret/path exclusion, source/artifact and candidate/report/attestation bindings, fixed gate and provider-observation inventories, scope-specific local-versus-provider image measurements, generated-policy drift, provider fail-closed startup, explicit local-CI isolation, exact-head workflow checkout, artifact-only topology, safe failure uploads, prohibited-surface checks, and the absence of any provider/account/Mac/tunnel mutation or green substitution for blocked evidence.

## Abort and rollback rules

- Any gate miss, identity mismatch, warning-only substitution, unexpected route or network destination, resource overage, or Browser failure makes the candidate ineligible.
- Preview evidence never silently transfers to a production rebuild. Re-attest and rerun every applicable gate for the final artifact.
- Reopen hosting only after root-cause evidence proves a required gate impossible on Vercel Hobby without weakening the product, exceeding `$0`, or violating zero-Mac.
- First-launch rollback is the website launcher's prelaunch or unavailable state. Never roll back to the Mac, a tunnel, an LLM, an alternate host, or an unattested deployment.
- The implementation map does not name the website repository, launcher path, current prelaunch target, or rollback commit. Resolve those read-only before proposing the cutover patch, then request explicit cutover approval.

## Definition of done

- All repository waves are complete and recorded here with commits and focused verification.
- One candidate has one machine-readable gate report and Deployment Attestation.
- Every all-or-nothing local, hosted, resource, security, admission, and live Browser gate passes for that candidate.
- Current Vercel Hobby, container, and Blob limits and the live Hobby scope are reverified before deployment.
- The protected candidate link is accepted by Stewart.
- Production receives its own attestation and applicable proof.
- The website launcher is switched only after explicit approval and passes external zero-Mac verification.
- Remaining changes, running services, account state, rollback state, and residual risks are recorded.

## Coordinator handoff prompt

```text
Continue the Public Deterministic Ground Ball implementation and release.

Work only in:
/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-release

Branch:
implementation/public-deterministic-groundball-candidate-gates

Read first:
- AGENTS.md
- CONTEXT.md
- docs/public-release-implementation-ledger.md

The completed Wayfinder map is on wayfinder/queryable-ground-ball at 6675ad1. Do not reopen its decisions unless current evidence invalidates a gate.

Waves 2-5 are merged through PR #29 at `17d972d`. Wave 6 implements canonical candidate identity, actual-policy/runtime binding, all-or-nothing gates, strict provider-attestation validation, an explicit no-deployment local template, and branch-independent candidate-container CI. Review and merge only this repository/local tooling proof without claiming provider, protected Browser, deployment, performance, persistence, accounting, or promotion evidence. Do not begin Wave 7 external proof without Stewart's separate explicit authorization, and do not reopen completed query, admission, result, parity, or candidate-identity decisions.

Continue through authorized repository implementation and local validation without stopping after a narrow green test. Do not create Blob state or secrets, deploy, delete deployments, promote, change domains or website launchers, enable paid services, activate Cloudflare, or touch Mac/tunnel state without Stewart's explicit approval at that boundary.

Update this ledger as each wave lands. Keep completed work closed, record commit and verification evidence, and preserve the frozen Query and Release Bundle seams.
```
