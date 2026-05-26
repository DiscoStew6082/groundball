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

ChromaDB indexing has been removed. Checked-in stat-definition Markdown remains
runtime grounding for supported stat-definition explanations.

For a full local data rebuild from scratch:

```bash
uv run python -m baseball_rag.db.download
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

# Short local UI entrypoint used by the Codex workflow (port 7861)
uv run baseball-rag-ui

# Web UI with a one-hour process TTL
uv run python -m baseball_rag.web_app --ttl-seconds 3600
```

## Code Quality

### Lint

```bash
uv run ruff check src/ tests/ evals/
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
| `lint` | - | `ruff check` across configured Python files, including `src/`, `tests/`, and `evals/` |
| `typecheck` | - | `mypy src/` + type stubs |
| `test` | lint, typecheck | Unit pytest suite, deterministic eval release gate, reliability report artifacts/run summary, coverage artifact, and optional Codecov upload |

Python version: **3.11** (ubuntu-latest). All dependencies installed via pip (not uv) in CI to avoid PATH issues.

The CI release gate is deterministic-only:

```bash
python -m evals.questions --report eval-report.md --guardrail-report guardrail-coverage.md --json-report eval-report.json --baseline evals/baseline.json
```

This command skips cases that require LM Studio or other live model services.
Live LLM evals remain local/manual opt-ins via `--include-live`.

The JSON report is compared to `evals/baseline.json`. Behavioral regressions block CI; dataset/model/prompt drift is reported as `WARN` so the baseline can be reviewed and refreshed deliberately.
The dataset audit hash is computed from the compact provenance payload that
answers expose, not from the CSV bytes alone. Refresh the baseline deliberately
when `data/manifest.json` file hashes still match NeuML/baseballdata but the
provenance payload changes, such as adding `source_authorities` metadata that
clarifies Lahman/DuckDB source roles.

CI also uploads `coverage.xml` as a workflow artifact. Codecov is useful reporting, but it is non-blocking so releases do not depend on external coverage upload availability.

## Regression Net

Use this checklist for PRs touching `service.py`, routing, stat queries, grounded
database templates/runtime, biography generation or verification, API payloads,
or the Gradio UI:

1. Run the full local gates:

   ```bash
   uv run ruff check src/ tests/ evals/
   uv run mypy src/
   uv run pytest tests/ -v
   ```

2. Run the product-critical focus suites:

   ```bash
   uv run pytest tests/test_service.py tests/test_player_bio_query.py tests/test_player_stat_claims_consensus.py tests/test_api.py -q
   ```

3. Run the deterministic eval release gate:

   ```bash
   uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json
   ```

4. Smoke the live UI in the Codex in-app Browser:

   ```bash
   uv run baseball-rag-ui
   ```

   Open `http://127.0.0.1:7861/`, run `who had the most RBIs in 1962`,
   and verify the answer, DuckDB source, SQL, rows, and Ask-button lifecycle.

5. Run a code review subagent and explicitly state whether intent names, API
   payload fields, SQL/source visibility, or eval baselines changed.

The product contract is authority-first: supported stat and grounded database
answers must carry DuckDB provenance with visible SQL and rows, and LLM-flavored
text must stay inside verified evidence.

## Governance Surfaces

The API exposes release and review surfaces for local demos:

- `GET /evals/report` returns the deterministic eval gate summary and Markdown report without writing files.
- `POST /evals/run` defaults to deterministic-only evals. `include_live=true` opts into cases that may require LM Studio.
- `GET /guardrails/coverage` returns manifest-only guardrail coverage through the package-safe eval manifest adapter, returning explicit unavailable metadata when the repo manifest is absent in a package-only runtime.
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
