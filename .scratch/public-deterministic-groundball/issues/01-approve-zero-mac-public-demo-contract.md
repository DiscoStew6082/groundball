# Approve the zero-Mac deterministic public demo contract

Type: `grilling`
Status: `resolved`
Blocked by: none

## Question

What product, architecture, data, privacy, interaction, ownership, and cutover contract should govern the genuinely interactive public Groundball demo before detailed implementation decisions are made?

## Answer

The approved destination is a publicly discoverable Groundball application at `/groundball/` that retains the website's dark, window-framed Start-menu application language while allowing a purpose-built interior experience.

### Product behavior

- Preserve full deterministic behavior: statistical leaderboards by season, range, decade, and career; player-season statistics; historical team rosters; grounded historical templates; stat definitions; compact Retrosheet-backed event questions; ambiguity handling; unsupported handling; and bounded deterministic follow-ups.
- Preserve Lahman as the primary factual authority for aggregate and identity questions. This approval explicitly extends the source-authority contract for the public event-query families only: a reviewed compact Retrosheet event projection is authoritative for the event-level facts it directly records, while remaining secondary and optional everywhere else.
- Keep natural-language input and add example chips, capability hints, and useful suggestions when a question fails closed.
- Questions requiring narrative generation, including LLM-dependent biographies, fail closed with a clear explanation that narrative generation is unavailable in the public deterministic demo.
- The public demo does not use an LLM. The existing local Python application keeps its DuckDB and optional LM Studio behavior unchanged.

### Deployment topology

```text
discostew.dev Start menu
        |
        v
Groundball app window
        | POST /groundball/query
        v
Blog Pages Query Adapter
        | private Cloudflare service binding
        v
Groundball Public Query Worker
        | prepared read-only SQL
        v
Cloudflare D1
  |- Lahman projections
  `- compact Retrosheet projections
```

- Groundball owns the Public Query Worker and D1 release machinery.
- The blog owns only the application UI and a thin same-origin Pages Query Adapter.
- The Worker has no public hostname. The Pages project reaches it through a private Cloudflare service binding.
- Neither deployment contains a tunnel origin, Mac hostname, origin proxy token, Access service token for a Mac origin, LM Studio credential, or Mac fallback.
- The Public Query Worker must have no outbound origin dependency. Its bindings are limited to the D1 database, rate limiting, and deployment/version metadata needed by the public contract.

### Public Query Module

The Public Query Module presents one small Interface:

```ts
query({ question, priorContext? }) => QueryResult
```

Its Implementation owns deterministic routing, ambiguity detection, typed query specifications, parameterized SQLite statements, answer assembly, evidence, provenance, suggestions, bounded follow-up resolution, and export planning.

Groundball owns a language-neutral query catalog and response contract. Python/DuckDB and TypeScript/D1 are separate Adapters satisfying that shared contract. Dialect-specific SQL remains inside each Adapter.

Because the public application may be redesigned freely, the new result contract should express:

- status: answered, unsupported, ambiguous, no data, rate limited, or unavailable;
- answer text;
- resolved query family and parameters;
- result columns, rows, total match count, and truncation state;
- sources, SQL or query plan, and dataset release provenance;
- suggested supported questions.

### Data release

- Use a reviewed, versioned D1 snapshot rather than scheduled upstream refreshes or direct production edits.
- Include the Lahman projections needed by supported query families.
- Include only compact Retrosheet projections needed by supported public questions, such as the derived strikeout-side event table.
- Do not upload the full raw Retrosheet corpus.
- Every release records source versions, checksums, row counts, schema version, build timestamp, and query-catalog version.
- The generated D1 database, including indexes, must be measured against current Cloudflare free-plan limits before release.

### Application experience

- Keep the website-compatible outer window frame and Start-menu launch behavior.
- Inside the frame, use a dedicated dark evidence-first application layout.
- Show the answer and key rows first.
- Put Sources, SQL or Query Plan, and Dataset Release evidence one click away in tabs or equivalent disclosure controls.
- Keep recent questions and results in browser-local history only.
- Permit bounded deterministic follow-ups by sending a small explicit prior-result context; keep the Worker stateless.
- Offer CSV and JSON downloads for the complete query result up to a documented safety cap, with total, exported, and truncated counts made explicit.

### Public access, privacy, and abuse controls

- The application is fully public, indexable, linked from the Start menu, and shareable.
- No account, private-link token, or Cloudflare Access login is required.
- Use invisible burst and sustained rate controls plus request-size, question-length, query-cost, execution, result, and export limits.
- Do not retain raw questions or IP addresses beyond short-lived platform abuse controls.
- Aggregate telemetry may retain route family, status, latency, dataset release, and error class.
- Rate-limit responses are honest and actionable; normal use has no CAPTCHA.
- The design targets Cloudflare's free allowances first and documents a paid-plan upgrade path rather than silently weakening limits.

### Validation and cutover

- The existing deterministic evaluation manifest is the golden behavior corpus.
- Python/DuckDB and TypeScript/D1 must agree on intent, support state, result rows, SQL meaning, and provenance for that corpus before cutover.
- Security tests cover ambiguity, injection attempts, oversized input, expensive requests, rate limiting, export bounds, missing bindings, and prohibited outbound origins.
- Preview validation uses the real Pages service binding and a preview D1 release.
- Browser validation exercises the Start-menu launch, free-form query, evidence disclosure, export, unsupported query, and deterministic follow-up paths.
- Cutover is atomic only after preview parity and security gates pass.
- After the cloud deployment is live, permanently remove the old tunnel hostname and configuration, Mac-related deployment secrets, Pages origin-forwarding code, and dormant Groundball tunnel/API LaunchAgents.
- Final proof must show the public application working while the Mac API, tunnel, and LM Studio remain stopped and unreachable.
- The Mac path is never an emergency fallback. Rollback means returning to a previously verified Cloudflare-only application and D1 release.
