# Find the Way to a Zero-Mac Interactive Ground Ball Demo

Label: `wayfinder:map`

## Destination

Reach an implementation-ready, reviewed decision set for a genuinely interactive public Ground Ball application that deploys the existing deterministic Python/Gradio/DuckDB behavior to a zero-Mac public runtime, preferring a $0 Vercel Hobby deployment and retaining Cloudflare Containers as the bounded $5 fallback.

## Notes

- Domain: Ground Ball is a local-first historical MLB almanac. The public deployment should package the proven Python router, Gradio application, DuckDB query path, Lahman data, and only the compact reviewed Retrosheet projections needed by supported deterministic routes.
- Consult the `prototype`, `codebase-design`, `domain-modeling`, `tdd`, and `browser-tool-call-hygiene` skills while working this map. Consult `cloudflare` and `wrangler` only if the Cloudflare fallback is activated.
- Refer to Modules, Interfaces, Implementations, Seams, and Adapters using the vocabulary in `CONTEXT.md`.
- Ask HITL questions one at a time and include a recommended answer.
- Preserve the website's dark, window-framed visual language. Ground Ball should look like an application launched from the Start menu, while its interior may be redesigned freely.
- The existing Mac LaunchAgents and tunnel are disabled. They must never be used as a fallback during design, preview, cutover, or rollback.
- Hosting budget: Vercel Hobby at $0 is the first proof target. Cloudflare Containers on Workers Paid at approximately $5 per month is the fallback. Hugging Face PRO, Vercel PRO, Google Cloud, and other paid hosting are not approved.
- Vercel Hobby is acceptable only for this personal, non-commercial public demo. If the product becomes commercial, hosting must be decided again rather than silently violating Hobby terms.
- This map plans decisions. It authorizes only the empty Vercel Hobby account/project setup and bounded private preview deployment required to resolve the named task and prototype tickets. It does not authorize a public or production deployment, paid-plan activation, production-domain changes, secret changes, tunnel deletion, or other production mutations.

## Decisions so far

- [Approve the zero-Mac deterministic Ground Ball public demo contract](issues/01-approve-zero-mac-public-demo-contract.md) — Preserve the existing deterministic Python/Gradio/DuckDB behavior in a packaged public runtime, use Vercel Hobby as the $0 proof target, retain Cloudflare Containers as the $5 fallback, and expose no Mac or LLM route.
- [Confirm current public container hosting constraints](issues/09-confirm-current-public-container-hosting-constraints.md) — Vercel Hobby now supports OCI containers within hard free limits and personal-use terms; Cloudflare Containers remain the paid, scale-to-zero fallback, while Hugging Face requires a PRO subscription for this app shape.
- [Provision the Vercel Hobby proof target](issues/10-provision-vercel-hobby-proof-target.md) — The CLI is authenticated as `discostew6082`; the verified empty `discostew6082s-projects/ground-ball` project is reserved for the bounded compatibility proof, with no deployment, Git integration, domain, or paid usage enabled.
- [Prove Vercel Hobby container fit](issues/02-prove-vercel-hobby-container-fit.md) — Vercel built and protected the 278.29 MB deterministic container and passed cold, sequential, fail-closed, data-integrity, and scale-to-zero checks, but concurrent Gradio sessions repeatedly lost in-memory queue/SSE state across stateless instances. Vercel fails the current-app compatibility proof, so the Cloudflare Container fallback is activated.

## Not yet specified

- The implementation slices and commit sequence can be specified only after the Cloudflare Container proof, packaged data release, public guardrails, hosted parity gates, app prototype, and cutover proof are resolved.
- [Prove session-affine Cloudflare Container fit](issues/11-prove-session-affine-cloudflare-container-fit.md) is now the required host proof. It cannot claim or mutate paid Cloudflare resources until Stewart explicitly approves the Workers Paid activation.

## Out of scope

- Implementing or deploying a production container, website integration, or redesigned UI while this map is still finding the way. The bounded private Cloudflare compatibility proof in ticket 11 enters scope only after Stewart explicitly approves the paid-plan activation.
- [The Worker/D1 runtime investigation](issues/08-confirm-current-cloudflare-runtime-constraints.md) and reimplementation of the proven deterministic Python query engine as a TypeScript Worker/D1 system; hosting the existing application is the narrower route.
- Paid Hugging Face, Vercel PRO, Google Cloud, or an unbounded pay-as-you-go host.
- Public LLM inference, Workers AI, LM Studio access, or narrative generation.
- Uploading the full raw Retrosheet corpus; only compact projections required by supported deterministic queries are in scope.
- Authentication, accounts, or server-side query history for the public demo.
- Any tunnel, origin proxy, or Mac-backed emergency fallback.
- Retiring LLM support from the existing local Python application.
