# Define parity and release gates

Type: `grilling`
Status: resolved
Blocked by: [Prove the stateless Svelte/FastAPI Vercel fit](12-prove-stateless-svelte-fastapi-vercel-fit.md), [Choose the packaged deterministic data release](04-choose-packaged-data-release.md), [Set public query, export, and abuse guardrails](05-set-public-query-export-and-abuse-guardrails.md), [Prove stateless Public Admission Policy feasibility](13-prove-stateless-public-admission-policy-feasibility.md), [Choose the Public Allowance Pause authority](14-choose-public-allowance-pause-authority.md)

## Question

What exact local-versus-hosted equivalence rules for the Published Query Catalog, Query Recipe, Query Plan, Query Run, and Coverage Report contracts; cold-start and warm-query budgets; security assertions; deterministic-admission checks; data-release checks; container limits; restart behavior; and browser scenarios must pass before the packaged Svelte/FastAPI/DuckDB application is safe to publish?

## Answer

Publication is governed by one all-or-nothing set of **Release Gates**. A release candidate is one fixed source commit, immutable Release Bundle and Release Manifest digest, container image and digest, runtime configuration, Public Admission Policy configuration, and provider-specific Deployment Attestation. Evidence from another commit, bundle, image, configuration, or historical preview does not transfer to it.

Every gate below must pass for that same candidate. A miss is not a warning: it blocks publication until the candidate passes or Stewart explicitly reopens the relevant product decision. The gate evidence makes a candidate eligible for the later preview and cutover proof; it does not itself authorize deployment, promotion, a domain change, or any production mutation.

### Local and hosted parity

Parity means the same deterministic baseball meaning, not byte-for-byte identity of volatile hosting metadata. For every supported parity input inside the public request, page, and export envelope, local and hosted Ground Ball must expose the same Published Query Catalog and exact passing Coverage Report identity and produce the same:

- accepted Query Recipe after canonical serialization;
- Query Plan after canonical serialization;
- baseball answer and outcome class;
- ordered rows, returned-row count, total matched-row count, pagination behavior, and complete CSV and JSON downloads;
- factual sources, source fingerprints, evidence, and provenance; and
- deterministic follow-up result when the follow-up can be derived from the preceding Query Recipe.

Only an explicit environment allowlist may differ: request or run identifiers, timestamps, measured durations, public-versus-local capability flags, deployment metadata, and local-only architecture traces, source excerpts, and developer-tool metadata. Public admission outcomes may wrap the shared deterministic Query Run Interface, but once a public run is admitted its baseball meaning must match local behavior. Differences outside that allowlist fail the gate.

The public Adapter remains unable to use an LLM. A contextual follow-up that requires LLM interpretation fails closed publicly; a deterministic follow-up that can refine the preceding Query Recipe must work identically in both environments. Local LLM-only capabilities are not part of the parity corpus and do not justify a hosted fallback or a second query contract.

Machine checks must exhaustively exercise every promoted catalog capability and raw Lahman surface. A small named golden corpus makes the critical behavior legible and must include at least:

- `who had the most RBIs in 1962` returning Tommy Davis with 153 RBI;
- `how many home runs did ohtani hit in the year he had the most wins as a pitcher`, returning Shohei Ohtani, 2022, 34 home runs, and 15 pitching wins;
- the equivalent composed Query Recipe: Batting at player-season grain; select `player.name`, `season`, `batting.HR`, and `pitching.W`; filter `player.name` equal to `Shohei Ohtani`; rank the highest `pitching.W` with ties; and return the same 2022 result without losing the hidden player-name match projection;
- the two-turn deterministic follow-up `how many RBIs did Shohei Ohtani have in 2022` then `what about his home runs in 2022?`, resolving the pronoun from the preceding turn and returning 34 home runs;
- each of the three bundle-backed strikeout-side Retrosheet families; and
- negative cases proving every unbundled Retrosheet family is unadvertised, does not match, and cannot execute.

### Performance and container fit

The final protected candidate must meet all of these user-visible budgets:

- application shell and capability readiness within 5 seconds of an independent cold wake;
- the first supported Query Run after a cold wake completed within 10 seconds; and
- each supported warm Query Run completed within 3 seconds.

One cold-wake sample begins only after the provider reports the candidate scaled to zero. From one documented external client using a monotonic clock, readiness is measured from sending the first root request until both the application shell and capability response are complete and identify the expected candidate. The first-query measurement begins when that ready client sends the default Tommy Davis Query Run request and ends when the complete response body arrives. A warm sample begins after readiness and at least one successful Query Run on the same live candidate, with no restart or scale-down, and is measured from request send through the complete response body.

The proof uses five independent cold-wake samples and a fixed twenty-run warm manifest recorded before execution. The warm manifest must cover the named golden corpus, normal pagination and export, all three Published Retrosheet Capabilities, and the public-envelope boundaries; a failed workload cannot be replaced after the run. Every sample must pass, with no discarded outlier, hidden retry, or average or percentile that masks a miss. The separately approved ten-second end-to-end Query Run deadline remains authoritative, and an over-deadline run returns the truthful timeout outcome rather than unsupported or no data.

The same candidate must remain at or below 1 GB of provider-reported container image size and 1.5 GB peak runtime memory. Record the actual image digest, image size, peak memory, build duration, cold and warm timings, and relevant provider observations. The older 132.84 MB Svelte preview predates the final Queryable Ground Ball release shape and is precedent only, not release evidence.

### Release Bundle and readiness

The Release Bundle freeze rules from [Choose the packaged deterministic data release](04-choose-packaged-data-release.md) are mandatory gates. For the fixed candidate, proof must:

- assemble the bundle before the final container build and perform no build-time or runtime acquisition of bundle bytes;
- enumerate and recompute every payload checksum, row count where applicable, canonical Release Manifest digest, source revision, source release, schema and year coverage, proof identity, license, notice, and provenance record;
- regenerate the exact Coverage Report and prove catalog, compiler, Adapter, data-release, and source-fingerprint compatibility;
- boot from the immutable bundle with external data access disabled;
- materialize and query DuckDB successfully without a persistent database or cache becoming release authority;
- advertise and execute only bundle-backed Published Retrosheet Capabilities; and
- bind the unchanged bundle and final image to the provider-specific Deployment Attestation.

Process liveness alone is insufficient. One read-only release-readiness result must confirm the expected Release Bundle identity, exact passing Coverage Report identity, working DuckDB materialization, reachable admission coordinator, and well-formed current UTC monthly-budget period and count. It must expose no secret and must fail closed when an identity or dependency is missing, stale, malformed, or contradictory.

### Public Admission Policy

The release candidate must prove the complete Public Admission Policy against real protected Vercel Blob coordination, not only an in-memory model. One atomic admission decision immediately before the Query Run Adapter must jointly enforce a 500-character natural-language question limit, a 16 KiB complete request-body limit, one running run per Visitor, four running runs deployment-wide, three starts per minute and twelve per hour per Visitor, live leases, and the 100-start UTC monthly allowance. It creates no queue.

Anonymous Visitor identity uses a random opaque first-party `Secure`, `HttpOnly`, `SameSite` cookie, while shared coordination state retains only its keyed one-way digest. Clearing or rotating that cookie legitimately creates a new anonymous Visitor; this is a human-paced product limit, not authentication or an anti-Sybil claim. Cookie rotation may start fresh per-Visitor limits but must never reset the deployment-wide running count or monthly allowance.

The proof must establish:

- private uncached reads and conditional writes work from the packaged Python runtime;
- one trusted coordinator clock governs rolling windows, monthly periods, retry times, and lease expiry;
- a competing fifth deployment-wide run and second same-Visitor run receive truthful Busy Rejections;
- minute and hour limits name the reached limit and exact retry time;
- the 100th start is admitted and a concurrent or later 101st start is refused;
- an admitted start is charged before execution and is never refunded after timeout, failure, interruption, restart, or deployment replacement;
- rejected admission attempts do not consume a monthly start;
- create-if-absent initialization, the first partial month, atomic UTC rollover from an older well-formed period, no rollover of unused starts, and prohibition of manual or deployment-driven reset all behave as approved;
- missing, malformed, contradictory, or future-period state returns Allowance Pause, while an unavailable store or exhausted bounded conditional-write retry returns Provider Unavailable;
- interrupted leases expire safely after the Query Run deadline without resetting rate or monthly history;
- every refusal preserves the Browser's last completed Query Run and updates a separate actionable attempt outcome; and
- actual Blob operation and transfer accounting, including bounded contention retries and lease release, remains within the approved free topology.

Interactive pages must default to 25 rows, allow 50 or 100 rows, never exceed 100 rows, and report returned and total matched counts with truthful pagination. Complete CSV or JSON export must be refused at the first of 3,000 rows, 1,500,000 downloadable bytes, or 3,500,000 bytes for the complete serialized response. The final Release Bundle must repeat the payload-size measurement; the candidate may lower a ceiling to fit but cannot raise one without a new product decision.

Restart, replacement, and scale-to-zero recovery must retain the monthly count and the history for each still-identifiable Visitor in shared coordination state. No in-process lock, browser state, restart, or new deployment may reset deployment-wide or monthly state; cookie clearing or rotation has only the explicitly approved new-Visitor effect above. Before promotion, `discostew6082s-projects` must satisfy the already-approved Ground-Ball-only active Hobby-scope rule. The evidence must continue to state that the application-owned counter cannot guarantee Vercel availability because page traffic, platform overhead, and provider accounting sit outside it.

### Security and honest failure

The hosted application may contact only the Vercel coordination store needed by the Public Admission Policy. Release proof must show that the final container cannot contact an LLM, Stewart's Mac, a tunnel, an alternate host, or a data-download source under successful, refused, malformed, timed-out, or failed requests.

Public route enumeration must prove that local-only Architecture Explorer, source inspection, test execution, eval mutation, review mutation, legacy request models, compatibility Adapters, and developer tools are unavailable before request processing. The deployed origin and preview protection rules must deny unapproved cross-origin or unauthenticated access as applicable. Oversized, malformed, adversarial, SQL-like, and non-finite inputs must fail before execution; SQL values remain bound parameters; logs and responses expose no credential, cookie value, coordination key, filesystem path, or source excerpt unavailable in public mode.

The public Interface must distinguish busy, visitor rate-limited, execution timed out, export too large, allowance paused, provider unavailable, unsupported, and successful no-data outcomes. None may silently truncate, queue, retry, pay, or fall back elsewhere. If Vercel itself pauses or rejects the deployment, Ground Ball reports Provider Unavailable wherever application code can still respond and makes no claim that the 100-start budget reserved provider capacity.

### Live Browser proof

Exhaustive catalog and data coverage belongs in machine checks. The final candidate also needs a compact live Browser proof on both desktop and 360-430 px mobile layouts, locally and against the protected hosted preview where the capability is shared. It must exercise:

- the Tommy Davis default answer;
- the exact Ohtani question and composed player-name Query Recipe named above;
- the exact two-turn deterministic follow-up named above;
- an approved strikeout-side Retrosheet query and an unavailable unbundled family;
- Query Recipe editing, pagination, and complete CSV and JSON downloads;
- every public refusal class while the last completed result remains visible; and
- Coverage Report and provenance access.

The proof records visible outcomes, console and page errors, network destinations, responsive layout evidence, and the exact candidate identities. Mocked DOM tests and the prior phone approval of the application shell remain useful lower-level evidence but cannot replace this live release proof.

### Final disposition

Gate results and artifacts must be machine-readable, summarized for human review, and linked from the Deployment Attestation. Any parity mismatch outside the allowlist, failed sample, missing artifact, resource overage, unexpected route or network destination, admission inconsistency, Browser failure, stale identity, or warning-only substitution makes the candidate ineligible.

[Define preview cutover and zero-Mac proof](07-define-preview-cutover-and-zero-mac-proof.md) remains responsible for the preview-to-public topology, website integration switch, external zero-Mac evidence, rollback proof, and actual abort or promotion procedure. This answer authorizes none of those mutations.
