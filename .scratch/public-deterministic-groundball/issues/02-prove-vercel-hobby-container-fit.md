# Prove Vercel Hobby container fit

Type: `prototype`
Status: resolved
Blocked by: 09, 10

## Question

Can a private Vercel preview run the existing deterministic Python/Gradio/DuckDB application from a `Dockerfile.vercel` within Hobby's personal-use, image, memory, CPU, invocation, duration, restart, and hard-pause limits while preserving Gradio event delivery for sequential and concurrent visitors and making no request to the Mac or an LLM?

The proof must record the generated private preview URL and explicit pass/fail evidence for container build and image size, cold start, default-query execution, unsupported and LLM-dependent fail-closed behavior, packaged-data access, browser embedding, multiple sequential queries, concurrent sessions, scale-to-zero recovery, and observed Hobby usage. It tests the current Gradio Adapter as it exists and does not assume that Adapter exposes the service's `conversation` parameter. A failed named criterion activates the Cloudflare Container fallback; success keeps Vercel as the selected host.

## Answer

No. Vercel Hobby can build, start, protect, pause, and wake this container, but it cannot reliably preserve Gradio's in-memory event state across the separate HTTP requests of concurrent sessions. The named concurrent-event-delivery criterion fails, so the Cloudflare Container fallback is activated.

The corrected authenticated evidence preview is:

- URL: `https://ground-ball-3hh438dzn-discostew6082s-projects.vercel.app`
- Deployment: `dpl_BBFiiTud1dKpCDWdg4aKWL3s6GeN`
- Target: `preview`
- Protection: anonymous access receives a `302` redirect to Vercel SSO; the proof used a temporary automation-bypass cookie and did not make the preview public.

### Compatibility evidence

| Criterion | Result | Evidence |
| --- | --- | --- |
| Container build and image | PASS | Vercel built all 14 `Dockerfile.vercel` steps with Buildah, pushed OCI image digest `sha256:704e4f7cd149aeca34544e387b32202ffeec54686dce1fe61ede8aae18f7e036`, and reports `services/app/index` at 278.29 MB in `iad1`. The cold build took 52.9 seconds and reused 0/14 layers. This live result also proves that the current `services` configuration is active despite the project UI retaining the `Other` framework label. |
| Port and process contract | PASS | The image starts `python -m baseball_rag.web_app` on `0.0.0.0:${PORT:-80}`. Vercel served the Gradio root from the service. |
| Packaged data access | PASS | The build downloaded the four canonical Lahman CSVs and compared every row count and SHA-256 value to `data/manifest.json`. A separate build step verified the reviewed 50,081-row Retrosheet strikeout-side projection against its manifest SHA-256. The upload excluded the raw 1.7 GB Retrosheet tree. The hosted default query returned its DuckDB source, manifest, rows, and SQL. |
| Initial cold page | PASS | The first protected root request returned the complete Gradio page after approximately 11.4 seconds. This includes container wake-up and Gradio application initialization. |
| Default query | PASS | A real two-event Gradio client session on the corrected preview answered `who had the most RBIs in 1962` in 2.463 seconds. Tommy Davis was first with 153 RBI; ten rows, one DuckDB source, and SQL were returned. |
| Unsupported policy | PASS | `what are todays betting odds` returned the grounded unsupported-policy response in 0.785 seconds with zero rows and no SQL. |
| LLM-dependent fail-closed | PASS | `who was Babe Ruth` returned in 0.797 seconds: the LLM-backed capability is disabled in the public demo. It returned zero rows, zero sources, and no SQL. Focused tests replace all `requests` traffic with an assertion failure and prove that biography, explanation, unmatched, policy, grounded-template, and default-stat paths make no outbound request. |
| No Mac or LLM route | PASS | `GROUNDBALL_PUBLIC_DEMO=1` selects a dedicated serialized Request Adapter. It uses deterministic routing and substitutes fail-closed handlers for biographies and general explanations before any LM Studio or Mac-backed implementation can run. The existing local Adapter and LLM behavior remain unchanged when the environment flag is absent. |
| Browser embedding and Gradio events | PASS | The protected root served `gradio-app`, its JavaScript and CSS assets, and named `/begin_query` and `/on_query` event metadata. The official Gradio client maintained one browser-equivalent session across both events and returned the rendered answer, rows, provenance, and SQL. The Codex in-app Browser backend was unavailable on the headless machine, so no visual screenshot was captured; hosted HTML/config inspection, the stateful client, contract tests, and the local Gradio smoke provide the recorded embedding evidence. |
| Sequential queries | PASS | One session completed RBI 1962, HR 1961, and SO 1972 queries in 2.029, 0.742, and 0.697 seconds respectively, each with ten rows. |
| Concurrent sessions | **FAIL** | A review first reproduced DuckDB's shared-connection race locally. The public Request Adapter was then serialized; a deterministic concurrency test and an eight-thread real DuckDB stress run passed. The corrected hosted preview subsequently completed eight simultaneous identical sessions correctly, but an immediate four-session mixed wave failed with Gradio client `CancelledError`. Repeating the four-session wave alone failed again. Vercel runtime logs show Gradio `/gradio_api/queue/data` streams raising `404: Not Found` after queue joins, consistent with stateful join and SSE requests reaching different stateless service instances. Application-level DuckDB serialization cannot repair that host-routing boundary. |
| Scale-to-zero recovery | PASS | After 40 seconds with no preview traffic, longer than Vercel's documented 30-second preview scale-in window, the default query completed in 2.305 seconds with ten rows, provenance, and SQL. |
| Observed Hobby usage | PASS for limits, FAIL for delivery | The proof stayed on the personal Hobby scope, enabled no paid usage, and the 278.29 MB image, build, cold start, and query durations remained inside documented limits. There were no observed throttles or out-of-memory restarts. The Gradio SSE 404s are nevertheless disqualifying functional errors. |

### Decision

Do not publish the current Gradio application on Vercel. A custom single-request stateless UI/API could avoid Gradio's in-memory queue protocol, but that would change the application shape this ticket was explicitly asked to test and belongs to a separate decision. The narrower fallback is a named Cloudflare Container/Durable Object that keeps all requests for the demo on one persistent container identity, preserving Gradio's session state while still sleeping after inactivity.

### Proof cleanup

The Vercel CLI's first unqualified deployment unexpectedly targeted production. That invalid static deployment (`dpl_8rcwWdEBaG3sEC5Yd4krHRCV4A6U`) and its production aliases were deleted. The invalid static preview (`dpl_BwVJwuBmgT54BA51VadEKByFBBsW`) was also deleted. The first container proof preview is removed after this corrected evidence preview is retained. Deleted deployments are recoverable only by redeploying their source; none is needed.

### Local verification

- `104 passed` across the public-demo, packaged-data, browser-contract, routing, request-execution, and service tests.
- Ruff check and format check pass for every changed Python file.
- The local `uv run groundball-ui` server remains available at `http://127.0.0.1:7861/`; its default query returned Tommy Davis, 153 RBI, source provenance, and SQL.
- No listener was present on port 8000.
