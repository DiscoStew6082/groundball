# Ground Ball Context

This is the canonical current architecture and domain context. Historical implementation ledgers live under `docs/archive/architecture/`; they are evidence, not current interfaces.

## Product contract

- Ground Ball is a local-first historical MLB query engine.
- Every loaded primary Lahman field and row is discoverable and reachable through filtering, stable pagination, or export. The synthesized TeamReference source has the same guarantee.
- The Published Query Catalog is the only structured-query capability authority.
- A Query Recipe is the visible, editable request. It may be incomplete or ambiguous.
- Query Plan v1 is the closed, deterministic, serializable meaning of a validated recipe. It contains no user SQL and no executable code.
- The compiler owns identifiers and emits parameterized DuckDB SQL. User values are bound data.
- QueryEvidence binds every factual outcome to the canonical plan, catalog revision, data release, SQL, bound values, immutable result fingerprint, and source fingerprints.
- A factual adapter result is available only when the checked-in Coverage Report passes and matches the runtime exactly.
- Retrosheet event queries are separately governed and do not extend the Lahman query catalog implicitly.
- Biography generation and open explanation are auxiliary. Lahman/DuckDB remains primary for extractable biography stat claims; Retrosheet may contribute optional consensus evidence.
- There is no backwards-compatibility contract for deleted request, routing, stat-registry, grounded-template, review-queue, eval-manifest, or Go-verifier surfaces.

## Current modules

- `src/baseball_rag/query/contracts.py`: recipe, plan, outcomes, and evidence types.
- `src/baseball_rag/query/registry.py`: catalog-backed discovery and semantic bindings.
- `src/baseball_rag/query/recipe_adapter.py`: reviewed natural-language and named-recipe interpretation.
- `src/baseball_rag/query/service.py`: plan and execute entry points.
- `src/baseball_rag/query/compiler.py`: constrained SQL compiler.
- `src/baseball_rag/query/runtime.py`: packaged DuckDB data runtime and compatibility enforcement.
- `src/baseball_rag/query/coverage.py`: proof identity, validation, and verification binding.
- `src/baseball_rag/query/adapters.py`: shared rendering-neutral HTTP, CLI, and browser payloads.
- `src/baseball_rag/retrosheet_query.py`: separate deterministic Retrosheet adapter.
- `src/baseball_rag/api/server.py`: FastAPI routes and built Svelte application.

## Release gates

The generated Coverage Report is the release proof. It contains six fixed gates and currently covers 5,253 obligations with zero uncovered. Its identity includes the report schema, complete catalog assets, semantic data manifest, query compiler contract sources, deterministic eval matrix, source row fingerprints, and data release.

Required checks:

```bash
uv run python -m baseball_rag.query.generate_catalog_compatibility --check
uv run python -m baseball_rag.query.generate_raw_inventory --check
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python -m baseball_rag.query.eval_matrix
uv run pytest tests/ -m 'not llm' -q
npm --prefix web test
npm --prefix web run build
```

## Working rules

- Use TDD for development work.
- Use subagents where possible and run an independent code-review subagent after every task.
- Do not restore a deleted compatibility facade without an explicit product decision.
- Regenerate the Coverage Report after any catalog, query implementation, or eval-matrix change.
- Keep the browser smoke at `http://127.0.0.1:7861/`; verify `who had the most RBIs in 1962` returns Tommy Davis with 153 RBI.
- A coding task is complete only after review, commit, push, green CI, and an explanation of any remaining unstaged changes.
