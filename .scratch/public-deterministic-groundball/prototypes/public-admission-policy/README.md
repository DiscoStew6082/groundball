# Public Admission Policy throwaway prototype

## Question

Can one server-owned admission state transition express the approved anonymous Visitor, per-Visitor running/rate, deployment-wide running, provider-allowance, actionable-refusal, and last-completed-result rules while independent stateless instances coordinate through one compare-and-swap Interface?

This prototype answers only that logic question. It is intentionally offline, in-memory, and marked throwaway. `InMemoryCasStore` models the consistent-read plus ETag conditional-write semantics documented for private Vercel Blob; it is not evidence that a Blob store was provisioned. The accompanying official-platform note supplies that platform evidence and records the independent provider-usage-signal failure.

## Run

From the canonical tracker worktree:

```bash
uv run python .scratch/public-deterministic-groundball/prototypes/public-admission-policy/demo.py
```

The initial state has no provider usage signal, so every admission fails closed. Press `u` to inject an explicitly synthetic current signal and exercise the CAS-coordinated running and rate outcomes. The screen re-renders the complete relevant state after every action.

Focused throwaway behavior proof:

```bash
uv run pytest -q .scratch/public-deterministic-groundball/prototypes/public-admission-policy/test_policy.py
```

## Verdict

The state model works behind one small Interface:

- an opaque first-party cookie becomes a one-way Visitor digest;
- one CAS transition checks the versioned allowance snapshot, one running Run per Visitor, four running Runs deployment-wide, and both rolling rate windows before adding the start and a lease derived from current coordinator time with five seconds of margin beyond the ten-second execution deadline;
- refusals do not mutate admission state and include exact retry time when one exists;
- completion removes only the lease and retains rate history;
- browser completion state is separate from an actionable attempt outcome.

Private Vercel Blob can now supply the CAS semantics within Hobby's included operation limits. Vercel Hobby still cannot supply the required current, trustworthy CPU/memory allowance snapshot. The real policy therefore remains permanently `allowance_paused` unless the hosting or allowance guardrail decision reopens; the synthetic `u` input exists only to inspect the otherwise-feasible transitions and must not be mistaken for a production signal.

No deployment, Blob store, account setting, domain, secret, paid feature, Mac, tunnel, LLM, or alternate host is used.
