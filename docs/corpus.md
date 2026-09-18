# Corpus Material

The Markdown under `src/baseball_rag/corpus/stat_definitions/` contains ten reviewed definitions used by the sourced assistant: 2B, AVG, BB, ERA, HR, OPS, PO, RBI, SB, and WHIP. Each document contains a concise definition or formula and its individual MLB glossary source URL. Historical player claims and editorial commentary are outside this corpus.

## Structure

```text
corpus/
├── __init__.py              # Path constants and helper listings
├── frontmatter.py           # YAML frontmatter parser
└── stat_definitions/        # 10 markdown files, one per stat
```

## Runtime behavior

`assistant.py` reads the reviewed definition, includes its text in the retained source record, and returns a cited `ground-ball-assistant-answer-v1` response. The source URL identifies the authoritative glossary entry; the answer's observation time describes the retained record, not a new web verification. Missing definitions are unavailable rather than filled in by model recall.

Statistical calculations still belong to the Published Query Catalog and verified DuckDB Query Runs. Definition prose does not add query fields or formulas. No vector index or generated biography is needed for this answer path.

## Document Format

The retained Markdown uses YAML frontmatter:

```markdown
---
title: Home Runs (HR)
category: stat_definition
source_url: https://www.mlb.com/glossary/standard-stats/home-run
tags:
  - hitting
  - power
---

[Reviewed definition text]
```

The parser returns the source URL with the existing metadata:

```python
parse_frontmatter(content)
  -> {"metadata": {"title": ..., "category": ..., "tags": [...], "source_url": ...}, "body": "..."}
```
