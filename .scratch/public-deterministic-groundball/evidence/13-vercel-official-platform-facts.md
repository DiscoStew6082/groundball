# Ticket 13: current Vercel Hobby platform facts

Research date: 2026-07-18

Scope: first-party Vercel documentation only. No deployment, store creation, account mutation, paid feature, secret change, or third-party service was used.

## Bottom line

The approved policy is **not fully feasible on the documented Vercel Hobby $0 topology**.

Current Vercel Blob capabilities make the admission-coordination half plausible without a paid dependency: one private state blob can be read consistently and updated with an ETag compare-and-swap (CAS), so every stateless instance can make the one-Visitor, per-Visitor rate, and deployment-wide running-count decision against one atomic state transition. This is an application coordinator, not a Vercel Function concurrency limit or WAF guarantee.

The exact failed criterion is the **sufficiently current, trustworthy provider CPU and memory usage signal**. Vercel documents the account dashboard as the place to view Hobby usage, but documents no freshness guarantee or supported application-readable Hobby feed for current Active CPU and Provisioned Memory consumption. The public billing API is documented as Pro/Enterprise-only and has one-day granularity; the CLI also documents one-day granularity. Configurable spend actions/webhooks are Pro-only. Therefore an application cannot prove that its provider-reported account usage is below 2.8 active CPU-hours and 252 GB-hours at admission time. Under the approved rule, a missing or untrustworthy signal must produce Allowance Pause, so the public release would remain fail-closed.

This failure requires reopening one of these decisions before parity gates are defined:

1. the **hosting decision**, to provide a plan/topology with a supported sufficiently fresh provider-usage feed or webhook; or
2. the **allowance guardrail**, to replace provider-reported account CPU/memory with a separately approved conservative application-owned budget and any necessary account-isolation rule.

The approved 70% values should not be weakened or inferred from request counts silently.

## Criterion-by-criterion findings

| Criterion | Finding | Official evidence and implication |
| --- | --- | --- |
| Privacy-appropriate anonymous Visitor | **Feasible at the application layer** | Vercel Functions can read request cookies, and Vercel documents personalized responses that vary by cookie as private-cache responses. A server-generated random opaque identifier in a `Secure`, `HttpOnly`, `SameSite` cookie avoids using the public IP or JA4 fingerprint as the product identity. Store only a one-way digest of the opaque value in admission state. Cookie deletion, another browser/profile, or a user rotating the value creates a new Visitor; this is an anonymous human-paced limit, not strong identity or anti-Sybil authentication. Sources: [Node.js request cookie helper](https://vercel.com/docs/functions/runtimes/node-js#node.js-helpers), [personalized responses that vary by cookie](https://vercel.com/docs/caching/cache-control-headers#recommended-cache-control-directives), [Vercel notes that public IP may be personal information](https://vercel.com/docs/query#manage-ip-address-visibility-for-query). |
| One running Query Run per Visitor | **Feasible in a Blob CAS state transition, not platform-enforced** | Include active leases keyed by the Visitor digest in one private JSON blob. A consistent read plus ETag-conditional write means only one concurrent admission can add a lease for that Visitor. Expired leases must be pruned so a crashed invocation does not block forever. [Vercel Blob conditional writes](https://vercel.com/docs/vercel-blob#conditional-writes) explicitly describe `ifMatch` optimistic concurrency and precondition failure when another process writes first. |
| Three starts/minute and twelve/hour per Visitor | **Feasible in the same Blob CAS state transition** | Keep only the Visitor's last hour of admitted-start timestamps. Under CAS, prune old timestamps, count the 60-second and 60-minute windows, return the exact earliest retry time when either limit is full, or append the start together with the running lease. The WAF alone does **not** implement the approved pair: Hobby gets one fixed-window rule, a maximum ten-minute window, and counters are per-region. The SDK can key a check by an application identity, but it still uses the configured WAF rule. Sources: [WAF rate-limit limits and per-region counters](https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting#limits), [`rateLimitKey` in the WAF SDK](https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting-sdk#use-the-ratelimitkey-in-code). |
| No more than four running Query Runs across all stateless instances | **Feasible in the same Blob CAS state transition** | Count unexpired active leases in the same state object and append a fifth only if the count is below four. CAS serializes competing admissions. Vercel Functions themselves are not a four-run guard: Vercel documents automatic scaling up to 30,000 concurrent executions on Hobby/Pro. [Function limits](https://vercel.com/docs/functions/limitations) and [concurrency scaling](https://vercel.com/docs/functions/concurrency-scaling). |
| Atomic admission across all limits | **Feasible in principle with one state object** | The Visitor's two rate windows, Visitor running lease, global running count, allowance snapshot/status, and new run lease must be checked and changed in **one** conditional write. Split blobs or independent WAF/Queue checks would not make the combined decision atomic. Private Blob now supports bypassing cache for a read guaranteed to reflect the latest write with `get(..., {useCache: false})`; the resulting ETag is the CAS precondition. Sources: [consistent private Blob reads, released 2026-07-14](https://vercel.com/changelog/vercel-blob-now-supports-consistent-reads-on-private-storage), [conditional writes](https://vercel.com/docs/vercel-blob#conditional-writes). |
| No paid coordination dependency | **Feasible but tightly usage-bounded** | Blob is first-party and available on Hobby. Hobby includes 1 GB storage, 10,000 simple operations, 2,000 advanced operations, and 10 GB transfer per month. A normal completed run needs at least two state writes (admit and release), so the nominal ceiling is at most 1,000 completed start/release pairs before initialization, contention retries, cleanup, or any other Blob writes. Vercel says Blob becomes inaccessible after Hobby limits are exceeded. This introduces a second fail-closed capacity boundary that release guardrails must acknowledge; it is not unlimited free coordination. Sources: [Blob pricing and included operations](https://vercel.com/docs/vercel-blob/usage-and-pricing#pricing), [Hobby Blob hard-stop behavior](https://vercel.com/docs/vercel-blob/usage-and-pricing#hobby), [Hobby cannot purchase additional usage](https://vercel.com/pricing). New Blob connections use short-lived, automatically rotated Vercel OIDC tokens, so the mechanism need not add a long-lived application secret: [Blob OIDC authentication](https://vercel.com/changelog/vercel-blob-now-supports-oidc-authentication). |
| Current/trustworthy CPU and memory usage | **Failed** | Hobby includes 4 Active CPU-hours and 360 GB-hours of Provisioned Memory. The Usage dashboard shows account/project allotments, but its documentation gives no freshness SLA or application feed. The new billing charges endpoint is documented with one-day granularity, and Vercel's integration scope reference says Billing is only available to Pro and Enterprise teams. `vercel usage` likewise supports daily/weekly/monthly breakdown with one-day data granularity. Sources: [Hobby allowances](https://vercel.com/docs/plans/hobby), [Usage dashboard](https://vercel.com/docs/pricing/manage-and-optimize-usage#viewing-usage), [billing API granularity](https://vercel.com/changelog/access-billing-usage-cost-data-api), [billing API plan availability](https://vercel.com/docs/integrations/create-integration/vercel-api-integrations#billing), [`vercel usage` granularity](https://vercel.com/docs/cli/usage#breakdown). A local request counter is not equivalent to Vercel's meters: Active CPU counts actual executing CPU milliseconds, while Provisioned Memory is allocated memory over the instance lifetime until the last in-flight request completes and can serve concurrent requests. [Fluid Compute resource definitions](https://vercel.com/docs/functions/usage-and-pricing#resource-details). |
| Fail-closed Allowance Pause at 70% | **Fail-closed behavior is implementable; a useful 70% gate is not** | The CAS state can require a provider snapshot with `as_of`, CPU-hours, memory GB-hours, and a maximum acceptable age, and return `allowance_paused` if absent, stale, malformed, at or above 2.8 CPU-hours, or at or above 252 GB-hours. With the documented Hobby signals, that condition remains paused because a trustworthy current snapshot cannot be supplied. Vercel Spend Management checks usage every few minutes and can call a webhook, but is available only on Pro. Hobby is automatically paused only after included limits are exceeded. Sources: [Spend Management plan and check frequency](https://vercel.com/docs/spend-management#how-vercel-checks-your-spend-amount), [Hobby pause at included limits](https://vercel.com/docs/plans#what-happens-when-i-reach-100-usage). |
| Preserve the last completed Query Run | **Feasible and independent of shared admission state** | A refusal must not overwrite browser result state. Keep the last completed Query Run in the existing client read model and update it only on `completed`; render busy, rate, allowance, and provider outcomes separately. The Blob coordinator should contain leases/counters only, not the result payload. Vercel supports private, cookie-varying responses, so the platform does not force result replacement or shared caching. [Recommended private cache directive for personalized/cookie responses](https://vercel.com/docs/caching/cache-control-headers#recommended-cache-control-directives). |
| Actionable busy, rate-limit, and allowance outcomes | **Feasible while the Function is invoked** | The application-owned admission decision can return structured outcomes: `busy_visitor` or `busy_deployment` with the earliest live lease expiry; `rate_limited_minute` or `rate_limited_hour` with the earliest expiring admitted timestamp; `allowance_paused` with a non-guessing explanation; and `provider_unavailable` after bounded CAS contention or Blob failure. The WAF SDK also demonstrates returning an application JSON 429. [WAF SDK response example](https://vercel.com/docs/vercel-firewall/vercel-waf/rate-limiting-sdk#configure-rate-limiting-in-code). Once Vercel itself pauses a deployment, visitors receive Vercel's `503 DEPLOYMENT_PAUSED`, so application code cannot promise a custom response after the hard stop. [Paused deployment behavior](https://vercel.com/docs/spend-management#pausing-projects). |

## Minimal coordinator shape supported by the platform facts

The smallest credible proof uses one small private Blob object, not Edge Config, Runtime Cache, process memory, or a hidden work queue:

```json
{
  "schema_version": 1,
  "allowance": {
    "as_of": "provider timestamp",
    "active_cpu_hours": 0,
    "provisioned_memory_gb_hours": 0,
    "source": "supported provider signal"
  },
  "running": [
    {
      "run_id": "opaque id",
      "visitor_digest": "one-way digest",
      "lease_expires_at": "timestamp after the ten-second run deadline"
    }
  ],
  "starts_by_visitor": {
    "visitor_digest": ["admitted timestamp within the last hour"]
  }
}
```

Admission algorithm:

1. Read the private blob with cache bypass and retain its ETag.
2. Prune expired run leases and start timestamps older than one hour.
3. Reject fail-closed if the allowance snapshot is absent, stale, invalid, or at/above either approved 70% threshold.
4. Reject with exact retry data if the Visitor already has a live lease, either rate window is full, or four live deployment leases remain.
5. Otherwise append the start timestamp and run lease in one state update.
6. Write with `ifMatch=<read ETag>`. On precondition failure, reread and retry a small bounded number of times; after the bound, return `provider_unavailable`, never admit optimistically.
7. On completion, CAS-remove the run lease. A lease longer than the ten-second end-to-end deadline recovers capacity after a crashed/timed-out invocation without expiring while a valid Query Run can still execute.

This design demonstrates why WAF, Queue push concurrency, and in-process locks are not the authoritative admission mechanism:

- Hobby WAF cannot express both approved time windows and is region-scoped.
- Vercel Queue push concurrency queues accepted work; the approved policy requires immediate Busy Rejection and no hidden queue. Queues are nevertheless included on Hobby and provide durable leases, but they are unnecessary once Blob CAS is available. [Queue semantics](https://vercel.com/docs/queues), [Queue Hobby operations and concurrency](https://vercel.com/docs/queues/pricing).
- Vercel Functions reuse and autoscale instances; a Python lock or process-global counter protects only one live instance and disappears at scale-to-zero.
- Edge Config is documented for read-often/change-rarely configuration and Hobby includes only 100 writes, making it the wrong per-run state primitive. [Storage product guidance](https://vercel.com/docs/storage#edge-config), [Hobby included usage](https://vercel.com/docs/plans/hobby).

## Remaining uncertainties requiring a protected proof if the allowance decision reopens

- The current general Blob docs and TypeScript examples document `ifMatch` and `useCache: false`. The Python section of the SDK page still shows an older signature that does not list the new cache-bypass option and inconsistently omits `if_match` even though the page's error section references conditional writes. The current FastAPI runtime therefore needs a protected SDK or raw-HTTP compatibility check before calling the coordinator implementation proven.
- Vercel publishes no clock-synchronization bound for Function instances. A prototype should use one documented/provider-derived time source if available, or record the small clock-skew assumption explicitly rather than claiming mathematically exact rolling windows across unsynchronized clocks.
- The docs do not state whether failed ETag precondition attempts consume an advanced-operation allowance. Capacity planning should conservatively count every attempted CAS write until measured otherwise.
- Blob CAS settles coordination feasibility only. It does not repair the missing current provider allowance signal, which independently fails the approved release criterion.
