# Interaction patterns for a Ground Ball sports-stat query experience

Checked against first-party product pages, documentation, and live result pages on 2026-07-17.

## Recommendation

Do not model Ground Ball as a miniature database workbench. Model it as an **answer-first sports app with an inspectable query**:

1. Start with the approved, editable 40–40 natural-language example.
2. Return a short answer, a compact result view, and a visible **“Ground Ball understood…”** interpretation.
3. Let the user tap that interpretation to edit a small set of structured filters.
4. Put the full field catalog, custom columns, approved calculations, and source evidence behind progressive disclosure.
5. Preserve bounded, serializable Query Plan state in the URL; add named saved views only after the core loop is useful.

On mobile, the **answer and results table are the primary screen**. **Refine**, **Columns**, and **Verify** are secondary controls that open focused sheets; they are not competing modes or equal-weight navigation destinations.

This combines the best interaction ideas from StatMuse, Stathead, MLB Stats, FanGraphs, and Baseball Savant without reproducing their desktop density.

## What the reference products actually do

| Product | First interaction | Result presentation | Progressive controls | Trust / reuse | Ground Ball lesson |
|---|---|---|---|---|---|
| StatMuse | One natural-language question plus example and trending questions | One-sentence answer, an explicit interpretation, then a data table and related questions | Most syntax stays implicit; a separate data/glossary surface explains supported concepts | Result URLs are inherently shareable | Best model for the first 10 seconds, but the interpretation must remain editable and deterministic |
| Stathead / Baseball-Reference | Choose the query grain/finder, then set explicit criteria | Plain-language “Current Search,” collapsible criteria, then a sortable table | Separate finders for seasons, games, streaks, spans, splits, events, and versus queries | Executable sample searches, compact URLs, coverage statement, source attribution | Best model for query transparency and grain selection; too form-heavy as a starting screen |
| MLB Stats | Choose a familiar task/tab and use a compact filter bar | Preset table views such as Standard, Expanded, and Statcast | More filters are available without changing the basic leaderboard mental model | Inline disclosure of qualification/sorting rules; glossary links define metrics | Presets are a better mobile default than exposing dozens of columns |
| FanGraphs | Open a leaderboard, choose filters or a saved/custom report | Dense table with stat-view presets and user-defined columns | Custom reports, stat filters, player/team lists, and pitch-level data are layered over the base table | Named reports, tabs, copied/shared URLs, load/save behavior | Saved views can become a useful expert layer; they should not dominate the public demo |
| Baseball Savant | Pick a leaderboard or open a highly structured Statcast search | Table or chart, often with downloadable data | Domain-grouped filters, custom columns, year/type/minimum controls, chart settings | Shareable URL state, CSV, metric definitions, coverage caveats | Best model for the advanced drawer and field catalog; its full search form is an anti-pattern for first use |

## 1. StatMuse: answer first, then reveal what was understood

StatMuse treats a question as the primary interaction. Its official MLB examples are grouped by user intent—scores, schedules, standings, stats, bios, recaps, odds, and “beyond the box score”—rather than by tables or schema. That gives new users concrete, tappable ways into the product instead of an empty prompt. [StatMuse MLB examples](https://www.statmuse.com/product/examples/mlb)

A live 40–40 query demonstrates the full response hierarchy:

- a direct sentence (“Jose Canseco went yard 42 times…”),
- an explicit **“Interpreted as”** line,
- a table containing the matching seasons and additional statistics,
- a statement of the relevant data-coverage boundary,
- related searches for the next step.

See the [live StatMuse 40-HR/40-SB result](https://www.statmuse.com/mlb/ask/players-with-40-home-runs-and-40-stolen-bases-in-a-season). StatMuse separately publishes its MLB coverage dates and metric definitions in a first-party [data and glossary page](https://www.statmuse.com/product/data/mlb).

The MLB landing page also mixes example questions with compact league leaders, rankings, standings, and trending searches. This means a user who does not want to type can still enter through recognizable content. [StatMuse MLB landing page](https://www.statmuse.com/mlb)

### Pattern to adopt

- Keep the input dominant.
- Make examples look like real questions, not feature labels.
- Show the interpreted query immediately below the answer.
- Use the answer sentence as a headline, not as a chatbot monologue.
- Offer two or three contextual follow-ups after the results.

### Pattern to avoid

The result table exposes far more columns than the question requires. On a narrow screen, that makes the answer harder to scan. Ground Ball should initially show only identity, season, and the statistics named in the question; **More stats** can reveal a preset or custom column view.

The interpretation should also not be passive text. In Ground Ball it should be a deterministic, editable representation of the Query Plan, so a mistaken grain or threshold can be corrected without rephrasing the entire question.

## 2. Stathead: choose the grain and make the compiled query visible

Stathead divides baseball questions into explicit finder families: season/career, game, streak, span, versus, split, and event. Its sample-search page says that opening an example reveals which tool and filters produced the result and invites the user to modify them. [Stathead baseball sample searches](https://stathead.com/stathead/baseball-sample-searches.html)

A live Player Batting Season Finder result places a plain-language **Current Search** summary above a Show/Hide Criteria control and the result table. The same page groups criteria into time, position, statistical, team, status, biography, and advanced sections. It also publishes the result’s database source and a precise coverage statement below the table. [Stathead Player Batting Season Finder](https://stathead.com/tiny/yQd70)

Stathead’s official product description emphasizes searching careers, seasons, games, streaks, spans, and individual events with filters, as well as creating customized leaderboards. [Stathead product page](https://stathead.com/stathead/)

### Pattern to adopt

- Ask for the grain only when it is ambiguous: **player season**, **career**, **single game**, **team season**, or **event**.
- Keep one plain-language summary of the compiled query visible.
- Let an example load a real, editable Query Plan rather than showing a canned screenshot.
- Attach coverage and source information to the result, not to a generic About page.

### Pattern to avoid

Stathead’s complete filter form is powerful but visually overwhelming: the statistical selector alone spans standard, value, sabermetric, win-probability, and miscellaneous categories, alongside many other filter groups. Ground Ball should not make users choose the right database tool before they can ask a common question. The grain chooser belongs in clarification or in an advanced sheet, not on the initial screen.

## 3. MLB Stats: compact presets before custom columns

MLB’s public Stats leaderboard uses a conventional sports hierarchy: hitting/pitching/Statcast tasks, a compact row of filters for year, season type, league, team, range, position, player pool, and split, and then preset table views such as **Standard**, **Expanded**, and **Statcast**. It discloses an important sorting rule inline: non-qualified players are hidden by default when a rate statistic is used for sorting. [MLB Stats leaderboard](https://www.mlb.com/stats)

MLB player pages use an equally familiar progression: career, game logs, splits, and batter-vs-pitcher views; MLB/minors, pitching/batting/fielding, and regular-season selectors; then the career table. [Example MLB player statistics page](https://www.mlb.com/player/672715)

MLB maintains a first-party glossary divided into standard, advanced, and Statcast statistics. The Statcast glossary distinguishes raw measurements from derived metrics and describes availability and collection technology. [MLB glossary](https://www.mlb.com/glossary) and [MLB Statcast glossary](https://www.mlb.com/glossary/statcast)

### Pattern to adopt

- Default the result to a named view containing a small, coherent set of columns.
- Use familiar filters—year, team, position, regular/postseason—before exotic field names.
- Explain material query rules inline when they affect who appears in a result.
- Give each unfamiliar metric a concise definition that can expand without leaving the result.

### Mobile lesson

MLB’s app uses a bottom tab bar and routes a team’s Stats link to that team’s stat leaders, while followed-player cards show at-a-glance stat lines and link to deeper player cards. These are strong mobile patterns: stable primary navigation, contextual leaderboards, and a small summary before detail. [MLB Android app release notes](https://www.mlb.com/apps/mlb-app/android-mlb-app-beta-release-notes) and [MLB followed-player feature](https://www.mlb.com/news/how-to-follow-favorite-players-in-mlb-app)

## 4. FanGraphs: saved reports and expert customization

The current FanGraphs leaderboards combine top-level filters with league presets, stat presets such as Dashboard, Standard, Advanced, Batted Ball, Win Probability, Value, and Statcast, plus entry points for custom reports and custom players/teams. [FanGraphs Major League leaderboard](https://www.fangraphs.com/leaders/major-league)

FanGraphs’ first-party customization guide describes reports containing selected stat columns, filters, and players. Reports can appear as quick-access tabs and can be managed in a Custom Reports dialog. Users can customize columns through drag/drop or double-click, with long-press as the mobile equivalent. [FanGraphs dashboard and leaderboard customization](https://blogs.fangraphs.com/why-not-both-the-board-scouting-stats/)

Its leaderboard redesign deliberately moved custom reports into modals, made split controls more accessible, and kept unavailable controls visible rather than making choices appear and disappear across eras/categories. Saving reports and using larger custom stat/player lists are membership features. [FanGraphs leaderboard redesign](https://blogs.fangraphs.com/weve-updated-our-major-league-leaderboards-interface/)

### Pattern to adopt

- Treat saved queries as named result views, not as a separate “history app.”
- Reuse familiar preset tabs and allow an expert to add columns later.
- Preserve disabled choices with an explanation when coverage makes them unavailable.
- Separate changes that require recomputation from local actions such as sorting or hiding a column.

### Pattern to avoid

Do not reproduce drag-and-drop column building as the main mobile interaction. A searchable checklist grouped by category is more discoverable, accessible, and deterministic. Saved reports can wait until the public demo proves that users repeatedly refine the same query.

## 5. Baseball Savant: the advanced drawer and evidence model

Baseball Savant’s Statcast Search explicitly supports per-pitch, per-game, per-player, per-team, and per-season queries. It exposes large groups of filters for pitch type, plate-appearance result, situation, location, handedness, venue, and other dimensions. It also explains coverage caveats, known adjustments, CSV documentation, and links to its tutorial and MLB glossary. [Baseball Savant Statcast Search](https://baseballsavant.mlb.com/statcast_search)

Its Custom Leaderboard is a clearer progressive pattern: choose batter or pitcher, year and minimum playing time, then open **Custom Columns**. Columns are grouped into standard stats, Statcast stats, bat tracking, quality of contact, pitches/location, fielding, sprint speed, and other domains. The page says that the resulting leaderboard and chart are shareable, and metric explanations appear inline in the table. [Baseball Savant Custom Leaderboard](https://baseballsavant.mlb.com/leaderboard/custom?type=batter)

The Top Performers page provides another useful progressive pattern: compact top-five cards for many metrics, each with **Definition** and **View Complete Leaderboard** actions. [Baseball Savant Top Performers](https://baseballsavant.mlb.com/leaderboard/top)

### Pattern to adopt

- Put the complete field/stat catalog in a full-height **More filters and columns** sheet.
- Group fields by user concept rather than source-table name.
- Provide select-all/clear and domain shortcuts where they reduce repetitive work.
- Keep source, coverage, definition, formula, and limitations attached to every field.
- Make bounded, serializable Query Plan state URL-addressable so results can be shared and reproduced.

### Pattern to avoid

The full Statcast Search places too many simultaneous choices in front of the user and warns that complicated queries may take time or require a refresh. Ground Ball’s public catalog and query caps should prevent that state rather than merely warn about it.

## Proposed Ground Ball interaction

### Initial mobile screen

- Ground Ball name and a short promise: **Ask a baseball stats question. See exactly how it was answered.**
- One large question field with a Run action.
- The approved 40–40 example preloaded and clearly labeled as editable:
  - “Who had 40 HR and 40 SB in the same season?”
- A small **Browse stats** link for users who prefer structured discovery.

### Result screen

1. Direct answer headline: **Six player-seasons match.**
2. An editable interpretation bar:
   - **Player seasons · HR ≥ 40 · SB ≥ 40 · regular season · all years**
3. Compact mobile rows showing Player, Season, HR, and SB—only the columns needed to understand this answer.
4. Secondary actions: **Refine**, **Columns**, **Verify**, and **Share**. Refine, Columns, and Verify open focused sheets while the result remains the primary context.
5. Two related questions generated from the deterministic catalog, not from an LLM.

### Refine sheet

- Show only active filters first.
- Add familiar dimensions next: years, team, league, position, season type.
- Put **Add condition** and **Choose columns** below those.
- Let the user switch grain explicitly if needed, while explaining that this resets incompatible filters.

### Verify sheet

- Dataset and coverage dates.
- Rows/tables used.
- Field definitions and formulas.
- Qualification and exclusion rules.
- Plain-language Query Plan and reproducible URL.
- Optional generated SQL only in an expert disclosure.

## The central design rule

Every row and column can be exposed without putting every row and column on the first screen. The public demo should expose the full catalog through search, grouped browsing, custom columns, and verification, while keeping the default path as simple as:

> Ask → answer → inspect interpretation → refine if needed.

That is the shared interaction pattern behind the strongest parts of these products, and it directly supports Ground Ball’s deterministic, no-LLM public architecture.
