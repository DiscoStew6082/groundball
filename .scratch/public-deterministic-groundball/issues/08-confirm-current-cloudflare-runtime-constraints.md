# Confirm current Cloudflare runtime constraints

Type: `research`
Status: resolved
Blocked by: none

## Question

What do current official Cloudflare sources establish about free-plan D1 storage and query limits, D1 performance constraints, Pages-to-Worker service bindings, Worker route isolation, rate-limiting semantics, and any other platform facts that bound the D1 read-model, public-guardrail, parity-gate, and zero-Mac topology decisions?

## Answer

[Cloudflare constraints for the public Groundball runtime](../../../research/cloudflare-public-runtime-constraints.md) records the current first-party platform facts. The topology is viable: Pages can privately invoke an un-routed Worker through a Service binding, and the proposed compact dataset fits the product's free-plan shape subject to measured database-size, indexed rows-read, query-count, duration, serialization, rate-limit, and export gates. Cloudflare's rate-limit binding is permissive and location-scoped, so deterministic resource ceilings remain mandatory.

Superseded for the current route on 2026-07-17: this research remains valid background, but the Worker/D1 rewrite was ruled beyond the revised destination after confirming that the existing Gradio/DuckDB application is the behavior to host. Cloudflare now remains only the Container fallback described by [Confirm current public container hosting constraints](09-confirm-current-public-container-hosting-constraints.md).
