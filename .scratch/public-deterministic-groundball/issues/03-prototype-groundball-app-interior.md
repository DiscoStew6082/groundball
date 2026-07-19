# Prototype the website-framed hosted Ground Ball experience

Type: `prototype`
Status: resolved
Blocked by: [Prove the stateless Svelte/FastAPI Vercel fit](12-prove-stateless-svelte-fastapi-vercel-fit.md)

## Question

Does the merged dark Svelte/FastAPI application already provide the website-framed hosted experience needed for public release—answer-first Query Runs, editable Query Recipes, inspectable Query Plans and evidence, field discovery, browser-local history, follow-up behavior, Coverage Report access, and CSV or JSON exports—and what bounded presentation or integration decisions, if any, remain without restoring a legacy compatibility layer?

## Answer

Use the merged dark Svelte/FastAPI shell unchanged as the presentation baseline for both local and hosted Ground Ball. Stewart approved the running application from commit `cc8f88b` on a mobile phone over the local network; that tree is content-identical to merged PR #19 at `f77b1df`. No alternate hosted interior, second prototype, persistent advanced-control panel, or legacy compatibility layer is needed.

The website should launch this same answer-first application inside the existing dark window frame. Preserve its compact mobile layout, top-left application navigation, bottom question composer, inline clarification and rejection states, progressively disclosed Query Recipe and Query Plan details, field discovery, evidence and Coverage Report access, browser-local history, and browser-generated CSV and JSON exports. Website integration may own only the launch and surrounding frame; it must not introduce a second query contract or hosted-only application surface.

The review also exposed a functional release blocker rather than a presentation decision: the natural-language question `how many home runs did ohtani hit in the year he had the most wins as a pitcher` is rejected even though the canonical structured Query Recipe can return `2022`, `34 HR`, and `15 pitching wins` when filtered by Ohtani's stable player identity. The equivalent composed recipe filtered by friendly player name also exposes a compiler defect because its hidden name-match projection is lost before filtering. These gaps must be corrected through the existing Published Query Catalog, player-identity authority, Query Recipe, Query Plan, and Query Run path. They do not justify a special Ohtani route, compatibility Adapter, alternate compiler, or new presentation.

Contextual follow-up behavior is also not yet proven by the merged application: browser-local history is present, but the current request Adapter sends only the new question or structured recipe rather than prior conversation context. This is a functional parity blocker, not a reason to change the approved shell. The later release work must either restore follow-ups through the canonical stateless request contract or obtain an explicit product decision to exclude them; this prototype approval makes neither choice.

The exact Ohtani question and result belong in the later local-versus-hosted parity and release evidence. This ticket approves the shell; it does not claim the current implementation is ready for public promotion, authorize the query fixes, or replace the remaining packaged-release, guardrail, parity, and cutover decisions.
