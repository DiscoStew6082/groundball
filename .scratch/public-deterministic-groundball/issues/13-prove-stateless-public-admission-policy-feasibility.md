# Prove stateless Public Admission Policy feasibility

Type: `prototype`
Status: resolved
Blocked by: [Set public query, export, and abuse guardrails](05-set-public-query-export-and-abuse-guardrails.md)

## Question

Can one bounded, protected Vercel Hobby prototype prove a privacy-appropriate anonymous Visitor identity; atomically enforce one running Query Run per Visitor, three starts per minute, twelve starts per hour, and four running Query Runs deployment-wide across stateless instances without a paid dependency; and obtain a sufficiently current, trustworthy CPU and memory usage signal to fail closed at the 70% Allowance Pause? The proof must preserve the last completed Query Run and return the approved actionable busy, rate-limit, and allowance outcomes. If any part is infeasible on the approved $0 topology, which exact acceptance criterion fails and which guardrail or hosting decision must reopen before parity gates are defined?

This ticket authorizes only the minimum protected prototype and account read-only inspection required to answer the question. It does not authorize a public or production deployment, paid-plan activation, production-domain changes, secret changes, or a fallback to the Mac, a tunnel, an LLM, or another host.

## Answer

No. The approved Public Admission Policy is not fully feasible on Vercel Hobby for $0. Current first-party Vercel Blob capabilities make the stateless identity, rate, and concurrency half feasible without a paid coordination dependency, but Vercel Hobby does not expose a sufficiently current, trustworthy application-readable Active CPU and Provisioned Memory usage signal. The approved rule therefore requires every public Query Run to fail closed with Allowance Pause. The application cannot pass its release gate on this topology as currently defined.

Detailed official-platform evidence is recorded in [Ticket 13: current Vercel Hobby platform facts](../evidence/13-vercel-official-platform-facts.md). The runnable state model and its behavior proof are recorded in the [Public Admission Policy throwaway prototype](../prototypes/public-admission-policy/README.md).

### Current merged application seam

The investigation used the current merged Query Recipe, Query Plan, and Query Run implementation, not the tracker branch's older application tree. The clean implementation worktree at commit `cc8f88b` has the same application tree as PR #19's merge commit `f77b1df` and current `origin/main` commit `f5f57c4`; current `origin/main` differs from `cc8f88b` only in `AGENTS.md`.

The merged Interface executes one Query Recipe through planning and synchronous Query Run completion in one `POST /api/query-runs` call. Its DuckDB lock, runtime cache, and Browser `pending` flag are process- or page-local. It has no Visitor identity, active-run ledger, cross-instance counter, allowance input, or busy/rate/allowance outcomes. The Browser owns local Query Run history and already preserves the prior result after a non-successful HTTP attempt, although actionable refusal data will require a separate attempt-outcome read model rather than replacing the completed Query Run.

The minimum future seam is therefore one server-owned Public Admission Policy call immediately before the existing Query Run Adapter. Query Recipe, Query Plan, immutable Query Run, DuckDB execution, and Coverage Report contracts do not need to change.

### Feasible criteria

| Criterion | Result | Proof and boundary |
| --- | --- | --- |
| Privacy-appropriate anonymous Visitor | Feasible | Issue a random opaque first-party `Secure`, `HttpOnly`, `SameSite` cookie and retain only a keyed one-way digest in shared admission state. This avoids making IP address or JA4 the product identity. Clearing or rotating the cookie creates a new anonymous Visitor; this remains a human-paced product limit, not account authentication or an anti-Sybil claim. |
| One running Query Run per Visitor | Feasible with Blob CAS | One private state object holds run leases keyed by Visitor digest. Each lease is derived from the successful admission attempt's current coordinator time and extends five seconds beyond the ten-second execution deadline. A cache-bypassing consistent read followed by an ETag `ifMatch` conditional write admits only one competing start. Expired leases recover capacity after an interrupted invocation. |
| Three starts per minute and twelve per hour per Visitor | Feasible with Blob CAS | The same atomic transition prunes timestamps outside the rolling hour, checks both rolling windows, and either appends the admitted start or returns the exact earliest retry time. Hobby WAF alone cannot express both limits: it supplies only one rate rule, no one-hour window, and region-local counters. |
| Four running Query Runs deployment-wide | Feasible with Blob CAS | The same transition counts all live leases and refuses a fifth with the earliest lease expiry. Vercel Functions' automatic scaling and process-local Python locks are not the authority. |
| Atomic combined decision | Feasible in principle | Private Blob now documents uncached consistent reads and conditional writes. Every allowance, Visitor-running, deployment-running, minute, and hour check must be evaluated and committed in one small JSON-object CAS. A precondition failure rereads and retries a bounded number of times; exhausted contention or Blob failure returns provider unavailable and never admits optimistically. |
| No paid coordination dependency | Feasible but tightly bounded | Vercel Blob is available within Hobby's included 1 GB storage, 10,000 simple operations, 2,000 advanced operations, and 10 GB transfer. At least one admit write and one release write cap the nominal proof shape below 1,000 completed runs per month before initialization, contention, cleanup, or failed-write accounting. Blob exhaustion is another fail-closed capacity boundary, not unlimited free coordination. No store was created because the independent allowance criterion already fails. |
| Preserve the last completed Query Run | Feasible | The Browser keeps `lastCompletedRun` separate from `attemptOutcome`; busy, rate, allowance, and provider refusals update only the latter. The coordinator stores leases and counters, never Query Run payloads. |
| Actionable outcomes | Feasible while application code can run | Visitor busy and deployment busy include the earliest live lease expiry. Minute and hour limits name the reached limit and exact retry time. Allowance Pause names an unavailable, stale, CPU-target, or memory-target signal without guessing. Bounded CAS failure returns provider unavailable. No outcome queues, retries, or redirects work elsewhere. |

The offline TDD prototype passes `18` focused checks for the pure transition, two independent stateless coordinator instances sharing CAS state, an allowance-update/admission race on that same CAS version, both rolling rate windows, both concurrency scopes, CPU and memory 70% thresholds, unavailable/stale/malformed usage, a retried lease that outlives the ten-second execution deadline, lease release, one-way Visitor identity, state-surfacing terminal frame, and last-completed Query Run preservation. Its TUI starts with the truthful production-equivalent state—provider usage unavailable and admission fail-closed—and permits an explicitly synthetic usage input only so the otherwise-feasible transitions can be inspected.

### Exact failed criterion

**Failed: obtain a sufficiently current and trustworthy Active CPU and Provisioned Memory usage signal that application code on Vercel Hobby can use at admission time.**

Hobby includes 4 Active CPU-hours and 360 GB-hours of Provisioned Memory, making the approved 70% targets 2.8 CPU-hours and 252 GB-hours. Vercel documents the dashboard for viewing account usage, but gives it no freshness guarantee or supported Hobby application feed. The billing endpoint is documented as Pro/Enterprise-only with one-day granularity. The CLI exposes only daily, weekly, or monthly breakdowns. Spend Management's every-few-minutes checks and webhook actions are Pro-only. An authenticated read-only check with Vercel CLI `56.3.1` against the Hobby scope returned `Costs not found (404)` for `vercel usage --format json`; it did not expose CPU or memory consumption.

Application-side request counting cannot substitute silently. Vercel bills Active CPU from executing CPU milliseconds and Provisioned Memory from allocated instance memory over runtime lifetime, including concurrency behavior; those values are also shared with other activity in the Hobby account. A local estimate would be a different guardrail, not the approved provider-reported 70% signal.

Consequently the fail-closed behavior is implementable but not useful: the allowance snapshot is absent or untrustworthy, so every start correctly returns Allowance Pause even when actual use may be low. Vercel's eventual hard pause at 100% cannot satisfy a proactive 70% gate, and application code cannot return a custom outcome after the provider has paused the deployment.

### Decision that must reopen

Before [Define parity and release gates](06-define-parity-and-release-gates.md) can be worked, one of these decisions must reopen explicitly:

1. **Allowance guardrail:** replace provider-reported account CPU/memory with a separately approved conservative application-owned budget, including any required account/project isolation, measurement model, reset rule, and lower safety margin; or
2. **Hosting decision:** select a still-approved topology that exposes a supported sufficiently fresh usage signal or pause webhook to application admission.

That reopened choice is the new frontier [Choose the Public Allowance Pause authority](14-choose-public-allowance-pause-authority.md), which now blocks parity-gate definition.

This answer does not choose either change, activate Vercel Pro or another paid dependency, reactivate Cloudflare, or weaken the 70% limits. If the allowance decision reopens, a final protected proof must still verify Python/raw-HTTP compatibility for Blob `ifMatch` plus uncached reads, the clock source used for rolling windows and lease expiry, and actual Blob operation accounting under contention.

No deployment, Blob store, account setting, domain, secret, paid feature, Mac, tunnel, LLM, or alternate host was created or changed. `CONTEXT.md` is unchanged because Public Admission Policy, Busy Rejection, and Allowance Pause were already settled domain terms; this ticket settles platform feasibility, not new ubiquitous language.
