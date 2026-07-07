# API Reference

FastAPI server exposing Groundball's almanac query pipeline over HTTP.

## Start the Server

```bash
uv run uvicorn baseball_rag.api.server:app --reload --port 8001
```

Groundball local API port: **8001** (`--reload` enables auto-reload on code changes).

## Browser Origins

The production website calls Groundball through a same-origin Cloudflare Pages
Function at `/groundball/query`, so the browser does not need to call the Tunnel
hostname directly. For local or direct-review paths, the API allows browser CORS
requests to `POST /query` from `GROUNDBALL_CORS_ORIGINS`. By default that
includes `https://discostew.dev` and local Astro review origins on port `4321`.

For the Cloudflare Tunnel profile:

```bash
export GROUNDBALL_CORS_ORIGINS=https://discostew.dev,http://localhost:4321,http://127.0.0.1:4321
```

The browser-facing page should call only same-origin `/groundball/query`;
that Pages Function forwards to `https://groundball.discostew.dev/query`. LM
Studio remains local-only. Operator endpoints such as `/evals/*` and
`/review-queue` do not receive browser CORS headers.

## Endpoints

### `GET /health`

Health check. No authentication required.

**Response**
```json
{ "status": "ok" }
```

---

### `GET /health/verification`

Operational verification readiness. No authentication required. This endpoint is
deterministic and does not call the LLM.

**Response**
```json
{
  "status": "ok",
  "checks": [
    {
      "name": "data_manifest",
      "status": "ok",
      "detail": "Primary manifest loaded for NeuML/baseballdata."
    },
    {
      "name": "duckdb_core_tables",
      "status": "ok",
      "detail": "DuckDB core tables are queryable."
    },
    {
      "name": "guardrail_manifest",
      "status": "ok",
      "detail": "Guardrail manifest loaded with deterministic and unsupported cases."
    }
  ],
  "commands": {
    "focused": "uv run pytest tests/test_api.py -q",
    "full": "uv run pytest -q",
    "eval_gate": "uv run python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json",
    "browser_smoke": "uv run groundball-ui"
  }
}
```

---

### `POST /query`

Ask a baseball question and get a grounded answer with provenance metadata.

**Request**

```json
{
  "question": "who had the most RBIs in 1962",
  "answer_mode": "stats_only"
}
```

**Response**

```json
{
  "answer": "Top RBI leaders (1962-1962):\n  1. Tommy Davis: 153 RBI\n  2. ...",
  "intent": "stat_query",
  "sources": [
    {
      "type": "duckdb",
      "label": "RBI leaderboard for 1962-1962",
      "detail": "Tables: batting, people. Dataset: local Hugging Face NeuML/baseballdata CSVs.",
      "sql": "SELECT p.nameLast || ', ' || p.nameFirst AS name, SUM(<stat>) AS stat_value FROM batting b JOIN people p ON b.playerID = p.playerID WHERE b.yearID >= ? AND b.yearID <= ? GROUP BY p.nameLast, p.nameFirst ORDER BY stat_value DESC LIMIT 10",
      "rows": [
        { "name": "Davis, Tommy", "team": "Range", "stat_value": 153 }
      ],
      "columns": [],
      "score": null,
      "data_manifest": {
        "dataset": {
          "name": "NeuML/baseballdata",
          "license": "CC BY-SA 3.0"
        },
        "coverage": {
          "structured_stat_years": { "min": 1871, "max": 2025 }
        },
        "files": [
          {
            "path": "data/Batting.csv",
            "table": "batting",
            "rows": 128598,
            "sha256": "007551e2fe3072aff396a8573de61dceabe14dbf8de20038c8b60e2abe16978f"
          }
        ]
      }
    }
  ],
  "warnings": [],
  "unsupported": false,
  "review": null,
  "metadata": {
    "answer_mode": "stats_only",
    "query_id": "q_0c9ab4d71dfcb6ec",
    "timestamp": "2026-04-28T12:00:00+00:00",
    "route": "stat_query",
    "unsupported": false,
    "unsupported_reason": null,
    "source_count": 1,
    "source_types": ["duckdb"],
    "source_labels": ["RBI leaderboard for 1962-1962"],
    "sql_visible": true,
    "sql": {
      "template": "SELECT ... WHERE b.yearID >= ? AND b.yearID <= ? ...",
      "template_hash": "sql_3f0c8e2cc6d1a8bb",
      "parameterized": true,
      "params_count": 2,
      "row_count": 10,
      "truncated": false,
      "source_label": "RBI leaderboard for 1962-1962"
    },
    "model": {
      "name": "local-llm",
      "prompt_version": "grounded-answer-v1"
    },
    "dataset": {
      "name": "NeuML/baseballdata",
      "version": "manifest",
      "downloaded_at": "2026-04-20T13:29:00-04:00",
      "hash": "manifest_..."
    },
    "eval": {
      "matched": true,
      "case_id": "stat_rbi_1962",
      "category": "stat_query"
    },
    "latency_ms": 8.4,
    "trace": {
      "route_type": "stat_query",
      "total_ms": 8.4,
      "stages": [
        { "component_id": "query-router", "label": "Route Query", "elapsed_ms": 0.2 },
        { "component_id": "duckdb", "label": "DB Query", "elapsed_ms": 8.2 }
      ]
    }
  }
}
```

| Field | Type | Description |
|-------|------|-------------|
| `question` | string | Natural language baseball question |
| `answer_mode` | string | Optional answer mode. `stats_only` returns the preformatted verified stats. `llm_flavored` gives the LLM the verified DuckDB result and returns prose while preserving source provenance. |

**Response fields**

| Field | Type | Description |
|-------|------|-------------|
| `answer` | string | Full answer text (preformatted verified stats or LLM-flavored prose, depending on `answer_mode` and route) |
| `intent` | string | Router intent used to answer the question |
| `sources` | array | DuckDB evidence or verification records used to ground the answer |
| `warnings` | array | Non-fatal caveats, such as truncated results or LLM-backed open explanation errors |
| `unsupported` | boolean | True when the system could not answer from grounded evidence |
| `review` | object/null | Human review queue hint for unsupported or ambiguous answers |
| `metadata` | object | Additive audit metadata for request ID, timestamp, route, unsupported reason, source summary, SQL template/hash, dataset/model versions, exact eval match when available, latency, and trace stages |
| `sources[].data_manifest` | object/null | Dataset source, checksums, row counts, coverage, download metadata, license notes, `source_authorities`, and optional `consensus_sources` plus `secondary_manifests.retrosheet` availability details for biography stat-claim evidence |

`metadata.eval.status` is omitted for normal repo-manifest matches. If the eval
manifest is absent in a package-only runtime, `metadata.eval.status` is
`"unavailable"` and the payload includes a reason instead of importing the
repo-only `evals` package.

`sources[].data_manifest.source_authorities` is the authority catalog used by
answer payloads. Lahman/DuckDB is the primary factual/stat authority for
structured stat answers, grounded database answers, player identity, and primary
biography stat-claim verification. Retrosheet is optional secondary consensus
evidence and appears only on biography stat-claim consensus payloads.

---

### `GET /evals/report`

Run the deterministic eval release gate and return JSON plus Markdown. The endpoint does not write report files and does not require LM Studio, external LMs, or live services by default.

`GET /evals/report` and `POST /evals/run` share the same report payload builder
for artifact-derived summary and case lists, so API governance payloads and
checked-in eval artifacts stay aligned without claiming identical top-level
schemas.

**Query parameters**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `include_live` | boolean | `false` | Include live/manual eval cases. This may require local LM Studio services. |

**Response**

```json
{
  "ok": true,
  "mode": "answer",
  "include_live": false,
  "minimum_pass_rate": 0.85,
  "summary": {
    "cases_loaded": 70,
    "attempted": 26,
    "passed": 26,
    "failed": 0,
    "skipped": 44,
    "pass_rate": 1.0,
    "recommendation": "PASS",
    "release_recommendation": "PASS - deterministic release gate is green"
  },
  "results": {
    "passed": [],
    "failed": [],
    "skipped": []
  },
  "failed": [],
  "skipped": [],
  "warnings": [],
  "markdown": "# Groundball Eval Report\n..."
}
```

---

### `POST /evals/run`

Run evals with explicit options. An empty body `{}` runs the same deterministic release gate as `GET /evals/report`.

`include_live=true` opts into cases that may require LM Studio. There are no retrieval strategy options.

**Request**

```json
{
  "include_live": false
}
```

**Common responses**

| Status | Condition |
|--------|-----------|
| 200 OK | Deterministic eval run completed |
| 422 Unprocessable Entity | Invalid request body |

---

### `GET /guardrails/coverage`

Return manifest-only guardrail coverage generated through the package-safe eval
manifest adapter from `evals/questions.yaml` when the repo manifest is present.
This endpoint does not touch DuckDB, LM Studio, or live services. In a
package-only runtime where the manifest is absent, it returns `status: "unavailable"`
with a reason and empty coverage counts.

**Response**

```json
{
  "summary": {
    "ci_safe_deterministic_guardrails": 11,
    "unsupported_guardrails": 18,
    "sql_safety": 12,
    "provenance_source_visibility": 43,
    "live_manual_guardrail_cases": 0
  },
  "categories": {
    "unsupported": [],
    "sql_safety": [],
    "provenance_source_visibility": [],
    "live_manual": []
  },
  "markdown": "# Groundball Guardrail Coverage\n..."
}
```

**Package-only unavailable response**

```json
{
  "status": "unavailable",
  "reason": "Guardrail manifest is unavailable at /path/to/evals/questions.yaml.",
  "summary": {
    "ci_safe_deterministic_guardrails": 0,
    "unsupported_guardrails": 0,
    "sql_safety": 0,
    "provenance_source_visibility": 0,
    "live_manual_guardrail_cases": 0
  },
  "categories": {
    "unsupported": [],
    "sql_safety": [],
    "provenance_source_visibility": [],
    "live_manual": []
  },
  "markdown": "# Groundball Guardrail Coverage\n..."
}
```

---

### `GET /review-queue`

Return the latest local human-review queue snapshots. The queue is append-only JSONL at `data/review_queue.jsonl` by default; set `GROUNDBALL_REVIEW_QUEUE_PATH` to override it. `BASEBALL_RAG_REVIEW_QUEUE_PATH` remains a compatibility alias.

**Query parameters**

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `status` | `open`, `resolved`, `dismissed`, `all` | `open` | Filter the latest snapshot for each item |

**Response**

```json
{
  "count": 1,
  "items": [
    {
      "id": "review_...",
      "question": "how many HRs did Totally Fakeplayer have in 2022",
      "answer_id": "q_...",
      "status": "open",
      "reason": "unsupported",
      "audit": {},
      "created_at": "2026-04-28T12:00:00+00:00",
      "resolved_at": null,
      "resolution_note": null
    }
  ]
}
```

---

### `PATCH /review-queue/{item_id}`

Resolve or dismiss an existing review item by appending a new latest snapshot.

**Request**

```json
{
  "status": "resolved",
  "note": "Expected unsupported guardrail"
}
```

**Common responses**

| Status | Condition |
|--------|-----------|
| 200 OK | Item resolved or dismissed |
| 404 Not Found | Unknown review item |
| 422 Unprocessable Entity | Invalid status |

---

### `GET /sources`

Return the complete local dataset provenance manifest.

**Response**

```json
{
  "dataset": {
    "name": "NeuML/baseballdata",
    "source_url": "https://huggingface.co/datasets/NeuML/baseballdata",
    "license": "CC BY-SA 3.0"
  },
  "download": {
    "downloaded_at": "2026-04-20T13:29:00-04:00"
  },
  "coverage": {
    "structured_stat_years": { "min": 1871, "max": 2025 }
  },
  "files": []
}
```

## Error Responses

| Status | Condition |
|--------|-----------|
| 422 Unprocessable Entity | Missing or invalid request body |
| 500 Internal Server Error | Unexpected DuckDB, LLM, or server error |

## Architecture Note

The `/query` endpoint calls the shared answer service. The CLI renders the same
structured answer as text, while the API returns the full JSON payload:

1. **Stat query** -> DuckDB lookup with registered stat whitelist
2. **Grounded database question** -> typed query spec -> parameterized SQL -> DuckDB
3. **Player biography** -> DuckDB identity resolution + LLM JSON generation + Lahman/Retrosheet stat-claim consensus when available
4. **General question** -> local stat definition when supported, otherwise LLM open explanation

The request lifecycle, route contracts, provenance shaping, and eval report payload builder are shared rather than rebuilt separately for API responses.

## Development

The server is intentionally minimal: it reuses the shared request lifecycle rather than duplicating CLI logic.
