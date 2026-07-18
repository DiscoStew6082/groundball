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

The takeaway: one catalog and one deterministic plan/compiler path own structured baseball facts. Every result is inspectable, proof-bound, and independent of an LLM or network service.
