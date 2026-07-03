# Retrosheet Event Support Matrix

Groundball has local Retrosheet event-derived data, but only for modeled projections.
The language model should not infer arbitrary play-by-play answers from that fact.

The source of truth in code is `src/baseball_rag/retrosheet_event_capabilities.py`.

| Capability | Local table | Supported query families | Supported filters | Nearby unsupported families |
| --- | --- | --- | --- | --- |
| Pitcher strikeout-side counts | `retrosheet_pitcher_strikeout_side_events` | Named pitcher career strikeout-side count; named pitcher season strikeout-side count; named pitcher strikeout-side game log; pitcher career strikeout-side leaderboard | pitcher full name; career; year; game log | inherited runners or entering with runners on base; pitch counts or immaculate innings; called/swinging strikeout splits; postseason-only splits; opponent, batter, team, or park filters |

When a query lands near a Retrosheet event family but needs an unmodeled projection, Groundball should return a deterministic unsupported answer that names the supported Retrosheet event families rather than falling through to LLM guessing.
