# Approve the zero-Mac deterministic Ground Ball public demo contract

Type: `grilling`
Status: resolved
Blocked by: none

## Question

What product, architecture, data, privacy, interaction, ownership, and cutover contract should govern the genuinely interactive public Ground Ball demo before detailed implementation decisions are made?

## Answer

Revised 2026-07-17 after confirming that the working pre-tunnel product was the existing Gradio application and comparing current Hugging Face, Cloudflare, and Vercel container terms.

The approved destination is a publicly discoverable Ground Ball application at `/groundball/` that retains the website's dark, window-framed Start-menu application language while allowing a purpose-built interior experience.

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
Ground Ball app window
        | launch or embed the hosted application
        v
Vercel Hobby container function (first proof target)
        | packaged Python process
        v
Existing Gradio app + deterministic Ground Ball service
        |
        v
Read-only DuckDB over a versioned packaged snapshot
  |- Lahman data required by supported routes
  `- compact reviewed Retrosheet projections
```

- Ground Ball owns the container, deterministic runtime policy, and data-release machinery. The blog owns only the Start-menu entry and compatible outer window frame.
- Vercel Hobby is the first proof target because the personal public demo can use its hard-capped $0 allowance. Cloudflare Containers on Workers Paid is the pre-approved fallback if Vercel fails a named acceptance criterion.
- The hosted runtime contains no tunnel origin, Mac hostname, origin proxy token, Access service token for a Mac origin, LM Studio credential, or Mac fallback.
- The hosted application has no required outbound origin dependency after startup. Its deterministic code and reviewed data snapshot ship together as one immutable release.
- Vercel PRO, paid Hugging Face, Google Cloud, and other unbounded pay-as-you-go hosting are not part of this contract.

### Public Query Module

The public runtime preserves the existing Python service Interface rather than introducing a second TypeScript implementation:

```python
execute_request(question, answer_mode="stats_only", conversation=None) -> RequestExecution
```

Its existing Implementation owns deterministic routing, ambiguity detection, typed query specifications, parameterized DuckDB statements, answer assembly, evidence, provenance, suggestions, and conversation-aware request execution. The current Gradio Adapter does not pass `conversation`, so hosted follow-up wiring is not assumed by the compatibility proof and remains a decision for the website-framed application prototype. Public admission must force deterministic behavior and fail closed before every biography, unmatched-planning, narration, or other LLM seam.

The existing `RequestExecution` and `StructuredAnswer` types do not guarantee every field the redesigned public experience may need. The website-framed application prototype owns the explicit mapping from those current types into any public Adapter or UI model, and the parity gates must verify that mapping. Desired public capabilities are:

- status: answered, unsupported, ambiguous, no data, rate limited, or unavailable;
- answer text;
- resolved query family and parameters;
- result columns, rows, total match count, and truncation state;
- sources, SQL or query plan, and dataset release provenance;
- suggested supported questions.

### Data release

- Use a reviewed, versioned, read-only data snapshot bundled into the container release rather than runtime downloads, scheduled upstream refreshes, or direct production edits.
- Include the Lahman tables or projections needed by supported query families.
- Include only compact Retrosheet projections needed by supported public questions, such as the derived strikeout-side event table.
- Do not upload the full raw Retrosheet corpus.
- Every release records source versions, checksums, row counts, schema version, build timestamp, and query-catalog version.
- The complete container image, startup time, resident memory, packaged data, and writable scratch requirements must be measured against Vercel Hobby limits before release.

### Application experience

- Keep the website-compatible outer window frame and Start-menu launch behavior.
- Inside the frame, use a dedicated dark evidence-first application layout.
- Show the answer and key rows first.
- Put Sources, SQL or Query Plan, and Dataset Release evidence one click away in tabs or equivalent disclosure controls.
- Keep recent questions and results in browser-local history only.
- Do not rely on process memory across hosted requests. The website-framed application prototype must decide whether and how to pass a bounded explicit `conversation` value through the Gradio or replacement public Adapter.
- Offer CSV and JSON downloads for the complete query result up to a documented safety cap, with total, exported, and truncated counts made explicit.

### Public access, privacy, and abuse controls

- The application is fully public, indexable, linked from the Start menu, and shareable.
- No account, private-link token, or Cloudflare Access login is required.
- Use invisible burst and sustained rate controls plus request-size, question-length, execution, result, and export limits. Prefer hard service limits that pause or reject work rather than create an overage bill.
- Do not retain raw questions or IP addresses beyond short-lived platform abuse controls.
- Aggregate telemetry may retain route family, status, latency, dataset release, and error class.
- Rate-limit responses are honest and actionable; normal use has no CAPTCHA.
- The first design targets Vercel Hobby's hard free allowances. It must not auto-upgrade to Vercel PRO. If the free proof fails, the explicit fallback decision is Cloudflare Containers on Workers Paid at approximately $5 per month.

### Validation and cutover

- The existing deterministic evaluation manifest is the golden behavior corpus.
- Local and hosted Python/DuckDB executions must agree on intent, support state, result rows, SQL meaning, and provenance for that corpus before cutover.
- Security tests cover ambiguity, injection attempts, oversized input, expensive requests, rate limiting, export bounds, missing packaged data, prohibited outbound origins, and every LLM admission seam.
- Vercel preview validation must prove container build size, cold start, Gradio event delivery, sequential and concurrent visitors, five-minute request bounds, stateless restart behavior, and Hobby usage accounting.
- Browser validation exercises the Start-menu launch, free-form query, evidence disclosure, export, unsupported query, and deterministic follow-up paths.
- Cutover is atomic only after preview parity and security gates pass.
- After the hosted deployment is live, permanently remove the old tunnel hostname and configuration, Mac-related deployment secrets, Pages origin-forwarding code, and dormant Groundball tunnel/API LaunchAgents.
- Final proof must show the public application working while the Mac API, tunnel, and LM Studio remain stopped and unreachable.
- The Mac path is never an emergency fallback. Rollback means returning to a previously verified hosted release or a static unavailable state. Cloudflare Containers may replace Vercel only after the Vercel proof records a failed acceptance criterion.
