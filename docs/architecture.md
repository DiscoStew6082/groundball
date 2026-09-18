# Architecture

Ground Ball has one structured-query pipeline and a bounded sourced assistant, presented through the same application. The structured pipeline remains:

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

## Question interpretation and sourced answers

`question_interpretation.py` owns the model prompt, closed response schema, validation, and `run_question_input`. The existing deterministic adapter runs first. When injected interpretation is available, it may propose a published Query Recipe, a bounded research request, a clarification code, or rejection. It cannot supply factual prose or SQL. Proposed recipes still pass the same planner and compiler.

`assistant.py` owns factual selection and rendering for `pregame`, `team_history`, and `definition`. Statistical facts retain their immutable Query Run and QueryEvidence. `ResearchSources` supplies only bounded fixture and historical postseason records; public code validates their scope and constructs the answer. The outer runtime owns model transport and external I/O, while the public repository remains the source of product behavior.

`ground-ball-assistant-answer-v1` adds at most five sourced facts to the existing `/api/query-runs` endpoint. Each answer retains source records, observation times, fingerprints, limitations, and application-owned credits from `source_attribution.py`. The Svelte chat renders plain text and safe HTTPS citations, preserves the last completed answer after a failed attempt, and supports browser-local history and full JSON downloads. Query recipe editing, pagination, and CSV export remain Query Run operations.

Fixture metadata identifies the next listed upcoming game, not a complete schedule. Statistical history ends in 2025; World Series context requires supporting records. Ten reviewed definitions link to their individual MLB glossary references. Unsupported conditions must be rejected or clarified, never removed to produce a generic answer. See [assistant.md](assistant.md).

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

Legacy biography and open-explanation modules are auxiliary and are not the same-chat assistant's factual answer path. They do not arbitrate structured statistics or extend the Published Query Catalog.
