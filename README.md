# Ground Ball

[![CI](https://github.com/DiscoStew6082/groundball/actions/workflows/ci.yml/badge.svg)](https://github.com/DiscoStew6082/groundball/actions/workflows/ci.yml)

Ground Ball is a local-first query engine for historical MLB data. Natural-language questions and structured Query Recipes compile to one closed, versioned Query Plan, execute against DuckDB, and return immutable rows with the exact SQL, bound values, source fingerprints, and release proof behind the result.

The primary query path is deterministic. It does not need an LLM, a network connection, or a machine-specific service.

## What is queryable

| Source | Rows | Fields |
| --- | ---: | ---: |
| People | 24,270 | 25 |
| Batting | 128,598 | 22 |
| Pitching | 57,630 | 30 |
| Fielding | 174,332 | 18 |
| TeamReference | 3,613 | 3 |

Every loaded field and row is reachable through discovery, filtering, stable pagination, or export. Promoted values add reviewed baseball semantics such as AVG, OPS, leader ranking, tie handling, grain-aware aggregation, and cross-discipline relationships. Arbitrary SQL and formulas are rejected.

Retrosheet event queries are a separate, explicitly bounded capability. Player biographies and open explanations remain auxiliary and do not arbitrate structured query facts.

## Architecture

```text
Natural-language question or Query Recipe
                  |
          Recipe Adapter
                  |
       Query Plan v1 validator
                  |
     constrained DuckDB compiler
                  |
 Rows / NoData / Exported + QueryEvidence
                  |
    HTTP, CLI, and Svelte adapters
```

The Published Query Catalog under `src/baseball_rag/query/catalog/` is the capability authority. Public mode is composed through injected `PublicAppBindings`; this repository contains no concrete hosting adapter. Missing public bindings fail closed.

## Run locally

```bash
uv sync
npm --prefix web ci
npm --prefix web run build
uv run groundball-ui
```

Open <http://127.0.0.1:7861/> or use the CLI:

```bash
uv run groundball query "who had the most RBIs in 1962"
uv run groundball fields --source Batting --search GIDP
uv run groundball capabilities retrosheet-events
```

Use the JSON API:

```bash
curl -s http://127.0.0.1:7861/api/query-runs \
  -H 'content-type: application/json' \
  -d '{"question":"Aaron Judge OPS in 2022"}'
```

## Release proof

The checked-in Coverage Report covers 5,253 obligations across catalog identity, raw reachability, promoted exactness, compiler safety, evidence integrity, and deterministic offline independence.

```bash
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python -m baseball_rag.coverage_proof_validator
uv run python -m baseball_rag.query.eval_matrix
uv run python scripts/check_provider_neutrality.py --root .
```

The Release Bundle is assembled from an exact source commit. A valid Release Artifact is a direct child commit that changes only `release/bundle/**`. Public CI verifies that topology, bundle identity, deterministic query parity, package synchronization, generic network-disabled container behavior, and neutrality without deployment credentials or external runtime actions.

## Data and provenance

The structured data is derived from [`NeuML/baseballdata`](https://huggingface.co/datasets/NeuML/baseballdata), a Lahman Baseball Database distribution. `data/manifest.json` records source URLs, row counts, checksums, coverage, and license metadata. Retrosheet-derived projections retain their own provenance and legal records.

Populate or refresh local CSVs with:

```bash
uv run python -m baseball_rag.db.download
```

See [CONTEXT.md](CONTEXT.md), [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), [docs/development.md](docs/development.md), and [docs/release-artifacts.md](docs/release-artifacts.md).
