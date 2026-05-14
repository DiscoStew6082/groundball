# Baseball RAG Eval Report

- Command: `python -m evals.questions --include-live --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json`
- Mode: answer
- Release recommendation: **WARN - full local/live eval suite is green with baseline drift**
- Cases loaded: 68
- Attempted: 68
- Passed: 68
- Failed: 0
- Skipped: 0
- Pass rate: 100.0%
- Required pass rate: 85%

## Service Requirements

- Live evals were included; `--include-live` may require LM Studio.

## Risk Categories

- Grounded stats: 13 case(s)
- SQL safety: 12 case(s)
- Unsupported guardrails: 18 case(s)
- Provenance and source visibility: 35 case(s)
- Live LLM optional: 14 case(s)

## Suite Coverage

- stat query: `stat_rbi_1962` - who had the most RBIs in 1962
- unsupported/guardrail: `stat_unsupported_column` - who led the league in vibes in 1999
- freeform SQL query: `stat_sql_injection_team` - who played for the Braves%' OR 1=1 -- in 1936
- LLM player biography: `player_bio_babe_ruth` - who was Babe Ruth
- LLM open explanation: `broad_bio_query_yankees_slugger` - which indexed player biography talks about a Yankees switch-hitting slugger

## Baseline Comparison

- Recommendation: WARN
- Warning: skipped case count changed from 48 to 0

## Failed Cases

- None
