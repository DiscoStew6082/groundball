### Active Wayfinder effort

When Stewart says "next ticket," load the Wayfinder skill and use the local-Markdown tracker.

- Canonical branch: `wayfinder/queryable-ground-ball`
- Stable worktree: `.worktrees/queryable-ground-ball` from the repository root
- Active map: `.scratch/public-deterministic-groundball/map.md`
- Completed predecessor map: `.scratch/queryable-ground-ball/map.md`. It records the completed Queryable Ground Ball planning effort and is not the active target for "next ticket" shorthand.
- The active map and completed predecessor map are stored on the canonical branch, not `main`. Resolve its checkout with `git worktree list --porcelain`; if the stable worktree is absent, recreate it using `docs/agents/issue-tracker.md`. Never switch the root worktree to the Wayfinder branch.
- Tracker instructions: `docs/agents/issue-tracker.md`
- "Next ticket" follows numeric order across unresolved, unblocked tickets. If the first one is already claimed, report the claim and stop; do not resume it or skip to a later ticket. Explain that an orphaned claim must be explicitly released before the same ticket can be claimed in a new session.
- Claim an unclaimed ticket before investigating or resolving it.
- Wayfinder tickets are planning work unless the map explicitly authorizes implementation. Do not start TDD, a UI server, or browser validation for decision-only tickets.
