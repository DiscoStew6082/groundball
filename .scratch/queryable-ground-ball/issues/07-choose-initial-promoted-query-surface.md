# Choose the initial promoted query surface

Type: `grilling`
Status: claimed
Blocked by: [Prototype the mobile Query Recipe experience](01-prototype-mobile-query-experience.md), [Specify the Published Query Catalog Interface](02-specify-published-query-catalog-interface.md), [Specify the deterministic Query Plan Interface](03-specify-deterministic-query-plan-interface.md), [Define completeness and verification gates](04-define-completeness-and-verification-gates.md)

## Question

Which exact current Lahman fields receive first-class natural-language treatment, which statistics and exact derived calculations are promoted, and which approved joins, filters, and groupings belong in the initial shared query surface while every raw loaded Lahman field and team-reference field remains discoverable? Numeric request, result, export, and hosting safety ceilings remain owned by the zero-Mac public-demo map.

## Working decisions

- Promote a coherent historical-almanac core rather than freezing the narrower current registry.
- Promote player, season, team, league, and position as first-class dimensions.
- Promote player name, birth and death dates and places, bats, throws, height, weight, debut, and final game as first-class almanac facts.
- Promote batting `G`, `AB`, `R`, `H`, `2B`, `3B`, `HR`, `RBI`, `SB`, `CS`, `BB`, and `SO`; pitching `W`, `L`, `G`, `GS`, `CG`, `SHO`, `SV`, innings pitched, `H`, `ER`, `HR`, `BB`, and `SO`; and fielding position, `G`, `GS`, innings, `PO`, `A`, `E`, and `DP`.
- Promote exact AVG, OBP, SLG, OPS, ERA, WHIP, and fielding-percentage calculations, plus named 30-30, 40-40, 500-HR-club, and Triple Crown recipes.
- All other loaded fields remain reachable through raw-field discovery and generic structured controls without first-class natural-language treatment.
- Exact rate values remain available for named-player and explicitly filtered queries. Rate leaderboards require an explicit sample floor or a reviewed catalog eligibility rule for the exact grain and season context; otherwise Ground Ball asks one focused clarification. The product never labels an arbitrary fixed threshold as “qualified.”
- Promote cross-discipline questions that combine batting, pitching, or fielding values only after each source is resolved to the same explicit named grain: player-season, player-team-season, or player-career. Ambiguous grain requires clarification, and raw fact rows never combine directly.
