# Development

## Setup

```bash
uv sync
npm --prefix web ci
uv run python -m baseball_rag.db.download
```

The CSVs and generated DuckDB files are local state. `data/manifest.json`, catalog assets, generated Coverage Report, packaged web assets, and Release Bundle are tracked contracts.

## Run

```bash
npm --prefix web run build
uv run groundball-ui
```

Open `http://127.0.0.1:7861/`. For frontend iteration, run `npm --prefix web run dev` alongside the API server.

## Generated contracts

```bash
uv run python -m baseball_rag.query.generate_catalog_compatibility
uv run python -m baseball_rag.query.generate_raw_inventory
uv run python -m baseball_rag.query.generate_coverage_report
npm --prefix web run build
npm --prefix web run package:sync
```

The Coverage Report fingerprints query modules and the deterministic eval matrix. Rebuild and package the web application rather than hand-editing `src/baseball_rag/web_dist/`.

## Validation

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/baseball_rag/
uv run pytest tests/ -m 'not release_proof' -q
uv run python -m baseball_rag.coverage_proof_validator
uv run python -m baseball_rag.query.eval_matrix
uv run python -m baseball_rag.query.generate_catalog_compatibility --check
uv run python -m baseball_rag.query.generate_raw_inventory --check
uv run python -m baseball_rag.query.generate_coverage_report --check
uv run python scripts/check_provider_neutrality.py --root .
npm --prefix web test
npm --prefix web run build
npm --prefix web run package:check
```

Ordinary CI runs dependency, lint, type, web, test, package-parity, and neutrality gates. Release Proof owns exhaustive coverage regeneration. Release Artifact Proof owns exact source-to-bundle topology, deterministic packaged behavior, generic network-disabled container proof, and artifact neutrality.

## Release assembly

Follow [release-artifacts.md](release-artifacts.md). Commit generated source artifacts first, record that full source SHA, assemble the bundle from that exact tree, and make one direct child commit containing only `release/bundle/**`.

## Change rules

- Use TDD for behavior changes.
- Preserve the Published Query Catalog as the sole structured-query authority.
- Keep public source free of concrete hosting adapters, credentials, and deployment tooling.
- Do not restore deleted compatibility routes or facades.
- Regenerate artifacts from their source; do not hand-edit generated JavaScript.
