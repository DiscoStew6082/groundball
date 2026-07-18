# Find the Way to a Fully Queryable Ground Ball

Label: `wayfinder:map`

## Destination

Reach a reviewed product and architecture specification, with an implementation handoff, for a mobile-friendly Ground Ball where natural-language questions and structured refinement share one deterministic Query Plan, every loaded primary Lahman row and field plus the team reference lookup is reachable, and a checked-in catalog caps the promoted query surface.

## Notes

- Domain: Ground Ball is a local-first historical MLB almanac. DuckDB/Lahman remains the factual authority for structured answers; every returned answer must expose verifiable rows, SQL, and source metadata.
- Consult the `wayfinder`, `prototype`, `codebase-design`, `domain-modeling`, `tdd`, and `browser-tool-call-hygiene` skills while working this map.
- Refer to Modules, Interfaces, Implementations, Seams, and Adapters using the vocabulary in `CONTEXT.md`.
- Ask HITL questions one at a time, include a recommended answer, and reserve detailed provenance choices for the implementation unless they change product behavior.
- Queryable Data Contract: every loaded primary Lahman table and field is discoverable, every loaded primary Lahman row is reachable through filtering, pagination, or export, and the synthesized team reference lookup is equally reachable. The first release applies this to People, Batting, Pitching, and Fielding plus that team lookup. Additional Lahman tables must be addable without redesigning the application.
- Secondary Retrosheet projections remain governed evidence and deterministic-route data, but exhaustive Retrosheet row-and-field exploration is not part of this destination.
- One progressive interface owns both question entry and structured refinement. It opens with a clearly labeled, editable 40-40 example; asks one focused clarification instead of guessing; uses friendly field names with Lahman details on demand; and defaults to baseball-meaningful grain while preserving raw-row access. The approved answer-first shell keeps the Query Recipe and field discovery progressively disclosed through the top-left navigation and Details surface rather than persistently visible beside every answer.
- Preserve the dark, website-compatible, launched-window visual language. Prototype the 360-430px mobile Query Recipe experience and obtain Stewart's approval before any later decision ticket is taken.
- A readable, checked-in Published Query Catalog is the product capability cap. Profiles promote natural-language fields, statistics, exact calculations, relationships, and operations without hiding the raw loaded Lahman surface. Estimated statistics and arbitrary user formulas are excluded. Numeric request, result, export, and hosting safety ceilings remain owned by the zero-Mac public-demo map.
- Verification is invariant. Stewart chooses the published capability cap, not provenance mechanics statistic by statistic.
- The public demo must remain self-contained, deterministic, zero-Mac, and unable to reach an LLM. Whether an optional LLM Adapter remains in private/local use is an open decision.
- The existing [zero-Mac public-demo map](../public-deterministic-groundball/map.md) remains the sole owner of packaged deployment artifacts, abuse and rate limits, hosting parity, public promotion, and cutover decisions. Its broad hosted-shell prototype is distinct from this map's narrower Query Recipe prototype.
- This map plans and decides. It does not authorize implementation, public promotion, paid hosting, production-domain changes, or secret changes.

## Decisions so far

- [Prototype the mobile Query Recipe experience](issues/01-prototype-mobile-query-experience.md) — Use the approved Variant F answer-first sports feed inside the launched-window frame, with the yellow top-left `GB` control as the single expandable application-navigation trigger, the familiar chat composer fixed at the bottom, compact verified results in the main feed, inline clarification, and technical details progressively disclosed behind one Details surface.

## Not yet specified

None currently. The visible frontier is precise enough to live entirely in child tickets; new fog should be added only when a resolution exposes an in-scope question that cannot yet be stated sharply.

## Out of scope

- Implementing the specification while this planning map is still open.
- Importing the complete Lahman distribution in the first release.
- Exhaustive raw Retrosheet exploration; this map preserves existing secondary evidence and deterministic routes without turning Retrosheet into the primary query surface.
- Estimated statistics, silently selected competing formulas, arbitrary user formulas, or user-editable raw SQL.
- A runtime administrator screen for changing the Published Query Catalog; the catalog is checked in and reviewed.
- Any public LLM inference, tunnel, origin proxy, Mac-backed fallback, or weakening of the current zero-Mac deployment contract.
- Packaged-data release mechanics, abuse and rate limits, hosting parity, public promotion, cutover, paid hosting activation, production deployment, or production-domain changes; those remain with the existing zero-Mac public-demo map.
