# Specify the Lahman source-expansion Seam

Type: `grilling`
Status: resolved
Blocked by: [Specify the Published Query Catalog Interface](02-specify-published-query-catalog-interface.md), [Specify the deterministic Query Plan Interface](03-specify-deterministic-query-plan-interface.md)

## Question

What source-registration Seam lets future Lahman tables contribute fields, relationships, grains, provenance, and catalog entries to the same Query Plan and interface without hard-coding another parallel query lane or importing the complete Lahman distribution now?

## Answer

Use one checked-in declarative **Published Lahman Source Registry Module** as the source-registration Seam. A source contribution describes what a published primary source means; it does not implement a new query path. The Module assembles those contributions into one immutable published-source view consumed by the existing Published Query Catalog, Query Planning, Query Execution, discovery, provenance, and completeness Interfaces.

### Source contribution contract

Each contribution declares only the stable facts the shared query system needs:

- a stable source identity and its source kind: packaged Lahman table or versioned synthesized reference lookup;
- its binding to the packaged data release and provenance record;
- its named baseball grains and the fields that identify those grains;
- its approved relationships to other published sources, including direction and cardinality;
- its contribution to the exhaustive generated raw-field inventory; and
- any separately reviewed promoted catalog entries that intentionally add friendly names, aliases, calculations, or natural-language behavior.

Registering a source automatically makes its complete raw surface discoverable and reachable through the generic structured controls already owned by the Published Query Catalog. It does not automatically promote raw fields into natural-language semantics. Promoted semantics remain hand-authored and opt-in, preserving the reviewed capability cap.

Relationships are explicit declarations, not conventions inferred from matching names such as `playerID` or `teamID`. Query Recipes, Query Plans, and external callers use only stable source, field, grain, and relationship identities; physical filenames, DuckDB table names, technical join keys, and source-specific loading behavior remain hidden inside the registry and Query Execution Implementations.

### Seam and Adapters

Executable Adapters remain internal to the Module and vary only where behavior actually differs by source kind. The initial real variation is:

- a packaged Lahman-table Adapter; and
- a synthesized-reference Adapter for the team lookup.

Individual Lahman tables do not receive custom Adapters. Adding a future standard table therefore adds a packaged asset and provenance binding, one declarative source contribution, a regenerated raw inventory, declared grains and approved relationships, and optional promoted semantics. It does not require a new route, planner branch, compiler branch, interface control, evidence path, or completeness mechanism.

The assembled published-source view is the single downstream dependency. It gives the catalog and discovery Interfaces rendering-neutral source metadata, and gives Query Execution an internal trusted mapping from stable catalog identities to registered relations. Provenance follows those resolved source identities rather than being reconstructed from rendered SQL or labels.

### Scope boundaries

- Only explicitly registered sources are published; this Seam does not import or expose the complete Lahman distribution.
- Retrosheet remains separately governed secondary evidence and does not register as a primary Lahman source through this Module.
- Runtime plugin discovery, administrator-editable source registration, and per-table executable callbacks are excluded. Registrations are checked in, reviewed, deterministic, and usable without an LLM or Mac.
- Physical loading, schema-normalization mechanics, row-locator strategy, validation ordering, startup availability policy, checksum failure handling, and exact error types are implementation-handoff details unless a later product decision gives them visible behavior.
