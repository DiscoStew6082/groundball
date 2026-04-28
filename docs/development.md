# Development

## Setup

```bash
git clone <repo-url>
cd baseball-rag
uv sync
```

### Data Dependencies

The project requires MLB data from the Lahman-derived
`NeuML/baseballdata` dataset. Download once:

```bash
uv run python -m baseball_rag.db.download
```

This fetches CSV files into `data/` and regenerates `data/manifest.json`.
The CSVs are ignored by git; the manifest is tracked as the reproducible data
contract.

To regenerate the manifest from already-downloaded CSVs:

```bash
uv run python -m baseball_rag.db.download --manifest-only
```

### Corpus / Chroma Index

ChromaDB is only the local vector search index. It should be treated as
generated state, not source. The source corpus is the Markdown under
`src/baseball_rag/corpus/`.

Build the current curated index from checked-in Markdown only:

```bash
uv run python -m baseball_rag.corpus --static-only
```

Build the larger experimental index with generated player bios from DuckDB:

```bash
uv run python -m baseball_rag.corpus
```

For a full local rebuild from scratch:

```bash
uv run python -m baseball_rag.db.download
uv run python -m baseball_rag.corpus
uv run python -m baseball_rag.corpus diagnostics --persist-dir data
```

The diagnostics command reports the resolved `persist_dir`, whether the
`baseball_corpus` collection exists, indexed document count, category/doc-kind
counts, generated corpus manifest status/counts, and embedding environment/model
hints. It is intentionally tolerant of missing or partial indexes, so it is safe
to run while debugging an ingest failure:

```bash
uv run python -m baseball_rag.corpus diagnostics --persist-dir data
```

For the retrieval-only benchmark slice, run Chroma-backed eval cases once per
retrieval strategy:

```bash
uv run python -m evals.questions --all-strategies --retrieval-only
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LM_STUDIO_URL` | `http://localhost:1234/v1/chat/completions` | LLM endpoint for generation |
| `LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` | Embedding endpoint base URL |
| `LMSTUDIO_EMBEDDING_MODEL` | `text-embedding-kalm-embedding-gemma3-12b-2511-i1` | Embedding model used for Chroma ingest/retrieval |
| `CHROMA_PERSIST_DIR` | `data/` | Optional override for retrieval and diagnostics persist directory |

## Running Locally

```bash
# CLI (stat query — DuckDB)
uv run python -m baseball_rag.cli "who had the most RBIs in 1962"

# API server (port 8000)
uv run uvicorn baseball_rag.api.server:app --reload

# Web UI (port 7860)
uv run python -m baseball_rag.web_app
```

## Code Quality

### Lint

```bash
uv run ruff check src/ tests/
```

### Type Check

```bash
uv run mypy src/
```

### Tests

```bash
uv run pytest tests/ -v
```

### Coverage Report

```bash
uv run pytest --cov=baseball_rag --cov-report=term-missing
```

Coverage report is also generated as `coverage.xml` and `coverage.html` (see `.coverage` and `htmlcov/` after runs).

## CI Pipeline

`.github/workflows/ci.yml` runs three jobs in sequence:

| Job | Depends On | What it does |
|-----|------------|--------------|
| `lint` | — | `ruff check src/ tests/` |
| `typecheck` | — | `mypy src/` + type stubs |
| `test` | lint, typecheck | Unit pytest suite, deterministic eval release gate, reliability report artifacts/run summary, coverage artifact, and optional Codecov upload |

Python version: **3.11** (ubuntu-latest). All dependencies installed via pip (not uv) in CI to avoid PATH issues.

The CI release gate is deterministic-only:

```bash
python -m evals.questions --report eval-report.md --guardrail-report guardrail-coverage.md
```

This command skips cases that require LM Studio, Chroma, external LMs, or live model services. Live and Chroma-backed evals remain local/manual opt-ins via `--include-live`, `--strategy`, `--all-strategies`, or `--retrieval-only`.

CI also uploads `coverage.xml` as a workflow artifact. Codecov is useful reporting, but it is non-blocking so releases do not depend on external coverage upload availability.

## Project Conventions

- Package location: `src/baseball_rag/` (explicit package discovery via `[tool.hatch.build.targets.wheel]` in pyproject.toml)
- Tests live in `tests/`, mirror source layout
- DuckDB query tables are initialized lazily from downloaded CSVs.
- ChromaDB indexes are generated local state and are wiped/rebuilt on every corpus build.

## Adding a New Stat or Player

1. Create the markdown file in `src/baseball_rag/corpus/stat_definitions/` or `src/baseball_rag/corpus/hof/`
2. Rebuild: `uv run python -m baseball_rag.corpus --static-only`
3. No other changes needed — routing, retrieval, and prompts all derive from frontmatter automatically
