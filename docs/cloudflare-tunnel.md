# Retired Cloudflare Tunnel Deployment

The Mac-backed Cloudflare Tunnel design is retired. Do not use it for previews,
production, rollback, or emergency fallback.

Ground Ball now uses one Svelte/FastAPI application. The hosted public mode is a
self-contained zero-Mac container with packaged DuckDB/Lahman data and no LLM
route. `GROUNDBALL_PUBLIC_DEMO=1` is enforced server-side; the browser cannot
select local execution.

The prior Tunnel, Pages Function proxy, visitor token, origin proxy, LaunchAgent,
and LM Studio routing instructions were intentionally removed because they
conflict with the public-demo boundary. The bounded private Vercel preview is the
current proof target. A paid Cloudflare Container proof remains postponed unless
the stateless Vercel shape fails and Stewart explicitly approves that separate
work.
