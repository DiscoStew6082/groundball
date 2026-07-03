# Retrosheet Event Support Matrix

Groundball has local Retrosheet event-derived data and game-level daily logs, but only for modeled query families.
The language model should not infer arbitrary play-by-play answers from that fact.

The source of truth in code is `src/baseball_rag/retrosheet_event_capabilities.py`.

Retrosheet daily-log zip archives are the tracked source artifacts. Runtime can use an ignored
`data/secondary_sources/retrosheet/retrosheet.duckdb` cache built with
`uv run python -m baseball_rag.db.secondary_sources.retrosheet_database`; Groundball validates
cache source hashes against the Retrosheet manifest before preferring it over zip/CSV fallback.

| Capability | Local table | Supported query families | Supported filters | Nearby unsupported families |
| --- | --- | --- | --- | --- |
| Pitcher strikeout-side counts | `retrosheet_pitcher_strikeout_side_events` | Named pitcher career strikeout-side count; named pitcher season strikeout-side count; named pitcher strikeout-side game log; named pitcher strikeout-side count or game log by opponent team; pitcher career strikeout-side leaderboard | pitcher full name; career; year; game log; opponent team | inherited runners or entering with runners on base; pitch counts or immaculate innings; called/swinging strikeout splits; postseason-only splits; batter or park filters |
| Stolen-base game streaks | `retrosheet_batting` | All-time longest stolen-base game streak; named player longest stolen-base game streak; named player longest postseason stolen-base game streak | player full name; regular season; postseason | team stolen-base streaks; consecutive successful steal attempts without caught stealing; base-specific steal streaks |

When a query lands near a Retrosheet event family but needs an unmodeled projection, Groundball should return a deterministic unsupported answer that names the supported Retrosheet event families rather than falling through to LLM guessing.
