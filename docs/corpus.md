# Corpus Material

The Markdown under `src/baseball_rag/corpus/` is checked-in project material. The stat-definition Markdown remains runtime grounding for supported stat-definition explanations.

ChromaDB indexing was removed because it duplicated generated baseball facts and introduced fragile local state. The runtime now uses DuckDB for structured facts, local LLM generation for open prose, and DuckDB verification for extractable biography stat claims.

## Structure

```text
corpus/
├── __init__.py              # Path constants and helper listings
├── frontmatter.py           # YAML frontmatter parser
└── stat_definitions/        # 10 markdown files, one per stat
```

## Runtime Behavior

- Structured stat answers are DuckDB-backed and expose SQL, rows, and manifest provenance.
- Grounded database question answers use typed query specs and parameterized DuckDB SQL.
- Player biographies resolve the player identity through DuckDB, then ask the LLM for JSON containing `answer` and `stat_claims`.
- Supported career and season stat claims extracted from biographies are verified against DuckDB.
- Supported stat-definition explanations such as "what is OPS?" use local stat-definition Markdown before the open LLM path.
- If LM Studio is unavailable for open prose, the system returns `llm_unavailable`; it does not synthesize DuckDB-only biography text.

## Document Format

The retained Markdown uses YAML frontmatter:

```markdown
---
title: Home Runs (HR)
category: stat_definition
tags:
  - hitting
  - power
---

A home run occurs when a batter hits the ball over the outfield fence...
```

The parser still supports this format for docs/tests:

```python
parse_frontmatter(content)
  -> {"metadata": {"title": ..., "category": ..., "tags": [...]}, "body": "..."}
```
