# Specify the implementation handoff

Type: `grilling`
Status: claimed
Blocked by: [Prototype the mobile Query Recipe experience](01-prototype-mobile-query-experience.md), [Define completeness and verification gates](04-define-completeness-and-verification-gates.md), [Specify the Lahman source-expansion Seam](06-specify-lahman-source-expansion-seam.md), [Choose the initial promoted query surface](07-choose-initial-promoted-query-surface.md)

## Question

What ordered implementation slices, migration constraints, mobile and desktop acceptance checks, deterministic eval cases, and compatibility requirements form a complete build handoff without reopening resolved product decisions or duplicating the existing zero-Mac map's deployment, hosting, abuse-control, promotion, and cutover responsibilities?

## Working decisions

- Make a clean replacement with no backward-compatibility requirement. Do not preserve legacy planner types, intent strings, payload schemas, SQL paths, compatibility facades, shadow runtime, or per-query fallback.
- Delete `StatQueryPlan`, Lahman `QuerySpec` and template-SQL execution, the current stat registry as semantic authority, and old response projections as their catalog-driven replacements land. Retain only product capabilities deliberately named in the new handoff.
