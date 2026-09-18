# Sourced baseball assistant

The assistant uses the existing chat and `POST /api/query-runs`. Public code owns its question interpretation contract, factual selection, evidence, and presentation. The outer runtime may inject model transport and bounded external source callbacks. Check `GET /api/capabilities` for enabled support; the deterministic query engine remains usable without these optional bindings.

## Supported scope

| Request | Evidence and limits |
| --- | --- |
| Historical context for one MLB team | Verified statistical Query Runs through 2025. Historical players are not presented as current participants. |
| Context for one team's upcoming game | The next listed, unstarted fixture; dated team statistics; supported historical World Series meetings between the opponents. Coverage is incomplete and start times may change. |
| Stat definition | Reviewed local definition with an individual MLB glossary citation: 2B, AVG, BB, ERA, HR, OPS, PO, RBI, SB, or WHIP. |

Research requests allow one to five details. Answers may contain fewer when evidence is missing; the limitation is explicit. A definition returns one explanation. Missing fixture evidence returns unavailable, while unavailable postseason evidence is disclosed without inventing a meeting.

Current injuries, starters, rosters, news, betting, weather, and current-season performance are outside this scope. Requested dates, additional teams, or other unsupported conditions must not be dropped to manufacture an answer. Ambiguous requests need clarification; unsupported requests are rejected. Specific historical statistical questions continue through the catalog-backed query engine.

## Interpretation and evidence

`question_interpretation.py` owns the prompt, response schema, validation, and `run_question_input`. The deterministic adapter is tried first. Optional model interpretation returns a recipe, bounded research plan, clarification code, or rejection. It does not write factual answers. Every proposed recipe passes the existing published planner/compiler.

`assistant.py` validates source records and builds `ground-ball-assistant-answer-v1`. Each fact identifies its supporting sources; statistical facts retain the immutable Query Run and QueryEvidence. Source records carry URLs, observation times, fingerprints, license information, and application-owned attribution. Observation time is not a promise that the source covers every game or has changed since the last observation.

The UI shows citations beside facts and required credits outside collapsed evidence. It renders source text safely and permits HTTPS source links only. History restores the full local snapshot; a failed new attempt preserves the last completed answer. Downloaded answer JSON includes all evidence and attribution. Assistant answers do not offer query CSV export or recipe editing.

The Published Query Catalog remains the sole statistical capability authority. External records and model interpretation cannot introduce query formulas or bypass Coverage Report verification. Retrosheet event queries retain their separate supported families. See [architecture](architecture.md), [API](api.md), and [source attribution](source-attribution.md).
