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

### Corpus Material

ChromaDB indexing has been removed. Checked-in Markdown under
`src/baseball_rag/corpus/` remains project material for docs/tests, but it is
not runtime grounding for stat explanations or player biographies.

For a full local data rebuild from scratch:

```bash
uv run python -m baseball_rag.db.download
uv run python -m baseball_rag.corpus diagnostics --persist-dir data
```

The diagnostics command reports checked-in corpus counts, old ignored manifest
state when present, and runtime flags that no vector index is required:

```bash
uv run python -m baseball_rag.corpus diagnostics --persist-dir data
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LMSTUDIO_BASE_URL` | `http://localhost:1234/v1` | OpenAI-compatible LM Studio base URL |
| `LMSTUDIO_MODEL` | `google/gemma-4-26b-a4b` | Model name sent to LM Studio |
| `LMSTUDIO_TIMEOUT_SECONDS` | `20` | Request timeout for LM Studio calls |
| `BASEBALL_RAG_REVIEW_QUEUE_PATH` | `data/review_queue.jsonl` | Optional override for the API-owned human review queue |
| `BASEBALL_RAG_WEB_APP_TTL_SECONDS` | unset | Optional Gradio web-app process time to live; `0` disables it |

## Running Locally

```bash
# CLI (stat query — DuckDB)
uv run python -m baseball_rag.cli "who had the most RBIs in 1962"

# API server (port 8000)
uv run uvicorn baseball_rag.api.server:app --reload

# Web UI (port 7860)
uv run python -m baseball_rag.web_app

# Web UI with a one-hour process TTL
uv run python -m baseball_rag.web_app --ttl-seconds 3600
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
python -m evals.questions --report eval-report.md --guardrail-report guardrail-coverage.md --json-report eval-report.json --baseline evals/baseline.json
```

This command skips cases that require LM Studio or other live model services.
Live LLM evals remain local/manual opt-ins via `--include-live`.

The JSON report is compared to `evals/baseline.json`. Behavioral regressions block CI; dataset/model/prompt drift is reported as `WARN` so the baseline can be reviewed and refreshed deliberately.

CI also uploads `coverage.xml` as a workflow artifact. Codecov is useful reporting, but it is non-blocking so releases do not depend on external coverage upload availability.

## Governance Surfaces

The API exposes release and review surfaces for local demos:

- `GET /evals/report` returns the deterministic eval gate summary and Markdown report without writing files.
- `POST /evals/run` defaults to deterministic-only evals. `include_live=true` opts into cases that may require LM Studio.
- `GET /guardrails/coverage` returns manifest-only guardrail coverage from `evals/questions.yaml`.
- `GET /review-queue` and `PATCH /review-queue/{item_id}` list, resolve, or dismiss API-created review items.

Only `/query` writes review queue items. CLI and Gradio calls do not persist review state.

## Project Conventions

- Package location: `src/baseball_rag/` (explicit package discovery via `[tool.hatch.build.targets.wheel]` in pyproject.toml)
- Tests live in `tests/`, mirror source layout
- DuckDB query tables are initialized lazily from downloaded CSVs.
- ChromaDB indexes are no longer generated or required.

## Adding a New Stat or Player

1. Add or update registered structured stats in `src/baseball_rag/db/stat_registry.py`.
2. Add focused tests for the public question-answering behavior.
3. For biography verification, ensure the stat can be queried from DuckDB before asking the LLM to emit it as a supported claim.
