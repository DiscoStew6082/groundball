# Prove the stateless Svelte/FastAPI Vercel fit

Type: `prototype`
Status: in progress
Blocked by: none

## Question

Can one dark, website-compatible Svelte application preserve Ground Ball's deterministic answer, evidence, conversation, export, Architecture Explorer, and developer-tool behavior while a server-owned capability boundary makes the hosted Vercel Hobby deployment completely unable to reach the Mac or an LLM, and does one self-contained JSON request per query remain reliable across sequential and concurrent stateless instances?

The implementation replaces Gradio everywhere with a Svelte/Vite frontend served by FastAPI. The browser owns conversation and history; `POST /api/query` receives the full compact conversation and returns the complete answer, visible rows, sources, SQL, conversation turn, and an architecture trace only in local mode. `GET /api/capabilities` is authoritative. Hosted mode must force the deterministic public Request Adapter, reject `llm_flavored`, omit local traces and source excerpts, and make Architecture Explorer source inspection, test execution, eval mutation, review mutation, tunnels, Mac access, and every LLM path unreachable server-side.

The proof must record focused and full test results, frontend build output, final container image size, local browser evidence at `http://127.0.0.1:7861/`, protected Vercel preview URL, cold start, default query, unsupported and LLM-dependent fail-closed behavior, conversation follow-up, CSV/JSON export, at least eight simultaneous identical queries, at least four simultaneous mixed queries, repeated concurrent waves, scale-to-zero recovery, and the disposition of both the previous Gradio evidence preview and the new preview. It authorizes a bounded private preview only, not public or production deployment.
