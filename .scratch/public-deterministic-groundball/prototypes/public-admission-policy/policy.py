"""PROTOTYPE: pure Public Admission Policy state transition."""

from __future__ import annotations

import hashlib
import hmac
import math
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Protocol

ACTIVE_CPU_SAFETY_TARGET_HOURS = 2.8
MEMORY_SAFETY_TARGET_GB_HOURS = 252.0
RUN_DEADLINE = timedelta(seconds=10)
LEASE_SAFETY_MARGIN = timedelta(seconds=5)


def visitor_digest(opaque_cookie: str, *, digest_key: bytes) -> str:
    """Keep the opaque first-party token out of shared coordination state."""
    return hmac.new(digest_key, opaque_cookie.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class AllowanceSnapshot:
    observed_at: datetime
    active_cpu_hours: float
    provisioned_memory_gb_hours: float
    trustworthy_until: datetime


@dataclass(frozen=True)
class AdmissionAttempt:
    visitor: str
    run_id: str
    now: datetime


@dataclass(frozen=True)
class RunLease:
    visitor: str
    run_id: str
    expires_at: datetime


@dataclass(frozen=True)
class AdmissionState:
    running: tuple[RunLease, ...] = ()
    starts_by_visitor: tuple[tuple[str, tuple[datetime, ...]], ...] = ()
    allowance: AllowanceSnapshot | None = None

    @classmethod
    def empty(cls) -> AdmissionState:
        return cls()

    def starts_for(self, visitor: str) -> tuple[datetime, ...]:
        return dict(self.starts_by_visitor).get(visitor, ())


@dataclass(frozen=True)
class AdmissionOutcome:
    kind: str
    reason: str
    retry_at: datetime | None = None


@dataclass(frozen=True)
class AdmissionTransition:
    state: AdmissionState
    outcome: AdmissionOutcome


@dataclass(frozen=True)
class BrowserReadModel:
    last_completed_run: dict[str, object] | None = None
    attempt_outcome: dict[str, object] | None = None

    def with_attempt_outcome(
        self,
        *,
        outcome_kind: str,
        message: str,
        retry_at: datetime | None,
    ) -> BrowserReadModel:
        return BrowserReadModel(
            last_completed_run=self.last_completed_run,
            attempt_outcome={
                "kind": outcome_kind,
                "message": message,
                "retry_at": retry_at.isoformat() if retry_at else None,
            },
        )


class CasStore(Protocol):
    """The only coordination Interface required from private Vercel Blob."""

    def read(self) -> tuple[AdmissionState, int]: ...

    def compare_and_swap(self, version: int, state: AdmissionState) -> bool: ...


class InMemoryCasStore:
    """PROTOTYPE Adapter with the documented ETag compare-and-swap semantics."""

    def __init__(self) -> None:
        self._state = AdmissionState.empty()
        self._version = 0
        self._lock = Lock()

    def read(self) -> tuple[AdmissionState, int]:
        with self._lock:
            return self._state, self._version

    def compare_and_swap(self, version: int, state: AdmissionState) -> bool:
        with self._lock:
            if version != self._version:
                return False
            self._state = state
            self._version += 1
            return True


class CasCoordinator:
    def __init__(
        self,
        store: CasStore,
        *,
        max_attempts: int = 8,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._max_attempts = max_attempts
        self._clock = clock or (lambda: datetime.now(UTC))

    def admit(
        self,
        attempt: AdmissionAttempt,
    ) -> AdmissionOutcome:
        for _ in range(self._max_attempts):
            state, version = self._store.read()
            decision_attempt = replace(attempt, now=max(attempt.now, self._clock()))
            transition = decide_admission(state, decision_attempt)
            if transition.outcome.kind != "admitted":
                return transition.outcome
            if self._store.compare_and_swap(version, transition.state):
                return transition.outcome
        return AdmissionOutcome(
            kind="provider_unavailable",
            reason="coordination_contention",
        )

    def release(self, run_id: str) -> bool:
        for _ in range(self._max_attempts):
            state, version = self._store.read()
            released = release_run(state, run_id)
            if released == state:
                return False
            if self._store.compare_and_swap(version, released):
                return True
        return False

    def set_allowance(self, allowance: AllowanceSnapshot | None) -> bool:
        for _ in range(self._max_attempts):
            state, version = self._store.read()
            updated = AdmissionState(
                running=state.running,
                starts_by_visitor=state.starts_by_visitor,
                allowance=allowance,
            )
            if self._store.compare_and_swap(version, updated):
                return True
        return False


def release_run(state: AdmissionState, run_id: str) -> AdmissionState:
    return AdmissionState(
        running=tuple(lease for lease in state.running if lease.run_id != run_id),
        starts_by_visitor=state.starts_by_visitor,
        allowance=state.allowance,
    )


def decide_admission(
    state: AdmissionState,
    attempt: AdmissionAttempt,
) -> AdmissionTransition:
    """Return a fail-closed decision without performing I/O."""
    allowance = state.allowance
    if allowance is None:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="allowance_paused",
                reason="provider_usage_unavailable",
            ),
        )
    if (
        not isinstance(allowance.observed_at, datetime)
        or not isinstance(allowance.trustworthy_until, datetime)
        or not isinstance(attempt.now, datetime)
    ):
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="allowance_paused",
                reason="provider_usage_invalid",
            ),
        )
    meters = (allowance.active_cpu_hours, allowance.provisioned_memory_gb_hours)
    timestamps_are_aware = (
        allowance.observed_at.utcoffset() is not None
        and allowance.trustworthy_until.utcoffset() is not None
        and attempt.now.utcoffset() is not None
    )
    if (
        not timestamps_are_aware
        or allowance.observed_at > attempt.now
        or allowance.trustworthy_until < allowance.observed_at
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
            for value in meters
        )
    ):
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="allowance_paused",
                reason="provider_usage_invalid",
            ),
        )
    if attempt.now > allowance.trustworthy_until:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="allowance_paused",
                reason="provider_usage_stale",
            ),
        )
    if allowance.active_cpu_hours >= ACTIVE_CPU_SAFETY_TARGET_HOURS:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="allowance_paused",
                reason="active_cpu_at_safety_target",
            ),
        )
    if allowance.provisioned_memory_gb_hours >= MEMORY_SAFETY_TARGET_GB_HOURS:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="allowance_paused",
                reason="provisioned_memory_at_safety_target",
            ),
        )
    live_running = tuple(lease for lease in state.running if lease.expires_at > attempt.now)
    recent_starts = {
        visitor: tuple(start for start in starts if start > attempt.now - timedelta(hours=1))
        for visitor, starts in state.starts_by_visitor
    }
    cleaned = AdmissionState(
        running=live_running,
        starts_by_visitor=tuple(
            sorted((visitor, starts) for visitor, starts in recent_starts.items() if starts)
        ),
        allowance=allowance,
    )
    visitor_lease = next(
        (lease for lease in live_running if lease.visitor == attempt.visitor),
        None,
    )
    if visitor_lease is not None:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="busy",
                reason="visitor_run_active",
                retry_at=visitor_lease.expires_at,
            ),
        )
    if len(live_running) >= 4:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="busy",
                reason="deployment_capacity_occupied",
                retry_at=min(lease.expires_at for lease in live_running),
            ),
        )
    starts = dict(cleaned.starts_by_visitor)
    visitor_starts = starts.get(attempt.visitor, ())
    minute_starts = tuple(
        start for start in visitor_starts if start > attempt.now - timedelta(minutes=1)
    )
    if len(minute_starts) >= 3:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="rate_limited",
                reason="three_starts_per_minute",
                retry_at=min(minute_starts) + timedelta(minutes=1),
            ),
        )
    if len(visitor_starts) >= 12:
        return AdmissionTransition(
            state=state,
            outcome=AdmissionOutcome(
                kind="rate_limited",
                reason="twelve_starts_per_hour",
                retry_at=min(visitor_starts) + timedelta(hours=1),
            ),
        )
    starts[attempt.visitor] = (*starts.get(attempt.visitor, ()), attempt.now)
    admitted = AdmissionState(
        running=(
            *cleaned.running,
            RunLease(
                visitor=attempt.visitor,
                run_id=attempt.run_id,
                expires_at=attempt.now + RUN_DEADLINE + LEASE_SAFETY_MARGIN,
            ),
        ),
        starts_by_visitor=tuple(sorted(starts.items())),
        allowance=allowance,
    )
    return AdmissionTransition(
        state=admitted,
        outcome=AdmissionOutcome(kind="admitted", reason="within_policy"),
    )
