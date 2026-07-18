# Issue tracker: Local Markdown

Ground Ball tracks Wayfinder efforts under `.scratch/<effort>/`.

## Wayfinding operations

- Map: `.scratch/<effort>/map.md`
- Child ticket: `.scratch/<effort>/issues/NN-<slug>.md`
- Each ticket records Type, Status (`open`, `claimed`, or `resolved`), and Blocked by.
- Blocking entries use linked ticket names rather than bare issue numbers.
- The frontier consists of open, unblocked, unclaimed tickets in numeric order.
- "Next ticket" follows numeric order across unresolved tickets whose blockers are resolved. A claimed ticket holds its place: report it and stop rather than resuming it or skipping to a later frontier ticket.
- Claim a ticket by setting Status to claimed before beginning work.
- If its session was orphaned, first verify that no session is still working it. With Stewart's explicit confirmation, release the orphaned claim by setting Status back to open, preserve and review any existing answer, assets, or commits, then claim that same ticket in the new session before continuing.
- Resolve it by adding an Answer, setting Status to resolved, and appending its linked gist to the map's Decisions so far.

## Active tracker checkout

- Canonical branch: `wayfinder/queryable-ground-ball`
- Stable worktree: `.worktrees/queryable-ground-ball` from the repository root
- Discover it with `git worktree list --porcelain`.
- If the local branch exists but the worktree does not, run `git worktree add .worktrees/queryable-ground-ball wayfinder/queryable-ground-ball` from the repository root.
- After a fresh clone, fetch first, then run `git worktree add --track -b wayfinder/queryable-ground-ball .worktrees/queryable-ground-ball origin/wayfinder/queryable-ground-ball`.
- Do not switch the root worktree to the Wayfinder branch; it may contain unrelated local deployment state.
