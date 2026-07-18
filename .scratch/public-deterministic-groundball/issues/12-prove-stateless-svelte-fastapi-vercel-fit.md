# Prove the stateless Svelte/FastAPI Vercel fit

Type: `prototype`
Status: resolved
Blocked by: none

## Question

Can one dark, website-compatible Svelte application preserve Ground Ball's deterministic answer, evidence, conversation, export, Architecture Explorer, and developer-tool behavior while a server-owned capability boundary makes the hosted Vercel Hobby deployment completely unable to reach the Mac or an LLM, and does one self-contained JSON request per query remain reliable across sequential and concurrent stateless instances?

The implementation replaces Gradio everywhere with a Svelte/Vite frontend served by FastAPI. The browser owns conversation and history; `POST /api/query` receives the full compact conversation and returns the complete answer, visible rows, sources, SQL, conversation turn, and an architecture trace only in local mode. `GET /api/capabilities` is authoritative. Hosted mode must force the deterministic public Request Adapter, reject `llm_flavored`, omit local traces and source excerpts, and make Architecture Explorer source inspection, test execution, eval mutation, review mutation, tunnels, Mac access, and every LLM path unreachable server-side.

The proof must record focused and full test results, frontend build output, final container image size, local browser evidence at `http://127.0.0.1:7861/`, protected Vercel preview URL, cold start, default query, unsupported and LLM-dependent fail-closed behavior, conversation follow-up, CSV/JSON export, at least eight simultaneous identical queries, at least four simultaneous mixed queries, repeated concurrent waves, scale-to-zero recovery, and the disposition of both the previous Gradio evidence preview and the new preview. It authorizes a bounded private preview only, not public or production deployment.

## Answer

Yes. Commit `3a762cd` replaces Gradio everywhere with one dark Svelte/Vite application served by FastAPI. Browser state owns the bounded 20-turn conversation and local history. The server owns the capability boundary, request execution, and static asset delivery. Public mode routes every query through the deterministic public Request Adapter, rejects `llm_flavored`, removes architecture traces, and returns 404 before validation for Architecture Explorer, developer tests, review mutation, and eval mutation. Both public and local requests serialize access to the shared in-process DuckDB runtime.

### Implementation and local verification

- Full Python suite: `812 passed` with one existing Starlette/httpx deprecation warning.
- Frontend suite: `7 passed`; production Vite build emitted a 0.58 kB HTML shell, 12.31 kB CSS, and 66.99 kB JavaScript.
- Ruff passed; mypy passed across 73 source files; deterministic eval gate reported `26 passed, 0 failed, 44 skipped`.
- A built Python wheel was inspected and contains the same compiled HTML, CSS, and JavaScript under `baseball_rag/web_dist`, so `groundball-ui` works outside a source checkout.
- The restarted local server at `127.0.0.1:7861` reported local LLM, Architecture Explorer, and developer capabilities. The default query returned `Davis, Tommy: 153 RBI`, ten visible rows, SQL, evidence, conversation output, and a local architecture trace. Port 8000 had no listener.
- The Codex in-app Browser backend was unavailable after the prescribed single bootstrap attempt, so this session could not capture a visual browser screenshot. The live HTTP smoke, Svelte DOM tests, production asset build, and protected hosted shell were used as the bounded fallback evidence; this is a tooling limitation, not an observed application failure.

### Protected Vercel proof

- Retained preview: `https://ground-ball-itrrf26kl-discostew6082s-projects.vercel.app`
- Deployment: `dpl_HYrrDJvGRqDLk2ZfYPnyPaPP8mBY`
- Inspector: `https://vercel.com/discostew6082s-projects/ground-ball/HYrrDJvGRqDLk2ZfYPnyPaPP8mBY`
- State: protected Preview, Ready, not production; Vercel reported the container function at 132.84 MB. Commits `56b75b6` and `db27e0a` add the 360-430px mobile presentation contract while preserving the public capability boundary.
- The cold container served capabilities in about three seconds and the default query in about five seconds. The current initial cold start plus the earlier same-project sleep/wake proof establish that no warm instance or session affinity is required; the self-contained request contract was then exercised under repeated concurrency.
- `GET /api/capabilities` returned public mode with query enabled and LLM, architecture, and developer tools disabled. The hosted HTML referenced the final compiled Svelte assets.
- The default query returned HTTP 200, Tommy Davis with 153 RBI, ten rows, SQL and Lahman provenance, `public_demo=true`, `llm_access=disabled`, and `architecture_trace=null`.
- `who was Babe Ruth` failed closed with `unsupported_reason=llm_unavailable`; an explicit `llm_flavored` request returned 422; `/api/architecture` returned 404.
- A second request carrying the prior turn returned HTTP 200 and a new conversation turn. The context-only phrase itself required LLM interpretation and therefore correctly failed closed rather than opening an LLM path.
- CSV and JSON exports are browser-generated from the completed response snapshot; frontend tests cover both export links, question snapshot integrity, history restoration, storage failure isolation, and the 20-turn request ceiling.
- Two repeated waves each passed eight simultaneous identical requests and four simultaneous mixed requests: `8/8 + 4/4`, twice. Every response was HTTP 200 with `status=completed` and `architecture_trace=null`.

### Cleanup and decision

The superseded Gradio preview `dpl_BBFiiTud1dKpCDWdg4aKWL3s6GeN`, intermediate Svelte previews `dpl_nbfw8ua41ZS3bC2q5eTZdhxfBp6W` and `dpl_DdGxFWZokBti1Zi6hpT5Munx5hbf`, and pre-mobile Svelte preview `dpl_AEHV8CZrKn3cgTwcnfcsSjBqZpGJ` were removed. They are recoverable only by redeployment from their recorded source state. The verified mobile Svelte preview above is the only retained deployment.

The stateless Vercel Hobby application shape passes. Keep the Cloudflare Container proof postponed. This does not authorize public promotion: packaged-data release choice, abuse/rate controls, parity gates, visual acceptance, and cutover remain separate tickets.
