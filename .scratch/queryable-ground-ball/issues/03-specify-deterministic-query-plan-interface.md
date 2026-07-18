# Specify the deterministic Query Plan Interface

Type: `grilling`
Status: resolved
Blocked by: [Specify the Published Query Catalog Interface](02-specify-published-query-catalog-interface.md)

## Question

What typed Query Plan Interface can represent field selection, filters and comparisons, grouping, exact derived calculations, ranking, sorting, pagination, export, and approved joins while remaining deterministic, serializable, safely translatable to parameterized SQL, and equally editable through natural language or structured controls?

## Answer

Use one closed, versioned Query Plan Interface as the validated, executable,
declarative meaning of a Query Recipe. Natural-language interpretation and
structured controls edit the same Query Recipe; neither emits SQL or bypasses
planning. A Query Plan describes the desired result, never an ordered database
procedure.

### Product contract

- Ground Ball creates a Query Plan only after the Query Recipe is clear, valid,
  and executable. Otherwise planning asks one focused clarification or returns a
  clear unsupported reason. A valid query that finds no rows is a successful
  execution result, not a planning failure.
- The Published Query Catalog is the capability authority. It owns the fields,
  statistics, calculations, grains, operations, relationships, formulas, and
  roll-up rules a Query Plan may use.
- Users can select fields and exact calculations; filter literal values or
  compare compatible catalog values; combine filters with `all`, `any`, and
  `not`; group results; rank and sort them; browse long results without gaps or
  duplicates; and export every matching row within separately governed safety
  limits.
- Planning resolves approved data relationships automatically. Query Recipes
  never expose tables, join keys, join direction, formulas, SQL fragments, or
  physical column names. If more than one approved relationship path is valid,
  planning asks for clarification rather than guessing.
- Rankings record their tie behavior and include every result tied at the
  cutoff by default. An exact-count policy remains available when explicitly
  requested. Stable identity keys order otherwise equal rows deterministically.
- Every execution preserves verification evidence: result rows, parameterized
  SQL, bound parameters, source metadata, catalog revision, and the exact data
  release used.

### Interface shape

`QueryPlanV1` is an immutable, canonically serializable record with these named
semantic sections:

```text
QueryPlanV1
  version              fixed Query Plan schema identity
  catalog_revision     exact Published Query Catalog revision
  grain                NamedGrain | RawRows | GroupBy
  selections           ordered catalog ValueRef entries
  predicate            Compare | All | Any | Not | none
  relationships        resolved approved RelationshipRef entries
  ranking              RankSpec | none
  ordering             ordered SortSpec entries
  output               InteractivePage | Export
```

The closed record is intentionally not a general expression language or
relational operator tree. Small discriminated values provide only the required
variation:

- `ValueRef` identifies a catalog field, promoted statistic, exact calculation,
  or catalog-approved aggregation. Formulas and SQL expressions remain in the
  catalog and compiler Implementation.
- `grain` is always explicit in a validated plan. It names either a
  catalog-defined baseball grain such as player-season or player-career, raw
  rows from one published source, or an explicit grouping of published raw
  fields. Planning may supply a catalog default only when exactly one
  baseball-meaningful choice exists; otherwise it clarifies.
- `Compare` uses a catalog-approved operator and compares a `ValueRef` with a
  typed literal or a compatible `ValueRef` valid at the same grain. Typed
  literals have canonical JSON representations; callers cannot provide SQL,
  identifiers, or untyped expression strings.
- `RankSpec` records the ranked value, highest or lowest direction, requested
  count, optional within-group dimensions, and `include_ties` or `exact_count`
  policy.
- `SortSpec` records value, direction, and null placement. Planning guarantees a
  total deterministic order without changing the visible ranking; the exact
  tie-breaker and continuation mechanics remain implementation decisions.
- `InteractivePage` records that the result is browsable. `Export` records the
  requested published format and full-match intent. Navigation mechanics and
  numeric ceilings stay outside the reusable Query Plan; the latter remain
  owned by the zero-Mac public-demo map.

Every catalog reference uses a stable catalog identity. The Query Plan pins its
catalog revision because a catalog change can change meaning; a stale plan must
be revalidated rather than silently reinterpreted. The plan deliberately does
not pin a data release. Re-running the same plan against a newer installed
release preserves the query's meaning, while the Query Run records the release
actually used. Browsing must not omit, duplicate, or silently mix records across
an execution, but the mechanism that enforces that invariant is left to the
implementation handoff.

### Planning and execution seam

The deep Query Planning Module exposes two conceptual entry points:

```text
prepare(QueryRecipe) -> Ready(QueryPlanV1)
                      | NeedsClarification(question, suggested_recipe_change)
                      | Rejected(reason)

execute(QueryPlanV1) -> QueryRun
                         | ExecutionUnavailable(reason)
                         | ExecutionFailed(reason)
```

`prepare` resolves aliases to catalog identities, selects or clarifies grain,
validates operations and types, resolves one approved relationship path,
canonicalizes semantically equivalent input, and produces the executable plan.
`execute` compiles only catalog-owned identifiers and formulas to parameterized
SQL, binds every user value, executes against DuckDB, and returns rows or an
export plus verification evidence. A successful `QueryRun` may contain rows, a
completed export, or an explicit `NoData` result.

The Module hides formula expansion, roll-up selection, relationship-path search,
SQL stage placement, aliases, identifier quoting, parameter binding, stable
tie-breakers, navigation mechanics, provenance shaping, and compatibility
translation from the current narrow `StatQueryPlan` and `QuerySpec` types. The
Published Query Catalog and compiler are in-process dependencies. DuckDB is a
local-substitutable execution dependency behind the same Interface; natural
language, Svelte, HTTP, and CLI remain Adapters around the Query Recipe and Query
Run rather than alternative planning paths.

Planning failures never masquerade as execution results: ambiguity produces one
clarification, unsupported capability produces a rejection, unavailable or
corrupt catalog/data state produces `ExecutionUnavailable`, an operational
execution error produces `ExecutionFailed`, and a successfully executed empty
result remains `NoData` with full evidence.
