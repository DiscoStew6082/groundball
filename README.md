# Ground Ball

[![CI](https://github.com/DiscoStew6082/groundball/actions/workflows/ci.yml/badge.svg)](https://github.com/DiscoStew6082/groundball/actions/workflows/ci.yml)

Ground Ball is a local-first query engine for historical MLB data. Natural-language questions and structured Query Recipes compile to one closed, versioned Query Plan, execute against DuckDB, and return immutable rows with the exact SQL, bound values, source fingerprints, and release proof behind the result.

The primary query path is deterministic. It does not need an LLM, a network connection, or a Mac-specific service.

## What is queryable

The published catalog exposes every loaded field and row from these sources:

| Source | Rows | Fields |
| --- | ---: | ---: |
| People | 24,270 | 25 |
| Batting | 128,598 | 22 |
| Pitching | 57,630 | 30 |
| Fielding | 174,332 | 18 |
| TeamReference | 3,613 | 3 |

Raw fields support discovery, filtering, stable pagination, and export. Promoted values add reviewed baseball semantics such as AVG, OPS, leader ranking, tie handling, grain-aware aggregation, and cross-discipline relationships. Arbitrary SQL and arbitrary formulas are rejected.

Retrosheet event queries are a separate, explicitly bounded capability. Player biographies and open explanations remain auxiliary features; neither arbitrates structured query facts.

## Architecture

```text
Natural-language question or Query Recipe
                  |
                  v
          Recipe Adapter
                  |
                  v
       Query Plan v1 validator
                  |
                  v
     constrained DuckDB compiler
                  |
                  v
 Rows / NoData / Exported + QueryEvidence
                  |
                  v
    HTTP, CLI, and Svelte adapters
```

The catalog under `src/baseball_rag/query/catalog/` is the capability authority. `src/baseball_rag/query/` owns contracts, planning, compilation, execution, evidence, and the completeness proof. There is no legacy router, stat registry, template query stack, compatibility request lifecycle, or Go verifier.

## Run it

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

The response is an explicit outcome such as `rows`, `no_data`, `needs_clarification`, `rejected`, `unavailable`, `failed`, or `exported`. Factual results are returned only when the checked-in Coverage Report matches the catalog, compiler, eval matrix, data release, and source fingerprints.

## Release proof

The canonical report is generated, not hand-maintained:

```bash
uv run python -m baseball_rag.query.generate_coverage_report
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python -m baseball_rag.query.eval_matrix
```

The current proof covers 5,253 obligations across six release-blocking gates:

- catalog and schema identity
- raw field and full-row reachability
- promoted semantic exactness
- plan/compiler safety
- outcome and evidence integrity
- zero-LLM, zero-network, zero-Mac independence

Human and machine views are served at `/coverage-report` and `/api/query-coverage`. CI regenerates the proof, runs the deterministic 17-case query matrix, and uploads both report forms.

## Data and provenance

The packaged structured data is derived from [`NeuML/baseballdata`](https://huggingface.co/datasets/NeuML/baseballdata), a Lahman Baseball Database distribution. `data/manifest.json` records source URLs, row counts, checksums, coverage, and license metadata. Query compatibility uses a semantic manifest hash, so volatile download timestamps do not invalidate identical data while any source-content change does.

Populate or refresh local CSVs with:

```bash
uv run python -m baseball_rag.db.download
```

See [CONTEXT.md](CONTEXT.md), [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), and [docs/development.md](docs/development.md).
