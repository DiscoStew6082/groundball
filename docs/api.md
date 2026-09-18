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

Returns query, catalog, Coverage Report, Retrosheet, assistant, and browser-local history capabilities. `assistant.enabled` reflects injected support, with topics derived from the public research contract: `pregame`, `team_history`, `definition`, `series_meeting`, `current_leaders`, and `probable_pitchers`. Source-specific topics can still return unavailable when their callbacks or evidence are absent. `llm_required: false` describes the independent structured query engine; optional question interpretation may use an injected model transport.

## `POST /api/query-runs`

Provide exactly one natural-language question or structured recipe. A natural-language request may include `previous_recipe`, containing only the preceding completed Query Recipe. It may also include `previous_context` with the preceding answer's bounded reference object: `version`, `topic`, `team`, `opponent`, `season`, and `statistic`. Unknown fields and context over 2 KB are rejected. Rows, factual prose and server-side conversation state are never accepted as context. Context is accepted only with a natural-language question.

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

Responses are rendering-neutral outcomes: `rows`, `no_data`, `exported`, `answer`, `needs_clarification`, `rejected`, `unavailable`, or `failed`. Factual rows are withheld when proof verification is unavailable.

With assistant bindings, a supported research question can return `kind: "answer"` and `schema: "ground-ball-assistant-answer-v1"`. The payload contains `title`, `summary`, up to five `facts`, `sources`, nullable `fixture`, `limitations`, `attributions`, and `requested_count`, plus reference-only `context` where applicable. Compound statistical answers also retain a follow-up `recipe`. Facts reference adjacent citations by `source_ids`; historical statistical facts also retain their `query_run`. Sources include their URL, observation time, license, attribution, supporting `record`, and fingerprint. The browser downloads this complete object locally rather than issuing a query export. See [assistant scope](assistant.md).

Public composition applies admission, leases, and the ten-second execution deadline to query/assistant requests and the separate Retrosheet POST route. Missing public bindings return a sanitized unavailable response before request parsing.

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

`QuestionBindings` optionally supplies local interpretation and `ResearchSources`; public runners inject these within their execution boundary. `question_interpretation.py` owns the prompt, output schema, validation, and `run_question_input`. Transports and source callbacks supply I/O, not alternative prompts, factual answer prose, or query semantics. Without these bindings, the deterministic query interface remains available.

Portable application configuration is limited to release bundle selection, local web assets, local-CI proof configuration, CORS origins, source identity, and runtime cache timing. Default CORS origins are localhost and loopback only.
