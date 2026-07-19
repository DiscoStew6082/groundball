# Development

## Setup

```bash
uv sync
npm --prefix web ci
uv run python -m baseball_rag.db.download
```

The CSVs and generated DuckDB files are local state. `data/manifest.json`, catalog assets, and the generated Coverage Report are tracked release contracts.

## Run

```bash
npm --prefix web run build
uv run groundball-ui
```

Open `http://127.0.0.1:7861/`. For frontend iteration, run `npm --prefix web run dev` alongside the API server.

## Generated contracts

Regenerate after changing their inputs:

```bash
uv run python -m baseball_rag.query.generate_catalog_compatibility
uv run python -m baseball_rag.query.generate_raw_inventory
uv run python -m baseball_rag.query.generate_team_reference --teams /path/to/official/Teams.csv
uv run python -m baseball_rag.db.generate_retrosheet_team_reference \
  --teams /path/to/official/Teams.csv \
  --retrosheet-teams /path/to/retrosheet-team-catalog.txt
uv run python -m baseball_rag.query.generate_coverage_report
```

The Coverage Report fingerprints all query Python modules and the deterministic eval matrix. Any change to those files requires regeneration.

## Validation

```bash
uv run ruff format --check src/ tests/
uv run ruff check src/ tests/
uv run mypy src/baseball_rag/
uv run pytest tests/ -m 'not llm and not release_proof' -q
uv run python -m baseball_rag.coverage_proof_validator
uv run python -m baseball_rag.query.eval_matrix
uv run python -m baseball_rag.query.generate_catalog_compatibility --check
uv run python -m baseball_rag.query.generate_raw_inventory --check
uv run python -m baseball_rag.query.generate_coverage_report --check
npm --prefix web test
npm --prefix web run build
```

Fast CI runs the non-LLM, non-release-proof suite and validates the exact checked-in proof. The path-scoped Release Proof workflow runs the offline release test, regenerates all 5,253 obligations, and uploads `coverage-report.json` and `coverage-report.md`. There is no baseline-refresh workflow and no Go verifier.

## Browser acceptance

Use the Codex in-app Browser with the integrated server. At minimum verify:

- `who had the most RBIs in 1962` returns Tommy Davis, 153.
- the 40-40 recipe returns exactly six players.
- raw `Batting.GIDP` discovery and execution work.
- Aaron Judge 2022 OPS exposes formula and evidence.
- ambiguous strikeouts request clarification inline.
- arbitrary formulas are rejected.
- export downloads the exact result snapshot.
- the Coverage Report opens and reports all obligations covered.
- no page-level horizontal overflow occurs at 360, 390, or 430 CSS pixels; desktop remains correct at 1024 and 1440.

Leave the local server running after the smoke for handoff.

## Change rules

- Use TDD.
- Run an independent code-review subagent after each task.
- Do not introduce a second stat/query registry beside the Published Query Catalog.
- Do not restore deleted compatibility routes or facades.
- Commit all intended changes, explain any unstaged files, push, and wait for green CI.
