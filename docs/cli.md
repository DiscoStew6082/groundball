# CLI Reference

## `baseball-rag`

Single command for ad-hoc queries against the shared answer pipeline.

### Usage

```bash
uv run python -m baseball_rag.cli "your question here"
```

Or via the installed entry point:

```bash
baseball-rag "who was Babe Ruth"
```

### Examples

```bash
# Stat query with year filter -> DuckDB lookup
uv run python -m baseball_rag.cli "who had the most RBIs in 1962"

# Career stat leaders -> DuckDB lookup
uv run python -m baseball_rag.cli "career home run leaders"

# Player biography -> DuckDB identity + LLM JSON + DuckDB claim verification
uv run python -m baseball_rag.cli "who was Babe Ruth"

# General stat explanation -> direct LLM answer
uv run python -m baseball_rag.cli "what is OPS"
```

### How It Works

```text
answer(question)
  |
  +-- service.answer(question)
      |
      +-- route(question)
          |
          +-- stat_query
          |   +-- registered stat SQL -> DuckDB
          |
          +-- grounded_database_question
          |   +-- typed query spec -> parameterized SQL -> DuckDB
          |
          +-- player_biography
          |   +-- resolve player in DuckDB
          |   +-- request structured biography JSON from LM Studio
          |   +-- verify extracted stat claims in DuckDB
          |
          +-- general_explanation
              +-- local stat definition when supported
              +-- otherwise request open explanation from LM Studio
```

### Error Handling

| Condition | Behavior |
|-----------|----------|
| No year in query | Returns career leaders instead of season leaders |
| Player-specific stat not found | Returns a no-result message instead of switching to league leaders |
| Ambiguous biography name | Fails closed before calling the LLM |
| Unresolved biography name | Returns `no_data` before calling the LLM |
| Contradicted biography stat claim | Returns the biography plus structured warnings and a visible note |
| LM Studio offline for open prose | Returns `llm_unavailable`; no DuckDB biography fallback is synthesized |
| DuckDB uninitialized | Auto-initializes on first stat query via `init_db()` |

The CLI intentionally does not ask the model to invent structured facts when grounded database evidence is required.
