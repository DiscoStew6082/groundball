# Demo Checklist

```bash
uv sync
npm --prefix web ci
npm --prefix web run build
uv run groundball-ui
```

Open `http://127.0.0.1:7861/`.

1. Ask `who had the most RBIs in 1962`; show Tommy Davis, 153, then open SQL and QueryEvidence.
2. Run the 40-40 recipe; show the exact six rows and tie-safe ordering.
3. Discover `GIDP` in the catalog, build a raw query, and show that the raw surface is not hidden behind promoted stats.
4. Ask `Aaron Judge OPS in 2022`; show the published formula and independently sourced components.
5. Ask an ambiguous strikeout question; show inline clarification rather than a guessed discipline.
6. Try an arbitrary formula; show the closed catalog rejection.
7. Export a result and show that the downloaded snapshot matches the visible rows.
8. Open the Coverage Report; show six passing gates, 5,253 covered obligations, and zero uncovered.

These structured query results share one catalog and deterministic plan/compiler path, with inspectable evidence and release proof independent of an LLM or network service.

When `assistant.enabled` is true, also ask for historical context about one team or an explanation of OPS. Show adjacent citations, expanded source records, visible attribution, and the full JSON download. Upcoming-game context requires available fixture evidence and must disclose that it covers the next listed game, not a complete schedule. See [assistant scope](assistant.md).

Use these representative assistant prompts when the corresponding bindings are enabled:

| Prompt | What to inspect |
| --- | --- |
| How many homers did Aaron Judge hit in 2023? | 37, with the historical query and its evidence. |
| Show Aaron Judge home runs in 2021 and 2023, separately. | Only the two requested seasons; no implicit intermediate year. |
| Compare Aaron Judge and Shohei Ohtani OPS in 2023 and explain OPS. | Both players, the requested season, the definition and evidence for each part. |
| Explain that statistic again. | Reference-only context from the preceding answer; definition retrieved again. |
| Give me five interesting details about the upcoming Braves game. | Selected matchup/date, available source-backed facts, dated historical context and explicit limits. |
| Who are the top five MLB home run hitters this season? | Fresh regular-season records and cutoff ties; values depend on the source observation. |
| Who is expected to pitch in the next Braves game? | Scheduled matchup and pitchers marked probable or unannounced. |
| Give me three details about the 2021 World Series between the Braves and Astros. | Retained records, citations and the full visible Retrosheet credit. |

Also check a request for unsupported injury/news information. It should explain the limitation without inventing facts or silently answering a different question. A model outage may produce unavailable; do not count a safe refusal as a successfully answered question.
