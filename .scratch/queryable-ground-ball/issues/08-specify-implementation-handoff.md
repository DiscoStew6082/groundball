# Specify the implementation handoff

Type: `grilling`
Status: resolved
Blocked by: [Prototype the mobile Query Recipe experience](01-prototype-mobile-query-experience.md), [Define completeness and verification gates](04-define-completeness-and-verification-gates.md), [Specify the Lahman source-expansion Seam](06-specify-lahman-source-expansion-seam.md), [Choose the initial promoted query surface](07-choose-initial-promoted-query-surface.md)

## Question

What ordered implementation slices, migration constraints, mobile and desktop acceptance checks, deterministic eval cases, and compatibility requirements form a complete build handoff without reopening resolved product decisions or duplicating the existing zero-Mac map's deployment, hosting, abuse-control, promotion, and cutover responsibilities?

## Answer

Build the fully queryable product as a clean replacement in seven dependency-ordered vertical slices. There is no backward-compatibility requirement: do not preserve legacy planner types, intent strings, payload schemas, SQL paths, compatibility facades, shadow runtime, or per-query fallback. Each slice replaces and deletes the superseded primary-Lahman behavior in its area rather than layering a second permanent query lane over it.

### Working method and pre-agreed test seams

Each acceptance increment within a slice repeats one public-behavior red test, the smallest end-to-end Implementation that passes, and focused verification before moving to the next increment. Independent code review, any resulting refactor, consolidated runtime evidence, and a commit close the slice before the next slice begins. Refactoring is not mixed into the red-green loop.

The agreed test seams are:

- the immutable published-source view from the Published Lahman Source Registry;
- the Published Query Catalog Interface and catalog-driven discovery read model;
- `prepare(QueryRecipe)` and its `Ready`, `NeedsClarification`, and `Rejected` outcomes;
- `execute(QueryPlanV1)` and its rows, export, `NoData`, `ExecutionUnavailable`, and `ExecutionFailed` outcomes;
- the immutable Query Run evidence read model;
- the canonical gate-results read model behind both Coverage Report representations; and
- the new HTTP, CLI, browser, and export Adapters over those Interfaces.

Tests exercise behavior through these Interfaces. They do not target compiler helpers, DuckDB internals, private formula functions, or compatibility side channels.

### Slice 1: Raw-query tracer

Deliver one thin complete path from published source to an evidence-complete internal Query Run:

- introduce the checked-in declarative source registry for People, Batting, Pitching, Fielding, and the versioned season-aware team reference;
- generate the initial checked-in raw-field inventory and the smallest valid promoted-catalog shell;
- introduce `QueryRecipe`, canonical `QueryPlanV1`, the planning outcomes, one trusted compiler, Query Execution, and immutable Query Run evidence;
- prove a discovered raw field such as `People.birthCity` can be selected and filtered through `prepare` and `execute`; and
- record parameterized SQL, bound values, source identity, catalog revision, data release, rows, and counts in the Query Run.

The first red test crosses the target public Interfaces; it does not wire a temporary browser route or choose between old and new engines. Old code may remain physically present while this tracer is built, but no runtime selector or fallback is introduced.

Acceptance evidence: canonical plan serialization is stable; an adversarial literal is bound rather than interpolated; a stale field or catalog identity fails before SQL; and the raw result carries complete evidence. This slice does not claim **Verified for this data release** and cannot ship a factual result because the canonical Coverage Report does not pass until Slice 7.

### Slice 2: Complete raw surface

Expand the tracer generically, not table by table:

- make every loaded field in all five published sources discoverable exactly once by stable identity;
- support the catalog's type-appropriate selection, filtering, valid grouping, sorting, deterministic browsing, and full-match export operations;
- complete the season-aware team reference so every referenced team identity has one friendly season-correct name;
- enforce catalog/data-release compatibility and return `ExecutionUnavailable` for missing, extra, renamed, or type-drifted fields; and
- prove browsing and export do not omit, duplicate, or mix rows across an execution.

Acceptance evidence: discovery enumeration equals the checked-in raw inventory; every raw field exercises every promised generic operation; each source is traversed through planning and execution; and its count plus order-independent row fingerprint matches a direct installed-source read.

### Slice 3: Promoted batting

Add the first natural-language and guided-recipe vertical:

- promote player, season, season-aware team, and league dimensions;
- publish the People-to-Batting and season-aware team-to-Batting relationships required by those dimensions;
- add the approved batting counts, AVG, OBP, SLG, and OPS with catalog-owned formulas and roll-ups;
- add explicit rate eligibility behavior, 30-30, 40-40, 500-home-run, and batting Triple Crown recipes; and
- prove natural-language interpretation and a manually built structured recipe canonicalize to the same Query Plan.

The current stat registry, `StatQueryPlan`, batting branches in `db/queries.py`, and Lahman batting template SQL cease to be semantic or execution authorities as their replacements land; delete them when no remaining deliberate capability uses them.

Acceptance evidence includes the editable 40-40 example, the existing 1962 RBI smoke, exact broader-grain rate recomputation, one bare rate-leaderboard clarification, one explicit-floor leaderboard, tie-at-cutoff behavior, and rejection of arbitrary formulas.

### Slice 4: Remaining promoted semantics

Complete the approved single-source catalog:

- add the exact People almanac facts;
- add the approved pitching counts, innings, ERA, and WHIP;
- add the approved fielding counts, innings, and fielding percentage;
- enforce every allowed grain and the complete additive, recompute, or non-aggregatable matrix; and
- resolve shared abbreviations such as `G`, `H`, `HR`, `BB`, and `SO` from context or ask one focused clarification.

Delete the superseded pitching and fielding executor branches, duplicated formulas, prompt vocabulary, and Lahman template SQL as the catalog assumes ownership. Stored rates never become roll-up truth; authoritative components and outs remain the source.

Acceptance evidence: fielding `G` and `GS` cannot roll across positions, fielding `DP` cannot masquerade as a team or league play total, broader-grain rates recompute from components, exact filtered rates need no sample floor, and player facts remain non-aggregatable.

### Slice 5: Relationships and cross-discipline questions

Add only the approved relationship behavior:

- publish the remaining People-to-Pitching, People-to-Fielding, season-aware team-to-Pitching, and season-aware team-to-Fielding relationships;
- resolve friendly relationships without exposing technical keys;
- independently aggregate each fact source before combining it at player-season, player-team-season, or player-career grain;
- reject direct raw fact-to-fact joins and ambiguous relationship paths; and
- preserve exact historical team identity without inferring franchise continuity.

Acceptance evidence: “Braves in 1936” resolves Boston's season identity; “Braves all time” clarifies; an Ohtani batting-plus-pitching season query does not multiply stints or positions; and a forbidden or ambiguous relationship fails before execution.

### Slice 6: Clean application cutover

Replace the user-facing composition root in one clean application slice:

- productionize approved Variant F as the dark answer-first sports feed with the yellow `GB` navigation control and fixed composer;
- make natural-language input and structured refinement edit the same Query Recipe;
- expose field discovery through navigation and Details, focused clarification inline, and Query Plan, calculations, rows, evidence, verification, Coverage Report link, and export through one Details surface;
- replace the HTTP, CLI, browser, and export Adapters with clean new contracts over Query Recipe and Query Run; and
- switch all primary People, Batting, Pitching, Fielding, and team-reference requests to the new composition root.

There is no compatibility `/query` route, response projection, legacy intent value, dual planner, per-query fallback, or old/new arbitration. A release containing this slice either uses the new primary query system or does not ship.

This application cutover is an integration-branch milestone, not release readiness. Until Slice 7 produces a passing Coverage Report for the exact catalog-and-data pair, the UI renders verification and the report as unavailable and no factual result may claim **Verified for this data release** or ship.

Retrosheet game-log, streak, and event routes remain separately governed deterministic capabilities and never become primary Lahman sources or alternate answers for primary queries. Local LLM biography and general-explanation Modules are outside this handoff and must not complicate or arbitrate the new structured query path.

### Slice 7: Proof, deletion, and handoff closeout

Finish with generated proof and removal, not another feature layer:

- generate one canonical gate-results read model and its machine-readable and human-readable Coverage Reports;
- require exact source/schema identity, raw-field operation coverage, full-row traversal, promoted obligation coverage, formula goldens, Query Plan safety, outcome integrity, complete evidence, and no-LLM/no-Mac independence;
- invalidate stale proof whenever the catalog, packaged data, compiler contract, or report schema changes;
- run the deterministic eval matrix, mobile and desktop Browser acceptance, focused Adapter checks, then the full repository quality commands; and
- delete all remaining primary-Lahman `StatQueryPlan`, Lahman `QuerySpec` and `AssembledSQL` execution, primary-Lahman grounded template SQL, old stat-registry authority, partial team map, old primary assemblers, legacy payload models, duplicate formula and relationship definitions, dead routes, and tests that specify superseded behavior.

Retain or migrate the separately governed Retrosheet deterministic templates behind their existing capability Interfaces; deletion of primary-Lahman template execution must not erase those routes. The closeout must include a source search proving no old primary query compiler, fallback, or semantic authority remains. Update architecture documentation and `CONTEXT.md` to name the new completed Modules and remove obsolete current-opportunity language only after the implementation and proof land.

### Intentional behavior changes

These are the new contract, not regressions to preserve:

- valid empty execution returns successful `NoData` with full evidence rather than an unsupported answer;
- a bare rate leaderboard clarifies unless an exact reviewed eligibility rule exists;
- team identity is season-aware rather than a partial code-only label or inferred franchise;
- rankings include every result tied at the cutoff by default;
- planning and execution use discriminated outcomes instead of legacy `unsupported` booleans and intent strings; and
- the new HTTP and CLI payloads expose canonical recipe, plan, outcome, evidence, catalog revision, and data release directly rather than projecting old shapes.

### Deterministic eval matrix

The static answer eval remains useful regression evidence, but it is not the completeness proof. Add exact Query Plan and Query Run assertions for at least these cases:

| Case | Required behavior |
| --- | --- |
| `who had the most RBIs in 1962` | Tommy Davis, 153 RBI, with plan and evidence |
| Editable 40-40 recipe | Canseco 1988, Bonds 1996, Rodriguez 1998, Soriano 2006, Acuña 2023, and Ohtani 2024 |
| Aaron Judge's 2022 OPS | Recompute from catalog components; expose unrounded value, formula, and inputs |
| `highest batting average in 1894` | `NeedsClarification` for eligibility or a sample floor |
| Same query with at least 100 AB | Hugh Duffy, `237 / 539`, with bound threshold |
| `who had the most strikeouts in 2024` | One batting-versus-pitching clarification |
| `who played for the Braves in 1936` | Season-aware `BSN`, Boston Braves |
| `Braves all time` | Clarification about historical identities or era |
| At least 30 HR and 10 pitching wins in one season | Ohtani 2022 `(34, 15)` and 2023 `(44, 10)` only |
| Top one home-run hitter in 2021 | Perez and Guerrero Jr., both 48, under default include-ties policy |
| Fielding `G` at team-season or fielding `DP` at league-season | `Rejected` as a forbidden roll-up |
| Players with 100 HR in 2024 | Successful `NoData` with complete evidence |
| Raw structured `Batting.GIDP` query | Discoverable and executable without natural-language promotion |
| Arbitrary formula or SQL-like input | `Rejected`; no executable fragment reaches compilation |
| Stale catalog revision | Fails before execution and runs no SQL |
| Every outcome kind | Separate fixtures for clarification, rejection, unavailable, failed, no data, rows, and export |

Expected values come from checked-in independent goldens or direct source facts, not from recomputing expected output through the same catalog/compiler Implementation under test.

### Mobile and desktop acceptance

Preflight the local server through shell and HTTP, then use the visible Codex in-app Browser at `http://127.0.0.1:7861/`; inspect page and console errors at every viewport. Keep the server running after acceptance.

At 360×800, 390×844, and 430×932:

- preserve the dark launched-window frame, editable 40-40 example, fixed composer, and yellow top-left `GB` navigation;
- allow no document-level horizontal overflow; only intentional result scrollers may scroll horizontally;
- keep primary controls at least 44×44 pixels, the composer/send target 48 pixels, safe-area insets, and readable wrapped evidence and SQL;
- run the 40-40 recipe, discover and query raw `Batting.GIDP`, inspect Judge OPS details, resolve the strikeout clarification inline, receive an arbitrary-formula rejection, open the matching Coverage Report, and export the exact result snapshot; and
- verify menu and Details focus entry, keyboard traversal, Escape and outside-click dismissal, and focus restoration.

At 1024×768 and 1440×900:

- use the same answer-first application rather than a separate desktop layout;
- keep Query Recipe and evidence progressively disclosed rather than permanently beside every answer;
- verify navigation, Details, discovery, clarification, paging, report, and export with keyboard operation; and
- run `who had the most RBIs in 1962`, confirming Tommy Davis, 153 RBI, rows, parameterized SQL, evidence, and no page or console error.

### Validation commands and scope boundary

After focused slice checks, closeout runs the repository's Python lint, formatting, type, non-LLM test, deterministic eval, web test, and production-build commands. The implementation plan should use the exact commands current at execution time rather than freezing tool syntax in this planning ticket.

This handoff owns the registry, complete versioned team reference, catalog and raw inventory, planning/compiler/execution Modules, evidence, Coverage Reports, clean HTTP/CLI/Svelte/export Adapters, deterministic evals, and local mobile/desktop proof.

The zero-Mac public-demo map alone owns packaged-release attachment or promotion, numeric request/result/export ceilings, abuse and rate controls, hosted parity, cold/warm/concurrency/container limits, secrets, restart behavior, preview or production promotion, domain integration, external rollback/cutover, and proof that no deployed route reaches Stewart's Mac. Nothing in this handoff authorizes those actions.
