# Prove Vercel Hobby container fit

Type: `prototype`
Blocked by: 09, 10

## Question

Can a private Vercel preview run the existing deterministic Python/Gradio/DuckDB application from a `Dockerfile.vercel` within Hobby's personal-use, image, memory, CPU, invocation, duration, restart, and hard-pause limits while preserving Gradio event delivery for sequential and concurrent visitors and making no request to the Mac or an LLM?

The proof must record the generated private preview URL and explicit pass/fail evidence for container build and image size, cold start, default-query execution, unsupported and LLM-dependent fail-closed behavior, packaged-data access, browser embedding, multiple sequential queries, concurrent sessions, scale-to-zero recovery, and observed Hobby usage. It tests the current Gradio Adapter as it exists and does not assume that Adapter exposes the service's `conversation` parameter. A failed named criterion activates the Cloudflare Container fallback; success keeps Vercel as the selected host.
