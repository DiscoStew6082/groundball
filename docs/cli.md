# CLI Reference

The CLI is a thin adapter over the same catalog, plan, execution, evidence, and proof seams as HTTP and the browser.

## Query

```bash
uv run groundball query "who had the most RBIs in 1962"
```

Or provide a structured recipe:

```bash
uv run groundball query --recipe-json '{"source":"People","selections":["People.playerID"],"output":{"kind":"interactive_page","size":10,"offset":0}}'
```

Both forms print the complete JSON outcome. There is no legacy positional command or compatibility entry point.

## Discover fields

```bash
uv run groundball fields
uv run groundball fields --source Batting
uv run groundball fields --source Batting --search GIDP
```

## Inspect Retrosheet support

```bash
uv run groundball capabilities retrosheet-events
```

This lists the separate Retrosheet event families and their supported filters. It does not run a query or invoke an LLM.
