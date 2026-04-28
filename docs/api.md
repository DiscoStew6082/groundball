# API Reference

FastAPI server exposing the RAG pipeline over HTTP.

## Start the Server

```bash
uv run uvicorn baseball_rag.api.server:app --reload
```

Default port: **8000** (--reload enables auto-reload on code changes).

## Endpoints

### `GET /health`

Health check. No authentication required.

**Response**
```json
{ "status": "ok" }
```

---

### `POST /query`

Ask a baseball question and get a grounded answer with provenance metadata.

**Request**

```json
{
  "question": "who had the most RBIs in 1962"
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
    "route": "stat_query",
    "unsupported": false,
    "source_count": 1,
    "source_types": ["duckdb"],
    "sql_visible": true,
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

**Response fields**

| Field | Type | Description |
|-------|------|-------------|
| `answer` | string | Full answer text (formatted list for stat queries, prose for general questions) |
| `intent` | string | Router intent used to answer the question |
| `sources` | array | DuckDB/Chroma evidence records used to ground the answer |
| `warnings` | array | Non-fatal caveats, such as missing indexes or truncated results |
| `unsupported` | boolean | True when the system could not answer from grounded evidence |
| `review` | object/null | Human review queue hint for unsupported, ambiguous, or low-confidence answers |
| `metadata` | object | Additive audit metadata for route, unsupported status, source summary, SQL visibility, latency, and trace stages |
| `sources[].data_manifest` | object/null | Dataset source, checksums, row counts, coverage, download metadata, and license notes for DuckDB-backed answers |

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
| 500 Internal Server Error | Unexpected DuckDB, ChromaDB, or server error |

## Architecture Note

The `/query` endpoint calls the shared answer service. The CLI renders the same
structured answer as text, while the API returns the full JSON payload:

1. **Stat query** → DuckDB lookup with registered stat whitelist
2. **Freeform query** → typed query spec → parameterized SQL → DuckDB
3. **General question** → ChromaDB retrieval + LLM generation

This means API and CLI behave identically for the same input.

## Development

The server is intentionally minimal — it reuses the CLI logic rather than duplicating it, keeping the API and command-line interface consistent.
