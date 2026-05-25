# Baseball RAG Eval Report

- Command: `python -m evals.questions --report docs/eval-report.md --guardrail-report docs/guardrail-coverage.md --json-report docs/eval-report.json --baseline evals/baseline.json`
- Mode: answer
- Release recommendation: **PASS - deterministic release gate is green**
- Cases loaded: 70
- Attempted: 26
- Passed: 26
- Failed: 0
- Skipped: 44
- Pass rate: 100.0%
- Required pass rate: 85%

## Service Requirements

- Deterministic/CI-safe mode was used; non-default cases were skipped. 44 case(s) are available behind `--include-live`; 11 skipped case(s) may require LM Studio.

## Skipped Live Cases

- `player_bio_babe_ruth`: who was Babe Ruth
- `player_bio_babe_ruth_tell_me`: tell me about Babe Ruth
- `player_bio_babe_ruth_team_followup`: what teams did he play for
- `player_bio_ted_williams`: tell me about Ted Williams
- `player_bio_willie_mays`: who was Willie Mays

## Risk Categories

- Grounded stats: 13 case(s)
- SQL safety: 13 case(s)
- Unsupported guardrails: 18 case(s)
- Provenance and source visibility: 43 case(s)
- Live LLM optional: 11 case(s)

## Suite Coverage

- stat query: `stat_rbi_1962` - who had the most RBIs in 1962
- unsupported/guardrail: `stat_unsupported_column` - who led the league in vibes in 1999
- grounded database question: `stat_sql_injection_team` - who played for the Braves%' OR 1=1 -- in 1936
- LLM player biography: `player_bio_babe_ruth` - who was Babe Ruth
- LLM open explanation: `broad_bio_query_yankees_slugger` - which biography text talks about a Yankees switch-hitting slugger

## Baseline Comparison

- Recommendation: PASS

## Failed Cases

- None
