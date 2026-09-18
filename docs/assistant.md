# Sourced baseball assistant

The assistant uses the existing chat and `POST /api/query-runs`. Public code owns its question interpretation contract, factual selection, evidence, and presentation. The outer runtime may inject model transport and bounded external source callbacks. Check `GET /api/capabilities` for enabled support; the deterministic query engine remains usable without these optional bindings.

## Supported scope

| Request | Evidence and limits |
| --- | --- |
| Historical context for one MLB team | Verified statistical Query Runs through 2025. Historical players are not presented as current participants. |
| Context for one team's upcoming game | The next listed, unstarted fixture; dated team statistics; supported historical World Series meetings between the opponents. Coverage is incomplete and start times may change. |
| Historical World Series follow-up | Both opponents and season carried as references; the retained games are retrieved and checked again. |
| Current batting leaders | Regular-season HR/RBI/SB, top one to five plus cutoff ties; fresh MLB records with player/team identities and retained raw provenance. |
| Probable pitchers | Next scheduled fixture within seven days; both teams or the requested team, with unannounced pitchers explicit and tentative status retained. |
| Comparison plus explanation | One verified statistical query and reviewed definition composed into at most five facts; unavailable parts prevent a partial answer. |
| Stat definition | Reviewed local definition with an individual MLB glossary citation: 2B, AVG, BB, ERA, HR, OPS, PO, RBI, SB, or WHIP. |

Research requests allow one to five details. Answers may contain fewer when evidence is missing; the limitation is explicit. A definition returns one explanation. Missing fixture evidence returns unavailable, while unavailable postseason evidence is disclosed without inventing a meeting.

Injuries, rosters, news, betting, weather, live player totals and current statistics beyond the listed leaderboards are outside this scope. Requested dates, additional teams, or other unsupported conditions must not be dropped to manufacture an answer. Ambiguous requests need clarification; unsupported requests are rejected. Specific historical statistical questions continue through the catalog-backed query engine.

## Interpretation and evidence

`question_interpretation.py` owns the prompt, response schema, validation, and `run_question_input`. The deterministic adapter is tried first. Optional model interpretation returns catalog-derived statistics slots, a direct recipe, a research request, a bounded compound plan, a clarification code, or rejection. Slots simplify common totals and comparisons; direct recipes preserve complex catalog operations. It does not write factual answers. Every proposed recipe passes the existing published planner/compiler. Typed season scopes must fit the immutable release coverage, and canonical teams are validated against the catalog-owned team source.

A compound plan has two or three steps and at most one statistical query. Comparisons preserve all requested players within that query. The model cannot write the answer. Follow-up context accepts only version, topic, canonical team/opponent, season and statistic references within 2 KB. It never accepts prior factual prose as evidence.

`assistant.py` validates source records and builds `ground-ball-assistant-answer-v1`. Each fact identifies its supporting sources; statistical facts retain the immutable Query Run and QueryEvidence. Source records carry URLs, observation times, fingerprints, license information, and application-owned attribution. Current-source normalized fields must match the retained normalized record, and the source adapter retains the raw records that produced them. Current answers require observations no older than ten minutes. Observation time is not a promise that the source covers every game or has changed since the last observation.

The UI shows citations beside facts and required credits outside collapsed evidence. It renders source text safely and permits HTTPS source links only. History restores the full local snapshot; a failed new attempt preserves the last completed answer. Downloaded answer JSON includes all evidence and attribution. Compound statistical answers preserve their recipe for the next question; their full answer download retains the embedded Query Run. Answer cards do not offer query CSV export or recipe editing.

The Published Query Catalog remains the sole statistical capability authority. External records and model interpretation cannot introduce query formulas or bypass Coverage Report verification. Retrosheet event queries retain their separate supported families. See [architecture](architecture.md), [API](api.md), and [source attribution](source-attribution.md).
