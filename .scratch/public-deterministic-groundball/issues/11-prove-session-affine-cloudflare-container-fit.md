# Prove session-affine Cloudflare Container fit

Type: `prototype`
Status: resolved
Blocked by: [Prove the stateless Svelte/FastAPI Vercel fit](12-prove-stateless-svelte-fastapi-vercel-fit.md)

## Question

Only if the stateless Svelte/FastAPI Vercel proof fails, and after Stewart explicitly approves activating the approximately $5/month Cloudflare Workers Paid plan, does a private Cloudflare Container proof provide a better zero-Mac runtime fit for the packaged deterministic Python/DuckDB application?

This proof is postponed while the stateless Vercel application shape is implemented and tested. If activated later, it must use a current `wrangler.jsonc`, a recent compatibility date, `startAndWaitForPorts()`, `container.fetch(request)`, `enableInternet = false`, a deliberate `sleepAfter`, and a bounded `max_instances`. It must reuse the verified immutable data checks, require no runtime download, and record explicit pass/fail evidence for image build, cold start, default query, unsupported and LLM-dependent fail-closed behavior, sequential and concurrent requests, browser embedding, sleep/wake recovery, resource usage, and teardown or retention of every paid proof resource.

This ticket authorizes no Cloudflare account upgrade, paid resource, public route, domain change, DNS change, tunnel, or deployment until Stewart gives the one-time paid-plan approval in the live ticket exchange.

## Answer

Ruled out of the current route on 2026-07-18 because [Prove the stateless Svelte/FastAPI Vercel fit](12-prove-stateless-svelte-fastapi-vercel-fit.md) passed and selected Vercel Hobby. The activation condition for this Cloudflare proof is therefore false, and no Cloudflare plan or resource is authorized.

If future evidence invalidates the stateless Vercel result, redraw the scope and create a fresh proof ticket that preserves this ticket's technical constraints. That future effort still requires Stewart's explicit approval before enabling Workers Paid or mutating any Cloudflare resource.
