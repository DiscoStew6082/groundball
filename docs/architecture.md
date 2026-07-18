# Architecture

Ground Ball has one structured-query pipeline and three adapters.

```text
question or recipe
       |
       v
Recipe Adapter -----> NeedsClarification / Rejected
       |
       v
Query Plan v1 validator
       |
       v
Catalog-bound compiler -----> ExecutionUnavailable
       |
       v
DuckDB execution -----> Rows / NoData / Exported / ExecutionFailed
       |
       v
QueryEvidence + Coverage proof binding
       |
       +---- HTTP
       +---- CLI
       +---- Svelte
```

## Authority boundaries

The Published Query Catalog owns sources, raw fields, promoted values, grains, relationships, combinations, recipes, operations, formulas, roll-up policy, and public visibility. The runtime never discovers a second semantic vocabulary from Python registries or router rules.

The plan contract is closed and versioned. Unknown keys, coercible-but-wrong types, non-finite numbers, stale catalog revisions, unlisted values, invalid grains, forbidden operations, arbitrary formulas, and forged source identifiers fail before executable SQL is produced.

The compiler owns all SQL structure and identifiers. Recipe literals become bound parameters. Cross-source results use only catalog-declared relationships and combinations. Ranking and pagination use deterministic total ordering; tie policy is explicit.

## Data identity and evidence

DuckDB loads People, Batting, Pitching, Fielding, and the versioned TeamReference asset. Runtime compatibility compares the catalog against a semantic data-manifest hash: provenance timestamps may change without changing identity, but table content, checksums, row counts, or schema changes invalidate it.

Every successful execution produces QueryEvidence containing the canonical plan, catalog revision, data release, parameterized SQL, bound values, source metadata and fingerprints, row counts, and result fingerprint. Returned rows are immutable snapshots.

The Coverage Report independently binds that evidence to generated release proof. If the proof is missing, failing, malformed, hash-invalid, or stale, application adapters return `unavailable` and do not expose unverified factual rows.

## Completeness proof

`generate_coverage_report.py` blocks network access and exercises six fixed gates:

1. Catalog/schema identity for all five sources.
2. Raw discovery, every declared raw operation, source pagination, and full-row fingerprint traversal.
3. Every public promoted value at every allowed grain, every type-appropriate filter, semantic declarations, cross-source combinations, named recipes, and golden answers.
4. Closed plan parsing, catalog pinning, parameterization, forged-identifier rejection, and deterministic ordering.
5. Every public outcome plus complete evidence fields and adapter sharing.
6. No LLM, network, or Mac runtime dependency.

The JSON report is canonical; Markdown and the human HTTP view are derived from it.

## Separate capabilities

Retrosheet event queries use six explicit template families in `db/retrosheet_query_templates.py` and a checksum-validated, year-aware identity reference generated from the official Retrosheet team catalog plus Lahman season names. They are not a fallback for arbitrary questions.

Player biography and general explanation classes remain callable auxiliary modules. They do not participate in query interpretation or structured factual execution. Biography claim vocabulary now consumes the Published Query Catalog instead of a second stat registry.
