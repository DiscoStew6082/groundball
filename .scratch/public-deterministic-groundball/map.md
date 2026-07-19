# Find the Way to a Zero-Mac Interactive Ground Ball Demo

Label: `wayfinder:map`

## Destination

Reach a reviewed, proven zero-Mac Ground Ball application that preserves the deterministic Python/DuckDB behavior behind one stateless Svelte/FastAPI interface, preferring a $0 Vercel Hobby deployment and retaining Cloudflare Containers as a conditional fallback.

## Notes

- Domain: Ground Ball is a local-first historical MLB almanac. One Svelte application serves both local and hosted use; the server exposes local LLM, Architecture Explorer, and developer capabilities only in local mode. The public deployment packages the Published Query Catalog, the clean Query Recipe to Query Plan to Query Run path, the DuckDB runtime, Lahman data, and only the compact reviewed Retrosheet projections required by separately supported deterministic event routes.
- Consult the `prototype`, `codebase-design`, `domain-modeling`, `tdd`, and `browser-tool-call-hygiene` skills while working this map. Consult `cloudflare` and `wrangler` only if the Cloudflare fallback is activated.
- Refer to Modules, Interfaces, Implementations, Seams, and Adapters using the vocabulary in `CONTEXT.md`.
- Ask HITL questions one at a time and include a recommended answer.
- Preserve the website's dark, window-framed visual language. Ground Ball should look like an application launched from the Start menu, while its interior may be redesigned freely.
- The existing Mac LaunchAgents and tunnel are disabled. They must never be used as a fallback during design, preview, cutover, or rollback.
- PR #19 completed the clean Queryable Ground Ball cutover. Remaining tickets must build on the Published Query Catalog, Query Recipe, Query Plan, Query Run, and Coverage Report contracts; they must not restore legacy request models, compatibility Adapters, or fallback query lanes.
- Hosting budget: Vercel Hobby at $0 is the first proof target. Cloudflare Containers on Workers Paid at approximately $5 per month is the fallback. Hugging Face PRO, Vercel PRO, Google Cloud, and other paid hosting are not approved.
- Vercel Hobby is acceptable only for this personal, non-commercial public demo. If the product becomes commercial, hosting must be decided again rather than silently violating Hobby terms.
- The stateless Svelte/FastAPI Vercel proof and the Queryable Ground Ball implementation are complete. This map now authorizes only the remaining planning and bounded prototypes needed to decide the website-frame integration, packaged release, public guardrails, parity gates, and cutover proof. It does not authorize a public or production deployment, paid-plan activation, production-domain changes, secret changes, tunnel deletion, or other production mutations.

## Decisions so far

- [Approve the zero-Mac deterministic Ground Ball public demo contract](issues/01-approve-zero-mac-public-demo-contract.md) — Initially selected the existing deterministic Python/Gradio/DuckDB behavior for a zero-Mac packaged runtime; the later stateless Svelte/FastAPI proof and clean Query contracts supersede that historical application shape while preserving the no-Mac/no-LLM boundary.
- [Confirm current public container hosting constraints](issues/09-confirm-current-public-container-hosting-constraints.md) — Vercel Hobby now supports OCI containers within hard free limits and personal-use terms; Cloudflare Containers remain the paid, scale-to-zero fallback, while Hugging Face requires a PRO subscription for this app shape.
- [Provision the Vercel Hobby proof target](issues/10-provision-vercel-hobby-proof-target.md) — The CLI is authenticated as `discostew6082`; the verified empty `discostew6082s-projects/ground-ball` project is reserved for the bounded compatibility proof, with no deployment, Git integration, domain, or paid usage enabled.
- [Prove Vercel Hobby container fit](issues/02-prove-vercel-hobby-container-fit.md) — Vercel built and protected the 278.29 MB deterministic container and passed cold, sequential, fail-closed, data-integrity, and scale-to-zero checks, but concurrent Gradio sessions repeatedly lost in-memory queue/SSE state across stateless instances. That result rejects the historical Gradio Adapter only; the 2026-07-17 decision supersedes its Cloudflare activation by testing one stateless Svelte/FastAPI request per query first.
- [Prove the stateless Svelte/FastAPI Vercel fit](issues/12-prove-stateless-svelte-fastapi-vercel-fit.md) — The unified 132.86 MB protected preview passed the server-enforced zero-Mac boundary, deterministic cold/default/fail-closed checks, two repeated `8/8 + 4/4` concurrent waves, packaged UI and export contracts, and final-preview cleanup. Vercel Hobby is the selected application shape; Cloudflare is ruled out of the current route and returns only as a fresh effort if this evidence is invalidated.
- [Prototype the website-framed hosted Ground Ball experience](issues/03-prototype-groundball-app-interior.md) — Keep the approved merged dark Svelte/FastAPI shell unchanged for local and hosted use; route discovered query defects through the canonical Query contracts and later parity proof rather than creating another interface or compatibility lane.

## Not yet specified

None currently. The remaining route is precise enough to live entirely in open tickets.

## Out of scope

- Performing a public production deployment, website cutover, or production-domain change; those mutations require the remaining release and cutover decisions plus Stewart's explicit approval.
- [Prove session-affine Cloudflare Container fit](issues/11-prove-session-affine-cloudflare-container-fit.md) — Ruled out of the current route because the stateless Vercel proof passed; if future evidence invalidates that result, Cloudflare requires a fresh effort and Stewart's explicit Workers Paid approval.
- [The Worker/D1 runtime investigation](issues/08-confirm-current-cloudflare-runtime-constraints.md) and reimplementation of the proven deterministic Python query engine as a TypeScript Worker/D1 system; hosting the merged Svelte/FastAPI/DuckDB application is the narrower route.
- Paid Hugging Face, Vercel PRO, Google Cloud, or an unbounded pay-as-you-go host.
- Public LLM inference, Workers AI, LM Studio access, or narrative generation.
- Uploading the full raw Retrosheet corpus; only compact projections required by supported deterministic queries are in scope.
- Authentication, accounts, or server-side query history for the public demo.
- Any tunnel, origin proxy, or Mac-backed emergency fallback.
- Retiring LLM support from the existing local Python application.
