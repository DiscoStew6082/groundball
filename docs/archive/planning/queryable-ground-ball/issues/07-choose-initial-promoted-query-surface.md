# Choose the initial promoted query surface

Type: `grilling`
Status: resolved
Blocked by: [Prototype the mobile Query Recipe experience](01-prototype-mobile-query-experience.md), [Specify the Published Query Catalog Interface](02-specify-published-query-catalog-interface.md), [Specify the deterministic Query Plan Interface](03-specify-deterministic-query-plan-interface.md), [Define completeness and verification gates](04-define-completeness-and-verification-gates.md)

## Question

Which exact current Lahman fields receive first-class natural-language treatment, which statistics and exact derived calculations are promoted, and which approved joins, filters, and groupings belong in the initial shared query surface while every raw loaded Lahman field and team-reference field remains discoverable? Numeric request, result, export, and hosting safety ceilings remain owned by the zero-Mac public-demo map.

## Answer

Promote one coherent **historical almanac essentials** surface instead of freezing the narrower and inconsistent current registry. This is the first-class natural-language and guided-control layer of the Published Query Catalog; it does not limit the exhaustive raw-field surface.

### First-class dimensions and almanac facts

- **Player** uses `People.playerID` as its stable identity and `nameFirst`, `nameLast`, and `nameGiven` for natural-language matching and display.
- **Season**, **team**, **league**, and **position** promote `yearID`, the season-aware `yearID` plus `teamID` identity and synthesized team name, `lgID`, and `Fielding.POS`.
- Player facts promote `birthYear`, `birthMonth`, `birthDay`, `birthCity`, `birthState`, `birthCountry`, `deathYear`, `deathMonth`, `deathDay`, `deathCity`, `deathState`, `deathCountry`, `bats`, `throws`, `height`, `weight`, `debut`, and `finalGame`.
- Technical identities `People.ID`, `bbrefID`, and `retroID`, along with `stint` and every other unlisted field, remain available through raw discovery and generic structured controls but receive no first-class natural-language aliases.

Team means the exact season-aware Lahman team identity attached to a source row, not an inferred franchise spanning relocations or renames. The published team reference is keyed by season plus team code, or an equivalent identity that uniquely preserves the season-correct name. A team-and-season question may resolve the appropriate historical identity; an unscoped franchise-like name that maps to multiple historical identities requires clarification. Every team identity referenced by a published fact source must have a friendly lookup entry before the promoted team dimension can pass its release gates. The current partial, code-only lookup therefore requires completion during implementation; the product must not silently label missing identities or infer franchise continuity.

### Promoted statistics and exact calculations

Promote these source statistics with friendly full-name aliases while retaining their familiar baseball abbreviations:

- **Batting:** `G`, `AB`, `R`, `H`, `2B`, `3B`, `HR`, `RBI`, `SB`, `CS`, `BB`, and batting `SO`.
- **Pitching:** `W`, `L`, `G`, `GS`, `CG`, `SHO`, `SV`, innings pitched from `IPouts`, `H`, `ER`, `HR`, `BB`, and pitching `SO`.
- **Fielding:** `G`, `GS`, fielding innings from `InnOuts`, `PO`, `A`, `E`, and `DP`.

Promote these exact calculations; broader-grain results always recompute them from summed source components rather than averaging stored row rates:

- `AVG = H / AB`.
- `OBP = (H + BB + HBP) / (AB + BB + HBP + SF)`.
- `SLG = ((H - 2B - 3B - HR) + 2×2B + 3×3B + 4×HR) / AB`.
- `OPS = OBP + SLG`.
- `ERA = 27 × ER / IPouts`.
- `WHIP = 3 × (BB + H) / IPouts`.
- `fielding percentage = (PO + A) / (PO + A + E)`.

Innings pitched and fielding innings are friendly representations of authoritative outs and preserve baseball thirds exactly. Shared abbreviations such as `G`, `H`, `HR`, `BB`, and `SO` use question context to select batting, pitching, or fielding meaning; if more than one meaning remains plausible, Ground Ball clarifies instead of guessing.

Promote the named 30-30 and 40-40 player-season recipes, the 500-home-run player-career club, and the batting Triple Crown at player-season-league grain. Triple Crown AVG leadership uses the catalog's reviewed, historically appropriate batting-title eligibility rule for that exact league-season; the recipe cannot publish for a league-season whose rule is absent. These recipes are catalog-owned compositions of the promoted values and ranks, not separate formulas or query lanes.

### Grains, groupings, filters, and operations

The named grains in the initial surface are player record, raw source row, player-season, player-team-season, player-career, team-season, and league-season. Fielding additionally supports player-position-season and player-position-career. Season questions default to player-season when that is the single baseball-meaningful interpretation, combining stints without hiding the available player-team-season or raw-row views.

The initial roll-up matrix is exact:

| Promoted values | Allowed grains beyond raw rows | Roll-up rule |
| --- | --- | --- |
| Player almanac facts | Player record; grouping and filtering at compatible result grains | Not aggregatable; one People value per player |
| Batting `G` | Player-team-season, player-season, player-career | Add stints; not available as team- or league-games |
| Other promoted batting counts | Player-team-season, player-season, player-career, team-season, league-season | Add source counts |
| Pitching `G`, `GS` | Player-team-season, player-season, player-career | Add stints; not available as team- or league-games |
| Other promoted pitching counts and outs | Player-team-season, player-season, player-career, team-season, league-season | Add source counts; `H`, `HR`, and `BB` mean allowed values in pitching context |
| Fielding `G`, `GS` | Player-position-season, player-position-career | Add stints only within one position; never add across positions |
| Fielding innings, `PO`, `A`, and `E` | Player-position-season, player-position-career, player-team-season, player-season, player-career, team-season, league-season | Add source counts or authoritative outs |
| Fielding `DP` | Player-position-season, player-position-career, player-team-season, player-season, player-career | Add player participations; not promoted as a team- or league-play total |
| AVG, OBP, SLG, and OPS | Player-team-season, player-season, player-career, team-season, league-season | Recompute from summed batting components |
| ERA and WHIP | Player-team-season, player-season, player-career, team-season, league-season | Recompute from summed pitching components and outs |
| Fielding percentage | Player-position-season, player-position-career, player-team-season, player-season, player-career, team-season, league-season | Recompute from summed `PO`, `A`, and `E` |

Named 30-30, 40-40, and batting Triple Crown recipes operate only at their declared player-season grains; the 500-home-run club operates only at player-career grain. No other roll-up is implied.

Promoted groupings include player, season, team, league, position, bats, throws, birth country or state, and the calendar year extracted from `debut`. Filters include player and team identity; exact or one-of league, position, handedness, country, and state; temporal exact, before, after, and range operations; and type-appropriate numeric comparisons and ranges over promoted fields and calculations. The Query Plan's existing `all`, `any`, and `not` composition, compatible value comparisons, ranking, deterministic sorting, browsing, and export apply without source-specific exceptions.

Exact rate values are available for named-player and explicitly filtered results. Rate leaderboards require an explicit sample floor or a reviewed catalog eligibility rule for the exact grain and season context. Otherwise Ground Ball asks one focused clarification. The product never labels an arbitrary fixed threshold as “qualified.”

### Approved relationships

Approve People-to-Batting, People-to-Pitching, and People-to-Fielding relationships through player identity, plus team-lookup relationships from each fact source through season-aware team identity. Friendly relationships are exposed to users while technical keys remain catalog and compiler details.

Cross-discipline questions may combine batting, pitching, and fielding values only after each source is independently resolved to the same explicit player-season, player-team-season, or player-career grain. Raw fact rows never join directly, so stints and fielding positions cannot multiply one another and change totals. If the shared grain is ambiguous or unavailable, planning clarifies or rejects rather than guessing.

Retrosheet game logs and streaks, franchise-continuity inference, external IDs, estimated statistics, arbitrary formulas, and every unlisted specialist field remain outside the promoted surface. Their governed deterministic routes or exhaustive raw accessibility are unchanged.
