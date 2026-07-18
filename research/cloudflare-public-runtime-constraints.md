# Cloudflare constraints for the public Groundball runtime

Checked against official Cloudflare documentation on 2026-07-17.

## Decision-relevant findings

### D1 free-plan capacity and invocation limits

- A Workers Free D1 database is limited to 500 MB; total free-account D1 storage is 5 GB. The proposed release therefore needs an automated post-import size gate covering tables and indexes, not just source CSV size. [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- A Free-plan Worker invocation may issue at most 50 D1 queries. D1 also limits a prepared statement to 100 bound parameters, an individual SQL query to 30 seconds, and an invocation to six simultaneous D1 connections. Query plans and exports must stay well below those ceilings. [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- Each D1 database processes queries serially. Throughput is therefore dominated by query duration; indexed, bounded read plans are a release requirement, while full scans and long export queries threaten both latency and concurrency. D1 operations and result serialization also consume Worker CPU and memory. [D1 limits](https://developers.cloudflare.com/d1/platform/limits/)
- The Workers Free allowance currently includes 5 million rows read per day and 100,000 rows written per day. Free limits reset daily; exceeding them causes D1 queries to fail until reset. Indexes reduce billed/scanned rows, and each query's metadata reports rows read and written. Guardrails and parity runs should capture those metrics. [D1 pricing](https://developers.cloudflare.com/d1/platform/pricing/)

### Private Pages-to-Worker topology

- Pages Functions support Service bindings in both preview and production environments. A Pages Function can call the bound Worker through `context.env.<binding>.fetch(...)`, which supports the planned same-origin Query Adapter. [Pages Function bindings](https://developers.cloudflare.com/pages/functions/bindings/)
- Cloudflare explicitly describes Service bindings as Worker-to-Worker calls that do not pass through a publicly accessible URL. A bound Worker can be deployed without public Internet reachability and made reachable only through an explicit Service binding. [Worker Service bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/)
- Service-bound Workers normally run on the same Cloudflare server/thread and do not add service-binding cost. This supports a separate Groundball-owned Worker without requiring a public hostname or duplicating the query Implementation in the blog. [Worker Service bindings](https://developers.cloudflare.com/workers/runtime-apis/bindings/service-bindings/)
- Worker Routes and Custom Domains are mechanisms that create public URL mappings. The zero-Mac proof must assert that the Groundball Worker has no route, custom domain, or enabled `workers.dev` exposure; only the blog's declared Service binding may reach it. [Worker routes](https://developers.cloudflare.com/workers/configuration/routing/routes/)

### Rate limiting and exports

- The Workers Rate Limiting binding supports programmable counters with 10-second or 60-second windows. Cloudflare documents the counters as local to a Cloudflare location, permissive, eventually consistent, and unsuitable for exact accounting. It is a useful abuse signal, not a complete resource-protection mechanism. [Workers Rate Limiting binding](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)
- Because the app has no accounts and privacy rules reject retained IP addresses, the guardrail decision must choose a short-lived, non-identifying client key and combine it with global query-cost, result-size, execution, and export caps.
- A synchronous full-result export still consumes D1 query time, rows read, Worker CPU, memory, and response serialization. The free-tier design therefore needs an evidence-based export cap and should reject or truncate beyond it; unlimited asynchronous export would require an additional persistence Module such as R2 and is outside the approved contract.

## Consequences for open Wayfinder tickets

- **Choose the D1 read model and release projection** must define size, index-coverage, rows-read, query-count, duration, and import reproducibility gates.
- **Set public query, export, and abuse guardrails** must combine the Rate Limiting binding with deterministic resource ceilings and honest `429` or truncation behavior.
- **Define parity and release gates** must capture D1 metadata and performance, not just answer equality.
- **Define preview cutover and zero-Mac proof** must inspect the deployed Worker for absence of public routes/domains and prove the Pages Service binding is the only invocation path.
