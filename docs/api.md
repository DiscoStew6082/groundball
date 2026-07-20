# API Reference

Start the single-origin FastAPI/Svelte application locally:

```bash
npm --prefix web run build
uv run groundball-ui
```

The default origin is `http://127.0.0.1:7861`.

## `GET /health`

Returns `{ "status": "ok" }`.

## `GET /api/capabilities`

Returns the server-enforced query, catalog, Coverage Report, Retrosheet, and browser-local history capabilities. The structured query path reports `llm_required: false` in local and public modes.

## `POST /api/query-runs`

Provide exactly one natural-language question or structured recipe. A natural-language request may include `previous_recipe`, containing only the preceding completed Query Recipe. Rows and server-side conversation state are never accepted as context.

```json
{ "question": "who had the most RBIs in 1962" }
```

```json
{
  "recipe": {
    "source": "Batting",
    "grain": "player-season",
    "selections": ["player.name", "season", "batting.RBI"],
    "predicate": {"kind": "compare", "value": "season", "operator": "equals", "literal": 1962},
    "ranking": {
      "value": "batting.RBI",
      "direction": "highest",
      "count": 1,
      "tie_policy": "include_ties",
      "within": []
    }
  }
}
```

Responses are rendering-neutral outcomes: `rows`, `no_data`, `exported`, `needs_clarification`, `rejected`, `unavailable`, or `failed`. Factual rows are withheld when proof verification is unavailable.

Public composition applies the same request body, result envelope, admission, lease, and ten-second execution deadline to both deterministic POST routes. Missing public bindings return a sanitized unavailable response before request parsing.

## `GET /api/query-catalog`

Returns published sources, raw fields, promoted values, and relationships. Optional parameters are `source`, `search`, `offset`, and `limit`.

## `GET /api/query-coverage`

Returns the canonical checked-in JSON Coverage Report. A missing or malformed report returns `503`.

## `GET /coverage-report`

Returns the dark, responsive human representation derived from the canonical report.

## `POST /api/retrosheet/queries`

Executes only separately governed Retrosheet event families.

```json
{ "question": "how many times did Nolan Ryan strike out the side in his career" }
```

Unsupported shapes return `422`; they do not fall through to an LLM.

## Public application composition

Use `baseball_rag.public_app.create_app` with `PublicAppBindings` supplied by the outer runtime. Bindings contain a deployment-shared CAS implementation, stable digest material, an initializer, and a hard-stop execution runner. The public repository deliberately supplies no concrete hosting implementation.

Portable application configuration is limited to release bundle selection, local web assets, local-CI proof configuration, CORS origins, source identity, and runtime cache timing. Default CORS origins are localhost and loopback only.
