# Specify the Lahman source-expansion Seam

Type: `grilling`
Status: claimed
Blocked by: [Specify the Published Query Catalog Interface](02-specify-published-query-catalog-interface.md), [Specify the deterministic Query Plan Interface](03-specify-deterministic-query-plan-interface.md)

## Question

What source-registration Seam lets future Lahman tables contribute fields, relationships, grains, provenance, and catalog entries to the same Query Plan and interface without hard-coding another parallel query lane or importing the complete Lahman distribution now?

## Working decisions

- Standard Lahman expansion uses checked-in declarative source registrations. Executable Adapters remain internal and vary only by source kind, such as a packaged CSV versus the synthesized team reference lookup; individual Lahman tables do not receive custom Adapters or parallel query lanes.
- Registering a source automatically contributes its exhaustive raw surface through the generated raw-field inventory. Friendly natural-language semantics remain separately reviewed, hand-authored, and opt-in under the Published Query Catalog decision.
