"""PROTOTYPE TUI for driving the Public Admission Policy state model."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from policy import (
    AdmissionAttempt,
    AdmissionState,
    AllowanceSnapshot,
    CasCoordinator,
    InMemoryCasStore,
    visitor_digest,
)

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
PROTOTYPE_DIGEST_KEY = b"public-admission-policy-prototype-only"


def render_frame(
    *,
    state: AdmissionState,
    last_outcome: str,
    now: datetime | None = None,
) -> str:
    clock = now or datetime.now(UTC)
    allowance = state.allowance
    if allowance is None:
        allowance_line = "provider allowance: unavailable -> FAIL CLOSED"
    else:
        allowance_line = (
            "provider allowance: "
            f"CPU {allowance.active_cpu_hours:.2f}/2.80 h; "
            f"memory {allowance.provisioned_memory_gb_hours:.2f}/252.00 GB-h; "
            f"trustworthy until {allowance.trustworthy_until.isoformat()}"
        )
    leases = (
        "\n".join(
            f"  {lease.run_id}: {lease.visitor[:12]}… until {lease.expires_at.isoformat()}"
            for lease in state.running
        )
        or "  none"
    )
    starts = (
        "\n".join(
            f"  {visitor[:12]}…: {len(timestamps)} start(s) in retained hour"
            for visitor, timestamps in state.starts_by_visitor
        )
        or "  none"
    )
    return "\n".join(
        (
            f"{BOLD}PUBLIC ADMISSION POLICY — THROWAWAY PROTOTYPE{RESET}",
            f"{DIM}clock: {clock.isoformat()}{RESET}",
            "",
            f"{BOLD}Shared CAS state{RESET}",
            f"running leases: {len(state.running)} / 4",
            leases,
            "visitor starts:",
            starts,
            "",
            f"{BOLD}Allowance input{RESET}",
            allowance_line,
            "",
            f"{BOLD}Last outcome{RESET}",
            last_outcome,
            "",
            f"{BOLD}[a VISITOR]{RESET} admit  {BOLD}[f RUN]{RESET} finish  "
            f"{BOLD}[u]{RESET} synthetic current usage  {BOLD}[x]{RESET} remove usage  "
            f"{BOLD}[t]{RESET} +10s  {BOLD}[q]{RESET} quit",
        )
    )


def main() -> None:
    store = InMemoryCasStore()
    now = datetime.now(UTC).replace(microsecond=0)
    coordinator = CasCoordinator(store, clock=lambda: now)
    last_outcome = "No attempt yet. Missing provider usage will fail closed."
    run_number = 0

    while True:
        state, _ = store.read()
        print("\x1b[2J\x1b[H", end="")
        print(
            render_frame(
                state=state,
                last_outcome=last_outcome,
                now=now,
            )
        )
        command = input("\n> ").strip().split()
        if not command:
            continue
        if command[0] == "q":
            return
        if command[0] == "t":
            now += timedelta(seconds=10)
            continue
        if command[0] == "u":
            coordinator.set_allowance(
                AllowanceSnapshot(
                    observed_at=now,
                    active_cpu_hours=1.0,
                    provisioned_memory_gb_hours=100.0,
                    trustworthy_until=now + timedelta(minutes=1),
                )
            )
            last_outcome = "Synthetic usage injected; Vercel Hobby cannot supply this feed."
            continue
        if command[0] == "x":
            coordinator.set_allowance(None)
            last_outcome = "Provider usage removed; admission must fail closed."
            continue
        if command[0] == "a" and len(command) == 2:
            run_number += 1
            visitor = visitor_digest(command[1], digest_key=PROTOTYPE_DIGEST_KEY)
            outcome = coordinator.admit(
                AdmissionAttempt(visitor=visitor, run_id=f"run-{run_number}", now=now)
            )
            retry = f"; retry at {outcome.retry_at.isoformat()}" if outcome.retry_at else ""
            last_outcome = f"{outcome.kind}: {outcome.reason}{retry}"
            continue
        if command[0] == "f" and len(command) == 2:
            released = coordinator.release(command[1])
            last_outcome = f"{'released' if released else 'not_found'}: {command[1]}"
            continue
        last_outcome = "Unknown command. Use a/f/u/x/t/q."


if __name__ == "__main__":
    main()
