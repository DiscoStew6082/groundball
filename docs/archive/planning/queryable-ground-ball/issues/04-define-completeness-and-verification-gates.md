# Define completeness and verification gates

Type: `grilling`
Status: resolved
Blocked by: [Specify the Published Query Catalog Interface](02-specify-published-query-catalog-interface.md), [Specify the deterministic Query Plan Interface](03-specify-deterministic-query-plan-interface.md)

## Question

What automated and visible acceptance evidence proves that every field and row across the loaded People, Batting, Pitching, and Fielding tables plus the synthesized team reference lookup is discoverable and queryable, every permitted calculation is exact, every Query Plan compiles safely, unsupported capabilities fail clearly, and the Published Query Catalog never requires an LLM or Mac?

## Answer

Treat completeness as a release-blocking, generated proof over the exact Published Query Catalog and packaged data release, not as a collection of hand-picked example questions. Ground Ball may call a release fully queryable only when every gate below passes with zero uncovered catalog-declared obligations, fields, or source rows.

Normal users see a quiet **Verified for this data release** status in the result Details surface. Opening it shows the Query Plan, rows, parameterized SQL and bound values, catalog revision, data release, and source metadata, plus a link to the readable public Coverage Report for that Query Run's exact catalog-and-data-release pair. The answer feed does not carry a permanent completeness dashboard.

### Release-blocking gates

1. **Catalog and packaged-schema identity**
   - Compare the generated raw-field inventory with the installed DuckDB schema for People, Batting, Pitching, and Fielding and with the versioned synthesized team reference lookup.
   - Require exact source, field, and type agreement and an explicit compatibility record for the catalog-and-data-release pair. Missing, extra, renamed, or type-drifted fields; an unversioned team lookup; or an undeclared catalog/data pairing fails the gate.
   - Record the catalog revision, data-release identity, source checksums or fingerprints, and the expected and observed row and field counts for all five published sources.

2. **Exhaustive raw-field and raw-row reachability**
   - Enumerate every field returned through the catalog-driven discovery read model, including all search, source-filter, and pagination paths, and compare its stable identities with the exhaustive raw-field inventory. Missing, duplicated, or unreachable fields fail the gate; the synthesized team lookup is covered identically.
   - Exercise every published raw field through selection and every type-appropriate generic operation the catalog promises: filtering, grouping where valid, sorting, pagination, and export.
   - Traverse every raw row through the public Query Planning and Query Execution Interfaces, using deterministic ordering and either browsing or full-match export, then compare source counts and an order-independent row fingerprint with a direct read of the installed source.
   - Any omitted, duplicated, changed, or release-mixed row fails the gate. Representative examples cannot substitute for this exhaustive traversal.

3. **Promoted semantic exactness**
   - Generate a finite acceptance matrix directly from catalog declarations: each promoted entry at each of its declared grains and operations; each calculation with its declared roll-up rule; and each approved relationship in every published direction. The report lists every obligation and permits no uncovered declaration.
   - Verify each permitted calculation against independently stated golden examples and direct recomputation from its declared source components. Additive, recomputed, and non-aggregatable rules must each prove their allowed behavior and reject forbidden roll-ups or grains.
   - Familiar baseball rounding may be used in the compact answer, but the unrounded computed value, exact formula, and source components remain available in Details and exports. No estimate or display rounding becomes source truth.

4. **Query Plan and compiler safety**
   - Prove canonical serialization and round-trip stability for `QueryPlanV1`, catalog-revision pinning, deterministic total ordering and tie behavior, and automatic use of only catalog-approved relationships.
   - Exercise every published Query Plan variant and every catalog-declared obligation in the finite matrix. Use generated compositions and typed literal values to prove canonicalization, recursion, ordering, and compiler-safety invariants without pretending the unbounded set of possible Query Plans can be enumerated. Stale catalog references, invalid types, ambiguous grains or relationships, forbidden operations, unsupported combinations, and adversarial literal values must fail before execution with the approved outcome.
   - Compiled SQL may contain only compiler-owned identifiers and formulas; every user value is bound as a parameter. Query Recipes, HTTP input, controls, and natural-language text can never contribute SQL, identifiers, formulas, join keys, or executable fragments.

5. **Outcome and evidence integrity**
   - Verify the distinct public outcomes already owned by the Query Planning and Query Execution Interfaces: `NeedsClarification`, `Rejected`, `ExecutionUnavailable`, `ExecutionFailed`, successful rows or export, and `NoData`.
   - Every successful Query Run, including `NoData`, must carry one complete immutable evidence bundle: canonical Query Plan, catalog revision, exact data release, parameterized SQL, bound values, source metadata, and stable result counts. Browser, HTTP, CLI, and export consume the same Query Run evidence read model rather than reconstructing evidence independently.
   - A structured factual result is **Verified for this data release** only when that bundle is complete and a passing Coverage Report exists for its exact catalog-and-data-release pair. If either proof is unavailable, Ground Ball returns an unavailable or failed outcome instead of an unverified factual answer.

6. **No-LLM and no-Mac independence**
   - Run the complete catalog, planning, compilation, execution, completeness, and Coverage Report suite with network access denied, no LM Studio or model configured, public deterministic capabilities enabled, and no Mac-specific runtime configuration.
   - Inspect the packaged catalog and runtime dependency graph for forbidden model, network, tunnel, origin-proxy, or machine-local dependencies. Any attempted access or required Mac-only artifact fails the gate.
   - This proves that the Published Query Catalog and fully queryable product surface are self-contained. Hosted local-versus-public parity, container limits, secrets, restart behavior, preview promotion, and final zero-Mac cutover proof remain owned by [Define parity and release gates](../../public-deterministic-groundball/issues/06-define-parity-and-release-gates.md) and [Define preview cutover and zero-Mac proof](../../public-deterministic-groundball/issues/07-define-preview-cutover-and-zero-mac-proof.md).

### Visible acceptance evidence

Generate one versioned canonical gate-results read model and render it as both a machine-readable Coverage Report and a concise public human-readable report. It shows:

- catalog and data-release revisions and source fingerprints;
- expected and observed row and field totals for People, Batting, Pitching, Fielding, and the team reference lookup;
- raw-field operation coverage and full-row traversal results;
- promoted calculation, grain, roll-up, relationship, and Query Plan matrix totals;
- parameterization, unsupported-state, evidence-integrity, and no-LLM/no-Mac results;
- zero failures and zero uncovered published capabilities, or an explicit failed/unavailable state with the failing gate named.

The report is generated from gate results, versioned, and exposed read-only through the application. It never claims current readiness from stale evidence: changing the catalog, packaged data, compiler contract, or report schema invalidates the prior proof until the suite regenerates a green report. How the report is packaged, attached, or publicly promoted remains with the zero-Mac public-demo map.

At 360-430px, the browser acceptance pass verifies that a user can discover a raw field, run a raw-field query, run one exact calculation, answer one focused clarification, receive one clear unsupported rejection, inspect the Verified Details evidence, open the Coverage Report, and export results without horizontal overflow. This smoke pass proves the approved product flow; it complements rather than replaces the exhaustive machine gates.

The acceptance seams are the Published Query Catalog Interface and discovery read model, `prepare(QueryRecipe)`, `execute(QueryPlanV1)`, the immutable Query Run evidence read model, and the canonical gate-results read model behind both Coverage Report representations. Future implementation tests should exercise behavior through those Interfaces rather than private compiler or database helpers.
