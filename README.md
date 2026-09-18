# Ground Ball

[![CI](https://github.com/DiscoStew6082/groundball/actions/workflows/ci.yml/badge.svg)](https://github.com/DiscoStew6082/groundball/actions/workflows/ci.yml)

Ground Ball answers baseball questions with cited sources and verified historical MLB statistics in one chat. Statistical questions and structured Query Recipes compile to a closed, versioned Query Plan, execute against DuckDB, and return immutable rows with SQL, bound values, source fingerprints, and release proof.

The structured query engine is deterministic and works without an LLM or network connection. Optional question interpretation uses a model only to select a validated recipe or bounded research request. Public application code constructs factual answers from evidence.

## Sourced assistant

When the optional assistant bindings are available, the same chat supports:

- Historical context for one MLB team, using the verified statistical release through 2025.
- Context for that team's next listed upcoming game, with dated historical statistics and supported World Series meetings. Fixture coverage is limited and start times can change.
- Historical comparisons combined with sourced explanations, and follow-ups about a referenced World Series.
- Current regular-season HR, RBI and stolen-base leaders, plus tentative probable pitchers for the next game, when current-source callbacks are available.
- Ten reviewed stat definitions: 2B, AVG, BB, ERA, HR, OPS, PO, RBI, SB, and WHIP, each linked to its MLB glossary source.

Answers contain at most five fact cards with citations, expandable source records, observation times, scope limits, and visible attribution. Full answer JSON downloads and history stay in the browser. Missing evidence can produce fewer facts or an unavailable response. Injuries, news, live statistics beyond the listed leaderboards, and unsupported date constraints are declined. A multi-part request is answered only when every part can be supported. See [assistant scope and evidence](docs/assistant.md).

## What is queryable

| Source | Rows | Fields |
| --- | ---: | ---: |
| People | 24,270 | 25 |
| Batting | 128,598 | 22 |
| Pitching | 57,630 | 30 |
| Fielding | 174,332 | 18 |
| TeamReference | 3,613 | 3 |

Every loaded field and row is reachable through discovery, filtering, stable pagination, or export. Promoted values add reviewed baseball semantics such as AVG, OPS, leader ranking, tie handling, grain-aware aggregation, and cross-discipline relationships. Arbitrary SQL and formulas are rejected.

Retrosheet event queries remain a separate, explicitly bounded capability. Assistant statistics reuse the same verified Query Runs; model output and external records do not define new statistical capabilities.

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

The Published Query Catalog under `src/baseball_rag/query/catalog/` is the structured-query capability authority. This repository also owns the interpretation prompt/schema and sourced answer construction. The outer runtime injects model transport and bounded source callbacks. Public mode is composed through injected `PublicAppBindings`; missing public bindings fail closed. See [architecture](docs/architecture.md).

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

The Release Bundle is assembled from an exact source commit. A valid Release Artifact is a direct child commit that changes only `release/bundle/**`. Public CI verifies that topology, bundle identity, deterministic query parity, source and distribution builds, package synchronization, and neutrality without deployment credentials or external runtime actions.

## Data and provenance

The structured data is derived from [`NeuML/baseballdata`](https://huggingface.co/datasets/NeuML/baseballdata), a Lahman Baseball Database distribution. `data/manifest.json` records source URLs, row counts, checksums, coverage, and license metadata. Retrosheet-derived projections retain their own provenance and legal records.

**Retrosheet credit**

The information used here was obtained free of charge from and is copyrighted by Retrosheet. Interested parties may contact Retrosheet at "www.retrosheet.org".

[Retrosheet](https://www.retrosheet.org/) supplies historical records used by supported event queries and World Series context. Required credits travel with answers and downloadable evidence. See [source attribution](docs/source-attribution.md).

Populate or refresh local CSVs with:

```bash
uv run python -m baseball_rag.db.download
```

See [CONTEXT.md](CONTEXT.md), [docs/architecture.md](docs/architecture.md), [docs/api.md](docs/api.md), [docs/development.md](docs/development.md), and [docs/release-artifacts.md](docs/release-artifacts.md).
