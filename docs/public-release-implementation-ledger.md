# Public Deterministic Ground Ball Implementation and Release Ledger

Status: Active.

This is the execution handoff for the completed Public Deterministic Ground Ball Wayfinder map. It governs repository implementation, candidate proof, and release preparation. It does not itself authorize an external deployment or public cutover.

## Canonical continuation

- Working directory: `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-release`
- Branch: `implementation/public-deterministic-groundball-release`
- Baseline: `origin/main` at merge commit `a4084f1`
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

The landed foundation packages the four Lahman tables, catalog and registry assets, generated raw inventory, team references, exact Coverage Report, compact strikeout-side Retrosheet projection, provenance, licenses, and canonical Release Manifest. It boots without acquiring data and advertises only the three bundle-backed Retrosheet families.

This is foundation evidence, not final release evidence. It does not yet prove shared public admission, final parity, performance, live Browser behavior, real Blob coordination, a Deployment Attestation, or public cutover.

### Preserved in-progress Public Admission Policy draft

The previous worktree contains five uncommitted files that must be preserved and inspected before being ported here:

- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/src/baseball_rag/api/server.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/src/baseball_rag/public_admission.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/tests/test_query_api_v1.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/tests/test_public_admission.py`
- `/Volumes/Envoy/projects/groundball/.worktrees/public-deterministic-groundball-implementation/tests/test_release_runtime.py`

On 2026-07-19, the focused command below passed `25` tests with one upstream deprecation warning:

```bash
uv run pytest tests/test_public_admission.py tests/test_query_api_v1.py tests/test_release_runtime.py -q
```

The draft proves an in-memory CAS state model, Visitor cookie digest, per-Visitor and deployment concurrency, minute and hour limits, leases, UTC-month rollover, a nonrefundable 100-start budget, 16 KiB body rejection, and basic HTTP refusal mapping. It is not production authority: its store and digest key are process-local, it has no Vercel Blob Adapter, and the real release path does not initialize or attest the budget.

Do not commit more source work on the old `implementation/public-deterministic-groundball` branch. Its release-container CI assumes an artifact-only tip and is hard-coded to that retired branch name. Port the five-file draft into this continuation worktree, verify the resulting diff, and leave the old dirty worktree intact until the port is confirmed.

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
| 2. Public Admission Policy core | In progress off-branch | Port and finish the pure state model and FastAPI seam; add stable configuration boundaries; enforce question/body limits, concurrency, rates, leases, monthly budget, timeout, and honest outcomes | Focused policy/API/runtime tests; no in-memory Adapter accepted as deployment authority |
| 3. Shared coordination Adapter | Pending after wave 2 | Implement Vercel Blob uncached read plus conditional-write CAS, trusted time, stable keyed Visitor digest, schema/versioning, initialization, readiness, and operation accounting | Local contract proof first; real Blob proof only after external approval |
| 4. Public result and Browser contract | Pending after wave 2 | Preserve last completed run separately from attempt outcome; 25/50/100 paging; returned and total counts; complete-or-refused CSV/JSON; timeout and all refusal classes | Focused API and web tests plus local Browser evidence |
| 5. Deterministic parity closure | Pending | Prove or fix the exact Ohtani cross-discipline question, equivalent friendly-name recipe, deterministic two-turn follow-up, three bundled Retrosheet families, and all unbundled negative cases | Named parity corpus plus exhaustive catalog/raw-surface checks |
| 6. Candidate identity and gate tooling | Pending after waves 2-5 | Bind one source commit, bundle digest, image digest, runtime config, admission config, evidence set, and Deployment Attestation; repair release-container CI so it is not tied to the retired branch | Machine-readable gate report and reproducible candidate assembly |
| 7. Protected Vercel proof | Blocked on explicit external approval | Provision isolated proof coordination, deploy protected candidate, and run real Blob, restart, scale-to-zero, performance, security, and live Browser gates | All gates pass for one candidate; no promotion |
| 8. Production and website cutover | Blocked on gates and explicit approvals | Build and attest final production artifact, send Stewart its link, receive acceptance, then make one reversible launcher change and externally verify | Stewart acceptance, attestation, post-switch proof, rollback proof |

## Wave 2 completion details

The Public Admission Policy must sit immediately before deterministic execution and jointly decide every limit. Finish these behaviors before moving to the real coordination Adapter:

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

The in-memory store remains a behavior-test Adapter only. Public startup must fail closed when a shared store, stable digest key, or valid monthly budget is unavailable.

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
implementation/public-deterministic-groundball-release

Read first:
- AGENTS.md
- CONTEXT.md
- docs/public-release-implementation-ledger.md

The completed Wayfinder map is on wayfinder/queryable-ground-ball at 6675ad1. Do not reopen its decisions unless current evidence invalidates a gate.

Begin with Wave 2. Preserve the dirty five-file admission-policy draft in the old public-deterministic-groundball-implementation worktree. Port it into this continuation worktree, verify the diff, and leave the old worktree untouched until the port is confirmed. The last focused run passed 25 tests.

Continue through repository implementation and local validation without stopping after a narrow green test. Do not create Blob state or secrets, deploy, delete deployments, promote, change domains or website launchers, enable paid services, activate Cloudflare, or touch Mac/tunnel state without Stewart's explicit approval at that boundary.

Update this ledger as each wave lands. Keep completed work closed, record commit and verification evidence, and preserve the frozen Query and Release Bundle seams.
```
