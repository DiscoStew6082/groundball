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
- Active map: `.scratch/queryable-ground-ball/map.md`
- The active map is stored on the canonical branch, not `main`. Use that branch's existing dedicated worktree for ticket work; do not switch the dirty root worktree.
- Tracker instructions: `docs/agents/issue-tracker.md`
- Select the first open, unblocked, unclaimed ticket in numeric order.
- Claim it before investigating or resolving the ticket.
- Wayfinder tickets are planning work unless the map explicitly authorizes implementation. Do not start TDD, a UI server, or browser validation for decision-only tickets.

After every context compaction, automatically re-establish Wayfinder context before responding or acting on active ticket work. Reload the complete `wayfinder` skill when it is available, then reread `docs/agents/issue-tracker.md`, the `.scratch/<effort>/map.md` that owns the currently claimed ticket, and that ticket. Use the compacted summary to identify the active effort; if it is unclear, identify the claimed ticket from the local tracker rather than asking Stewart to repeat the workflow. Resume from the recorded status, answers, and commits without requiring Stewart to re-explain anything. If the standalone skill is unavailable, treat the repository-owned Markdown workflow as authoritative and continue without searching repeatedly for the missing skill.

### Domain docs

Ground Ball uses the root `CONTEXT.md` and root `docs/adr/` as a single domain context. See `docs/agents/domain.md`.
