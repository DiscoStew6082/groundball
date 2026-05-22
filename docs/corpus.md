# Corpus Material

The Markdown under `src/baseball_rag/corpus/` is checked-in project material. It is useful for examples, docs, and tests. The stat-definition Markdown remains runtime grounding for supported stat-definition explanations; Hall of Fame biography Markdown is not runtime grounding for player biographies.

ChromaDB indexing was removed because it duplicated generated baseball facts and introduced fragile local state. The runtime now uses DuckDB for structured facts, local LLM generation for open prose, and DuckDB verification for extractable biography stat claims.

## Structure

```text
corpus/
├── __init__.py              # Path constants and helper listings
├── diagnostics.py           # Checked-in corpus and old manifest diagnostics
├── frontmatter.py           # YAML frontmatter parser
├── stat_definitions/        # 10 markdown files, one per stat
└── hof/                     # 5 Hall of Fame player biography examples
```

## Runtime Behavior

- Structured stat answers are DuckDB-backed and expose SQL, rows, and manifest provenance.
- Freeform database answers use typed query specs and parameterized DuckDB SQL.
- Player biographies resolve the player identity through DuckDB, then ask the LLM for JSON containing `answer` and `stat_claims`.
- Supported career and season stat claims extracted from biographies are verified against DuckDB.
- Supported stat-definition explanations such as "what is OPS?" use local stat-definition Markdown before the open LLM fallback.
- If LM Studio is unavailable for open prose, the system returns `llm_unavailable`; it does not synthesize a DuckDB biography fallback.

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

## Diagnostics

Print corpus diagnostics as JSON:

```bash
uv run python -m baseball_rag.corpus diagnostics --persist-dir data
```

The report includes:

- resolved corpus/manifest directory
- checked-in stat definition and Hall of Fame Markdown counts
- old ignored `corpus_manifest.json` presence/counts when present
- runtime flags showing that no index is required

Diagnostics do not require a vector index. Missing directories, missing manifests, and corrupt manifests are reported in JSON instead of raising.
