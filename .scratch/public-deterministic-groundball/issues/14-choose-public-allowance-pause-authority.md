# Choose the Public Allowance Pause authority

Type: `grilling`
Status: resolved
Blocked by: [Prove stateless Public Admission Policy feasibility](13-prove-stateless-public-admission-policy-feasibility.md)

## Question

Because Vercel Hobby cannot supply the current, trustworthy provider-reported Active CPU and Provisioned Memory feed required by the approved 70% Allowance Pause, which explicit decision should replace that infeasible release condition before parity gates are defined: revise the allowance guardrail around a conservative application-owned budget with the necessary account/project isolation, measurement model, reset rule, and safety margin; or reopen the $0 hosting decision for a topology with a supported sufficiently fresh usage signal? The decision must not silently weaken the approved limits or authorize a paid plan, paid add-on, Mac, tunnel, LLM, alternate production host, public deployment, domain change, or secret change.

## Answer

Keep the proven Vercel Hobby application shape and replace the infeasible provider-reported 70% CPU and memory gate with a deliberately conservative application-owned monthly start budget. Do not reopen hosting.

This is an explicit change of allowance authority, not a claim that Query Run counts estimate Vercel's Active CPU or Provisioned Memory meters. Those provider values remain unavailable to Hobby application code. The application-owned budget is instead a smaller, auditable release condition chosen to leave substantial room beneath the free-plan allowances.

### Monthly budget

- Admit at most **100 public Query Runs per UTC calendar month** across the deployment.
- Charge one unit atomically when the Public Admission Policy admits a Query Run, before deterministic execution begins.
- A charged start is never refunded, including when execution times out, fails, or its invocation is interrupted.
- The existing ten-second end-to-end deadline therefore bounds the admitted execution represented by one full monthly budget to at most 1,000 seconds of Query Run wall time. This is a conservative application bound, not a reconstruction of provider billing.
- Rejected admission attempts do not become Query Runs and do not consume a start unit. They remain governed by the already-approved Visitor, concurrency, rate, request-size, and fail-closed rules. Provider usage from page delivery, refusals, coordination, cold starts, and other runtime overhead remains real and must not be represented as covered by the start count.

The monthly count belongs in the same versioned, server-owned coordination state as the Visitor rate history and live Query Run leases. Admission checks the period and remaining count and, when successful, increments the count and creates the run lease in the same compare-and-swap transition. Competing stateless instances must not admit a 101st start.

### Reset and failure rules

- Each budget period begins at `00:00:00 UTC` on the first day of a calendar month.
- The first partial public month still receives no more than 100 starts.
- Unused starts never roll over.
- No operator, deployment, retry, state deletion, or application restart may reset or refund the counter manually.
- At 100 charged starts, the Public Admission Policy returns Allowance Pause with the next UTC reset time and preserves the Browser's last completed Query Run.
- Missing, malformed, contradictory, or out-of-period budget state fails closed as Allowance Pause rather than reconstructing or guessing a count.
- An unavailable coordination store or exhausted bounded compare-and-swap retry returns Provider Unavailable, as already decided, and never admits optimistically.

### Hobby-scope isolation

While the public Ground Ball deployment is live, `discostew6082s-projects` must be a Ground Ball-only active Hobby scope: the one public Ground Ball deployment may remain active, but no other active deployment or automated preview build may share the scope. Bounded preview and parity proof may occur before promotion, but every other retained proof or preview deployment must be removed before the public cutover gate passes.

This isolation is a release condition, not an account mutation authorized here. If the scope cannot satisfy it, public promotion stops and the allowance or hosting decision must reopen; the application-owned counter must not be presented as protecting usage consumed elsewhere.

### Consequences for the remaining route

[Set public query, export, and abuse guardrails](05-set-public-query-export-and-abuse-guardrails.md) remains authoritative for every request, Visitor, concurrency, execution, result, export, and refusal rule except its provider-reported 70% CPU and memory admission condition, which this answer supersedes.

[Define parity and release gates](06-define-parity-and-release-gates.md) must require proof that the monthly count is atomic across stateless instances; the 101st start is refused; timeouts and failures do not refund units; UTC reset, first-partial-month, no-rollover, missing-state, malformed-state, and coordination-failure behavior are correct; the last completed Query Run survives Allowance Pause; the Hobby scope satisfies the isolation rule; and actual Vercel Blob operation accounting plus Python or raw-HTTP conditional-write compatibility remain inside the approved free topology.

The later gate must also state the residual truth: an application-owned start budget cannot guarantee that Vercel will not pause the project because non-Query traffic, platform overhead, or provider accounting remains outside the counter. If Vercel does reject or pause the deployment, Ground Ball reports Provider Unavailable wherever application code can still respond and never falls back to a paid plan, another host, the Mac, a tunnel, or an LLM.

This decision changes no previously approved per-Visitor, concurrency, rate, timeout, result, export, or honest-refusal limit. It authorizes no implementation, deployment, public promotion, account or project change, domain change, secret change, paid feature, Mac, tunnel, LLM, or alternate host. `CONTEXT.md` needs no change: its existing Allowance Pause definition already describes a self-imposed free-plan safety target without claiming reserved provider capacity.
