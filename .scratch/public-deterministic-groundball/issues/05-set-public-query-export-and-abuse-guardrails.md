# Set public query, export, and abuse guardrails

Type: `grilling`
Status: resolved
Blocked by: [Choose the packaged deterministic data release](04-choose-packaged-data-release.md)

## Question

What concrete request, execution-time, result, export, burst, sustained-use, concurrency, and monthly-allowance limits protect the hosted Svelte/FastAPI/DuckDB application without making normal exploration frustrating, prevent any automatic paid upgrade, and define honest user-visible behavior when Vercel pauses or rejects work?

## Answer

The public Ground Ball application supports anonymous, human-paced exploration only. Automated scraping, bulk API use, hidden request queues, background retries, silent truncation, compatibility fallbacks, Mac or LLM fallback, paid-plan activation, and automatic paid usage are outside its public contract.

One server-owned **Public Admission Policy** decides whether a public Query Run may start before DuckDB execution. It must enforce every limit below across both natural-language questions and edited Query Recipes. A request that cannot be admitted fails closed with an honest, actionable outcome while the browser preserves the visitor's last completed result.

### Request and admission limits

- A natural-language question is at most 500 characters.
- A public query request body is at most 16 KiB (16,384 bytes), including an edited structured Query Recipe.
- One visitor may have at most one Query Run executing at a time.
- The public deployment may have at most four Query Runs executing at a time across all instances. Deployment-wide enforcement must be proven without adding a paid dependency; inability to enforce the limit fails the release gate.
- A visitor may start at most three Query Runs in any minute and twelve in any hour.
- Capacity does not create a server-side queue. A request rejected because the visitor or deployment concurrency limit is occupied receives a retryable **Busy Rejection** with a truthful retry interval.
- A request rejected by the burst or sustained-use limit identifies the limit reached and the exact time at which work may be attempted again.

These are product limits, not an invitation to rotate identifiers. The public demo does not support automation or bulk access even when a caller could distribute requests across clients.

This decision defines the limits applied to a **Visitor** but does not guess how an anonymous visitor is identified across stateless instances. [Prove stateless Public Admission Policy feasibility](13-prove-stateless-public-admission-policy-feasibility.md) must choose and prove a privacy-appropriate identity mechanism, distributed enforcement, and usage signal without adding a paid dependency before release gates are defined.

### Execution and interactive results

- An admitted Query Run has a ten-second end-to-end deadline. Timeout returns an unavailable outcome that asks the visitor to narrow the question; it is never reported as no data or unsupported.
- Interactive results start at 25 rows. A visitor may choose 50 or 100 rows, and 100 is the hard maximum for one page.
- Every page reports both returned row count and total matched row count. Pagination remains available within the same published Query Recipe; the first page is never presented as the whole result when more rows matched.

### Complete exports

The **Export Ceiling** is the first of these limits reached:

- 3,000 rows;
- 1,500,000 bytes of downloadable CSV or JSON content; or
- 3,500,000 bytes for the complete serialized HTTP response, including the Query Recipe, Query Plan, rows, evidence, verification, and export content.

An export is complete or it is refused. Ground Ball must never silently truncate an export. When the matched result exceeds any ceiling, the response reports the total matched rows, names the ceiling that was exceeded, and suggests filters that can produce a complete export.

These byte and row limits are grounded in Vercel Hobby's [4.5 MB response-body limit](https://vercel.com/docs/functions/limitations#request-body-size) and the current Query Run Interface, which includes exported rows both as structured `rows` and as downloadable `export.content`. Measurement against the packaged data at implementation commit `cc8f88b` found that an all-column 5,000-row People JSON minimal response envelope was approximately 5.36 MB and an equivalent Pitching envelope was approximately 4.18 MB before full plan and evidence overhead. The equivalent 3,000-row People envelope was approximately 3.21 MB before that overhead, including about 1.53 MB of downloadable content. The release gate must repeat this measurement against the final Release Bundle and generated Interface payload; it may lower a ceiling if needed but may not raise one without a new product decision.

### Monthly free-plan allowance

The provider-reported 70% CPU and memory authority selected below is superseded by [Choose the Public Allowance Pause authority](14-choose-public-allowance-pause-authority.md). That later decision owns the replacement allowance rule; every other guardrail in this answer remains in force.

Vercel Hobby currently includes 4 active CPU-hours, 360 GB-hours of provisioned memory, and 1,000,000 function invocations in its free usage window. Hobby cannot buy on-demand overages and pauses projects after an included allowance is exhausted. The provider facts and official sources remain recorded in [Public container hosting constraints for Ground Ball](../../../research/public-container-hosting-constraints.md).

Ground Ball enters an **Allowance Pause** and stops admitting new Query Runs at 70% of either the CPU or memory allowance: 2.8 active CPU-hours or 252 GB-hours of provisioned memory. This self-imposed safety target is intended to leave 30% headroom for an unavailable explanation and bounded release verification; it cannot reserve account-level capacity or guarantee that Vercel remains available when other traffic or projects consume the shared allowance. No production configuration may activate Vercel Pro, a paid add-on, on-demand usage, or an automatic upgrade.

The release gate must prove how current provider usage becomes an admission input and must test the pause before public promotion. If usage is unavailable or stale enough that the 70% rule cannot be trusted, query admission fails closed rather than guessing. Vercel's one-million-invocation cap and other account-level allowances remain hard provider limits, but CPU and memory are the proactive Ground Ball pause signals selected for this release.

### Honest refusal and provider behavior

The public Interface distinguishes at least these outcomes: busy, visitor rate-limited, execution timed out, export too large, allowance paused, provider unavailable, unsupported question, and successful no-data result. Each refusal states what happened and either when to retry or how to narrow the request. The browser retains the last completed Query Run and never replaces it with a failed attempt.

The application cannot promise a custom response after Vercel itself has hard-paused or rejected the deployment. The 70% Allowance Pause exists to avoid that state. When an edge or provider rejection still occurs, the browser must label it as provider unavailability rather than converting it to unsupported, no data, or a generic successful response. No refusal may trigger a hidden retry, alternate runtime, tunnel, Mac access, LLM call, paid host, or paid-plan change.

Feasibility proof remains owned by [Prove stateless Public Admission Policy feasibility](13-prove-stateless-public-admission-policy-feasibility.md). Final acceptance and cutover proof remain owned by [Define parity and release gates](06-define-parity-and-release-gates.md) and [Define preview cutover and zero-Mac proof](07-define-preview-cutover-and-zero-mac-proof.md). This decision does not authorize deployment or production changes.
