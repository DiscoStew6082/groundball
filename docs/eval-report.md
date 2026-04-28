# Baseball RAG Eval Report

- Command: `python -m evals.questions --report docs/eval-report.md`
- Mode: answer
- Release recommendation: **PASS - deterministic release gate is green**
- Cases loaded: 68
- Attempted: 20
- Passed: 20
- Failed: 0
- Skipped: 48
- Pass rate: 100.0%
- Required pass rate: 85%

## Service Requirements

- Deterministic/CI-safe mode was used; non-default cases were skipped. 48 case(s) are available behind `--include-live`; 25 skipped case(s) may require Chroma, corpus, and LLM services.

## Skipped Live Cases

- `stat_sql_injection_team`: who played for the Braves%' OR 1=1 -- in 1936
- `freeform_braves_1936`: who played for the Braves in 1936
- `freeform_yankees_1950`: who played for the Yankees in 1950
- `freeform_dodgers_1955`: who played for the Dodgers in 1955
- `min_sample_avg_2024`: who had the highest batting average in 2024 with at least 100 at bats

## Risk Categories

- Grounded stats: 13 case(s)
- SQL safety: 12 case(s)
- Unsupported guardrails: 18 case(s)
- Provenance and source visibility: 41 case(s)
- Live retrieval/LLM optional: 35 case(s)

## Suite Coverage

- stat query: `stat_rbi_1962` - who had the most RBIs in 1962
- unsupported/guardrail: `stat_unsupported_column` - who led the league in vibes in 1999
- freeform SQL query: `stat_sql_injection_team` - who played for the Braves%' OR 1=1 -- in 1936
- player biography retrieval: `player_bio_babe_ruth` - who was Babe Ruth
- baseball explanation retrieval: `strategy_broad_bio_query_yankees_slugger` - which indexed player biography talks about a Yankees switch-hitting slugger

## Failed Cases

- None
