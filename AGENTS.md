# AGENTS.md instructions for /Volumes/Envoy/projects/groundball

Use the tdd skill for dev work.
Use subagents wherever possible and a code review subagent should be run after every task.
You are not finished coding until your changes have been committed and any unstaged changes are explained.
If you have pushed to GitHub make sure the CI comes back green.
Use the Codex in-app Browser to troubleshoot this project. Start the local UI if needed with `uv run groundball-ui`, open `http://127.0.0.1:7861/`, make the Browser visible, run a quick default-query smoke test, and keep the dev server running.

## Agent skills

### Issue tracker

Wayfinder maps and tickets use local Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

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

### Domain docs

Ground Ball uses the root `CONTEXT.md` and root `docs/adr/` as a single domain context. See `docs/agents/domain.md`.
