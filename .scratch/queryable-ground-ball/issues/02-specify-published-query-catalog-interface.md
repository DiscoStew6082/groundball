# Specify the Published Query Catalog Interface

Type: `grilling`
Status: resolved
Blocked by: [Prototype the mobile Query Recipe experience](01-prototype-mobile-query-experience.md)

## Question

What is the smallest readable catalog Interface that distinguishes mandatory raw Lahman discoverability from promoted query semantics, then defines friendly fields, aliases, exact derived statistics, valid grains, filters, aggregations, approved joins, and verification metadata once for interpretation, controls, planning, documentation, and completeness checks while leaving numeric safety ceilings to the zero-Mac public-demo map?

## Answer

Use one small, checked-in Published Query Catalog Interface with two parts: an exhaustive generated raw-field inventory and a hand-authored promoted semantic layer. The same catalog governs structured public and local Ground Ball; runtime profiles remain deferred until concrete capability divergence exists.

- Raw coverage uses a hybrid catalog: a generated, checked-in inventory exhaustively records every in-scope primary Lahman table and field plus the synthesized team reference lookup, while hand-authored semantic entries define friendly names, aliases, exact calculations, approved relationships, and promoted query semantics. Verification rejects drift between the packaged schema and the checked-in inventory.
- Unpromoted raw fields remain reachable through one generic structured field interface for selection, type-appropriate filtering and grouping, sorting, pagination, and export. Natural-language interpretation recognizes only promoted semantic entries; the first release does not require field-specific natural-language behavior for raw fields such as `People.birthCity`.
- Public and local Ground Ball consume one canonical Published Query Catalog and one promoted query surface. Runtime profiles are not part of the initial Interface; add them only when a concrete second capability cap exists.
- Every promoted statistic and exact calculation declares its allowed result grains, such as player-season, player-career, or team-season. The Query Plan may use only those declared grains; unsupported combinations trigger focused clarification or fail clearly instead of being inferred.
- Filter operations use safe defaults declared once per data type: numeric fields support exact comparisons and ranges, text fields support exact and one-of matching, and temporal fields support before, after, and ranges. Individual catalog entries declare only reviewed exceptions; fuzzy behavior is never implied by type.
- The catalog declares every approved relationship between data sources, including the technical join keys and supported direction. The Query Plan may cross only those approved relationships, while the interface presents friendly relationships and never asks users to choose database join keys.
- Each promoted statistic or exact calculation has one canonical catalog entry containing its stable identity, friendly name, aliases, plain-language explanation, exact formula, source-field references, and allowed result grains. Interpretation, controls, planning, documentation, and verification consume that same definition rather than duplicating formulas or descriptions elsewhere.
- The same canonical entry carries one minimal roll-up rule: additive, recompute from named source fields, or not aggregatable. This prevents invalid averaging of rate statistics without introducing a separate formula language or user-visible configuration system.
