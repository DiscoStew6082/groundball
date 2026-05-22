# Demo Checklist

Use this when walking a reviewer through the project in five minutes.

## Prep

```bash
uv sync
uv run python -m baseball_rag.db.download
uv run python -m evals.questions
```

Optional UI:

```bash
uv run python -m baseball_rag.web_app
```

## Script

1. Ask: `who had the most RBIs in 1962`
   - Show deterministic stat routing to DuckDB.
   - Point out returned rows and data manifest provenance.

2. Ask: `who won the Triple Crown and which years`
   - Show `Deterministic template query` in the source label.
   - Point out SQL visibility and template-owned factual execution.

3. Ask: `who played for the Braves in 1936`
   - Show the LLM-backed typed grounded database path.
   - Point out that Python still assembles constrained, parameterized SQL.

4. Ask: `who was Babe Ruth`
   - Show that the player identity resolves through DuckDB first.
   - Point out biography stat-claim verification rows and any warnings.

5. Ask: `how many home runs did Williams have in 1941`
   - Show ambiguity handling.
   - Emphasize that unsupported or ambiguous questions do not silently guess.

6. Open `docs/eval-report.md`
   - Show safe deterministic eval counts.
   - Mention that `--include-live` is intentionally separate because it may require LM Studio.

## Close

The takeaway: language is used for routing and narration, while deterministic code owns database execution and every answer carries inspectable evidence.
