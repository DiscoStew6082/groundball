# API Reference

Start the single-origin FastAPI/Svelte application:

```bash
npm --prefix web run build
uv run groundball-ui
```

The default origin is `http://127.0.0.1:7861`.

## `GET /health`

Returns `{ "status": "ok" }`. This is the only route exempt from the optional origin-proxy token.

## `GET /api/capabilities`

Returns the server-enforced query, catalog, coverage, Coverage Report, Retrosheet, and browser-local history capabilities. The structured query path reports `llm_required: false` in both local and public modes.

## `POST /api/query-runs`

Provide exactly one natural-language question or structured recipe. A natural-language request may also include `previous_recipe`, containing only the preceding completed Query Recipe. It is rejected with structured `recipe` input; rows and server-side conversation state are never accepted as context.

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

A deterministic follow-up can refine one unambiguous prior player filter:

```json
{
  "question": "what about his home runs in 2022?",
  "previous_recipe": {
    "source": "Batting",
    "grain": "player-season",
    "selections": ["player.name", "season", "batting.RBI"],
    "predicate": {
      "kind": "all",
      "predicates": [
        {"kind": "compare", "value": "player.name", "operator": "equals", "literal": "Shohei Ohtani"},
        {"kind": "compare", "value": "season", "operator": "equals", "literal": 2022}
      ]
    }
  }
}
```

The bounded follow-up grammar uses no LLM or server-side history and fails closed without exactly one prior `player.name equals <name>` predicate.

The response is a rendering-neutral discriminated outcome:

- `rows`: immutable result rows plus QueryEvidence and verified release status.
- `no_data`: a valid plan matched no rows, with evidence.
- `exported`: exact CSV or JSON snapshot plus rows and evidence.
- `needs_clarification`: the recipe is ambiguous or incomplete.
- `rejected`: the request is outside the catalog or contract.
- `unavailable`: data, catalog, plan, compiler, or proof identity is unavailable or stale.
- `failed`: an unexpected bounded execution failure occurred.

Factual rows are not returned when verification is unavailable.

## `GET /api/query-catalog`

Returns published sources, raw fields, promoted values, and relationships. Optional query parameters:

- `source`: exact published source identity.
- `search`: case-insensitive field identity/name search.
- `offset`: non-negative raw-field offset.
- `limit`: positive page size.

The payload includes `catalog_revision`, `field_total`, `field_offset`, and `field_limit`. Promoted values and relationships are returned in full; pagination applies to raw fields.

## `GET /api/query-coverage`

Returns the canonical checked-in JSON Coverage Report. A missing or malformed report returns `503`.

## `GET /coverage-report`

Returns the dark, responsive human representation derived from the canonical report.

## `POST /api/retrosheet/queries`

Executes only the separately governed Retrosheet event families.

```json
{ "question": "how many times did Nolan Ryan strike out the side in his career" }
```

Unsupported Retrosheet shapes return `422`; they do not fall through to an LLM.

## Deployment controls

- `GROUNDBALL_PUBLIC_DEMO=1`: declares public mode; the query contract is unchanged.
- `GROUNDBALL_ORIGIN_PROXY_TOKEN`: requires `x-groundball-proxy-token` on every route except `/health`.
- `GROUNDBALL_CORS_ORIGINS`: comma-separated allowlist for cross-origin `POST /api/query-runs`.
- `GROUNDBALL_WEB_DIST`: override the built Svelte asset directory.
