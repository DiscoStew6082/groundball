# AGENTS.md instructions for /Volumes/Envoy/projects/groundball

Use the tdd skill for dev work.
Use subagents wherever possible and a code review subagent should be run after every task.
You are not finished coding until your changes have been committed and any unstaged changes are explained.
If you have pushed to GitHub make sure the CI comes back green.
Use the Codex in-app Browser to troubleshoot this project. Start the local UI if needed with `uv run groundball-ui`, open `http://127.0.0.1:7861/`, make the Browser visible, run a quick default-query smoke test, and keep the dev server running.

## Agent skills

### Issue tracker

Wayfinder maps and tickets use local Markdown under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Domain docs

Ground Ball uses the root `CONTEXT.md` and root `docs/adr/` as a single domain context. See `docs/agents/domain.md`.
