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
