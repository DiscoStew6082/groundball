# Five-Minute AI Governance Demo

This walkthrough shows Baseball RAG as an eval-gated, audit-ready AI assistant rather than a generic chatbot. It uses deterministic commands by default, so it does not require LM Studio, external LMs, or live services.

## 1. Run The Deterministic Release Gate

```bash
uv run python -m evals.questions \
  --report docs/eval-report.md \
  --guardrail-report docs/guardrail-coverage.md \
  --json-report docs/eval-report.json \
  --baseline evals/baseline.json
```

Expected headline:

```text
evals: 20 passed, 0 failed, 48 skipped
```

Show:

- [docs/eval-report.md](eval-report.md): pass rate, release recommendation, skipped live cases, risk categories, and baseline comparison.
- [docs/eval-report.json](eval-report.json): machine-readable artifact for CI and baseline review.
- [docs/guardrail-coverage.md](guardrail-coverage.md): unsupported-case, SQL safety, and provenance coverage.

Talking point: skipped cases are intentional. CI gates only deterministic cases; live LLM evals stay manual opt-ins.

## 2. Confirm CI-Safe Quality Checks

```bash
uv run ruff check
uv run pytest tests/ --ignore=tests/test_db_download.py -m "unit and not llm" -q
```

Talking point: the release gate and core tests do not depend on LM Studio or external model services.

## 3. Start The API

```bash
uv run uvicorn baseball_rag.api.server:app --reload
```

## 4. Show Governance Endpoints

```bash
curl -s http://127.0.0.1:8000/evals/report | jq '.summary'
curl -s http://127.0.0.1:8000/guardrails/coverage | jq '.summary'
```

Show the explicit live eval opt-in:

```bash
curl -s http://127.0.0.1:8000/evals/run \
  -H 'content-type: application/json' \
  -d '{"include_live": true}' | jq '.warnings'
```

Talking point: non-deterministic eval modes are explicit opt-ins, not accidental CI dependencies.

## 5. Show Audit-Ready Query Metadata

```bash
curl -s http://127.0.0.1:8000/query \
  -H 'content-type: application/json' \
  -d '{"question":"who had the most RBIs in 1962"}' | jq '.metadata'
```

Call out:

- `query_id`: deterministic request identifier.
- `route` and `unsupported`: how the system handled the query.
- `sql.template_hash`, `parameterized`, `row_count`: SQL visibility without interpolated params.
- `dataset`: provenance version and manifest hash.
- `model.prompt_version`: prompt/version traceability.
- `eval.case_id`: exact match to the eval manifest when available.
- `latency_ms` and `trace`: operational observability.

## 6. Show Human Review Queue

Create an unsupported item:

```bash
curl -s http://127.0.0.1:8000/query \
  -H 'content-type: application/json' \
  -d '{"question":"which team should I bet on tonight"}' | jq '.review'
```

List the queue:

```bash
curl -s http://127.0.0.1:8000/review-queue | jq
```

Resolve the item:

```bash
curl -s -X PATCH http://127.0.0.1:8000/review-queue/<item_id> \
  -H 'content-type: application/json' \
  -d '{"status":"resolved","note":"Correctly rejected betting advice"}' | jq
```

Talking point: unsupported or ambiguous answers are not just rejected; they can be routed into a human review workflow.

## Close With The Positioning

Use this one-sentence framing:

> Baseball RAG is a grounded baseball analytics assistant, but the portfolio story is the release-confidence framework: deterministic eval gates, guardrail coverage, audit-ready provenance, and human-in-the-loop review.
