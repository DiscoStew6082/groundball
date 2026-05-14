# Baseball RAG Eval Report

- Command: `python -m evals.questions --include-live --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json`
- Mode: answer
- Release recommendation: **BLOCK - investigate full local/live eval failures before release**
- Cases loaded: 68
- Attempted: 68
- Passed: 52
- Failed: 16
- Skipped: 0
- Pass rate: 76.5%
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

- Recommendation: BLOCK
- Blocker: pass rate decreased from 1.000 to 0.765
- Warning: skipped case count changed from 48 to 0

## Failed Cases

- `stat_unsupported_column`: unsupported: expected True, got False; answer missing substring 'grounded'
- `stat_sql_injection_stat`: unsupported: expected True, got False
- `stat_sql_injection_team`: intent: expected 'freeform_query', got 'general_explanation'; expected parameterized SQL with bound placeholders
- `freeform_braves_1936`: SQL missing substring 'JOIN teams'
- `min_sample_avg_2024`: intent: expected 'freeform_query', got 'stat_query'
- `min_sample_avg_no_qualifier`: intent: expected 'freeform_query', got 'stat_query'
- `stat_definition_rbi`: answer missing substring 'run batted in'
- `unsupported_betting`: unsupported: expected True, got False
- `unsupported_injury_news`: unsupported: expected True, got False
- `unsupported_live_score`: unsupported: expected True, got False
- `unsupported_contract`: unsupported: expected True, got False
- `team_history_boston_braves`: answer missing substring 'Braves'
- `unsupported_opinion`: unsupported: expected True, got False
- `unsupported_non_baseball`: ValueError: Could not determine stat_tables from LLM response: {
  "year_value": 2020
}
- `unsupported_schema_unknown`: unsupported: expected True, got False
- `unsupported_minor_leagues`: unsupported: expected True, got False
