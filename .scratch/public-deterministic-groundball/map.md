# Find the Way to a Zero-Mac Interactive Groundball Demo

Label: `wayfinder:map`

## Destination

Reach an implementation-ready, reviewed decision set for a genuinely interactive public Groundball application that preserves full deterministic query behavior on Cloudflare while providing no network route to Stewart's Mac and no public LLM access.

## Notes

- Domain: Groundball is a local-first historical MLB almanac. DuckDB/Lahman remains the primary local factual authority; the public deployment will use a versioned D1 read model plus compact Retrosheet projections.
- Consult the `codebase-design`, `domain-modeling`, `cloudflare`, `tdd`, and `browser-tool-call-hygiene` skills while working this map.
- Refer to Modules, Interfaces, Implementations, Seams, and Adapters using the vocabulary in `CONTEXT.md`.
- Ask HITL questions one at a time and include a recommended answer.
- Preserve the website's dark, window-framed visual language. Groundball should look like an application launched from the Start menu, while its interior may be redesigned freely.
- The existing Mac LaunchAgents and tunnel are disabled. They must never be used as a fallback during design, preview, cutover, or rollback.
- This map plans decisions. It does not authorize implementation, deployment, secret changes, tunnel deletion, or other production mutations.

## Decisions so far

- [Approve the zero-Mac deterministic public demo contract](issues/01-approve-zero-mac-public-demo-contract.md) — The public app will be a discoverable, free-tier-compatible Cloudflare Worker and D1 deployment with full deterministic parity, a private Pages service binding, evidence-first UX, bounded exports, privacy-minimal telemetry, and no Mac or LLM route.
- [Confirm current Cloudflare runtime constraints](issues/08-confirm-current-cloudflare-runtime-constraints.md) — Official platform constraints validate the private service-binding topology and require measured D1 size, indexed rows-read, query-cost, rate-limit, serialization, and export gates.

## Not yet specified

- The implementation slices and commit sequence can be specified only after the query contract, D1 read model, public guardrails, parity gates, app prototype, and cutover proof are resolved.

## Out of scope

- Implementing or deploying the Worker, D1 database, Pages Adapter, or redesigned UI while this map is still finding the way.
- Public LLM inference, Workers AI, LM Studio access, or narrative generation.
- Uploading the full raw Retrosheet corpus; only compact projections required by supported deterministic queries are in scope.
- Authentication, accounts, or server-side query history for the public demo.
- Any tunnel, origin proxy, public Worker hostname, or Mac-backed emergency fallback.
- Retiring LLM support from the existing local Python application.
