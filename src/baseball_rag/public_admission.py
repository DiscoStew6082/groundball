"""Server-owned admission policy for public Query Runs."""

from __future__ import annotations

import hashlib
import hmac
import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Iterator, Protocol

from baseball_rag.public_release_config import (
    DEPLOYMENT_CONCURRENCY_LIMIT,
    EXECUTION_DEADLINE_SECONDS,
    LEASE_SECONDS,
    MAXIMUM_CAS_ATTEMPTS,
    MONTHLY_START_LIMIT,
    VISITOR_STARTS_PER_HOUR,
    VISITOR_STARTS_PER_MINUTE,
)

RUN_DEADLINE = timedelta(seconds=EXECUTION_DEADLINE_SECONDS)
RUN_LEASE_DURATION = timedelta(seconds=LEASE_SECONDS)
_BUDGET_PERIOD_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


def visitor_digest(opaque_cookie: str, *, digest_key: bytes) -> str:
    """Keep the opaque first-party Visitor token out of coordination state."""
    return hmac.new(digest_key, opaque_cookie.encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class MonthlyBudget:
    period: str
    charged_starts: int


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
    monthly_budget: MonthlyBudget | None = None

    def starts_for(self, visitor: str) -> tuple[datetime, ...]:
        return dict(self.starts_by_visitor).get(visitor, ())


@dataclass(frozen=True)
class AdmissionOutcome:
    kind: str
    reason: str
    retry_at: datetime | None = None
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class AdmissionTransition:
    state: AdmissionState
    outcome: AdmissionOutcome


class CoordinationStateError(ValueError):
    """Shared state is present but cannot safely authorize a Query Run."""


@dataclass(frozen=True)
class CasVersion:
    """Opaque store-specific version retained only for a matching CAS write."""

    _token: object = field(repr=False)


@dataclass(frozen=True)
class CasSnapshot:
    state: AdmissionState
    version: CasVersion
    observed_at: datetime | None = None
    exists: bool = True

    def __iter__(self) -> Iterator[AdmissionState | CasVersion]:
        """Preserve state/version unpacking while time remains snapshot-scoped."""
        yield self.state
        yield self.version


class CasStore(Protocol):
    """Versioned coordination state shared by stateless server instances."""

    @property
    def deployment_shared(self) -> bool: ...

    def read(self) -> CasSnapshot: ...

    def compare_and_swap(self, version: CasVersion, state: AdmissionState) -> bool: ...


@dataclass(frozen=True)
class _MemoryVersion:
    value: int


class InMemoryCasStore:
    """Process-local Adapter for behavior proof; never deployment authority."""

    def __init__(self, state: AdmissionState | None = None) -> None:
        self._state = state or AdmissionState()
        self._exists = state is not None
        self._version = 0
        self._lock = Lock()

    @property
    def deployment_shared(self) -> bool:
        return False

    def read(self) -> CasSnapshot:
        with self._lock:
            return CasSnapshot(
                state=self._state,
                version=CasVersion(_MemoryVersion(self._version)),
                exists=self._exists,
            )

    def compare_and_swap(self, version: CasVersion, state: AdmissionState) -> bool:
        with self._lock:
            if version != CasVersion(_MemoryVersion(self._version)):
                return False
            self._state = state
            self._exists = True
            self._version += 1
            return True


class CasCoordinator:
    """Apply the policy through bounded compare-and-swap retries."""

    def __init__(
        self,
        store: CasStore,
        *,
        max_attempts: int = MAXIMUM_CAS_ATTEMPTS,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._max_attempts = max_attempts
        self._clock = clock or (lambda: datetime.now(UTC))

    def admit(self, attempt: AdmissionAttempt) -> AdmissionOutcome:
        try:
            for _ in range(self._max_attempts):
                snapshot = self._store.read()
                transition = decide_admission(
                    snapshot.state,
                    replace(attempt, now=self._snapshot_time(snapshot)),
                )
                if transition.outcome.kind != "admitted":
                    return transition.outcome
                if self._store.compare_and_swap(snapshot.version, transition.state):
                    return transition.outcome
        except CoordinationStateError:
            return AdmissionOutcome("allowance_paused", "monthly_budget_invalid")
        except Exception:  # noqa: BLE001 - the policy must fail closed on Adapter failure
            return AdmissionOutcome("provider_unavailable", "coordination_store_unavailable")
        return AdmissionOutcome("provider_unavailable", "coordination_contention")

    def _snapshot_time(self, snapshot: CasSnapshot) -> datetime:
        return snapshot.observed_at if snapshot.observed_at is not None else self._clock()

    def readiness(self) -> AdmissionOutcome:
        """Check reachability and a budget valid now or safe for UTC rollover."""
        try:
            snapshot = self._store.read()
            now = self._snapshot_time(snapshot)
        except CoordinationStateError:
            return AdmissionOutcome("allowance_paused", "monthly_budget_invalid")
        except Exception:  # noqa: BLE001 - readiness must not leak Adapter details
            return AdmissionOutcome("provider_unavailable", "coordination_store_unavailable")
        invalid = _budget_invalid_outcome(snapshot.state.monthly_budget, now)
        if invalid is not None:
            return invalid
        return AdmissionOutcome("ready", "public_admission_ready")

    def initialize_current_budget(self) -> bool:
        """Create the current zero budget once without replacing any record."""
        try:
            for _ in range(self._max_attempts):
                snapshot = self._store.read()
                period = _period_key(self._snapshot_time(snapshot))
                if period is None or snapshot.exists or snapshot.state.monthly_budget is not None:
                    return False
                initialized = replace(
                    snapshot.state,
                    monthly_budget=MonthlyBudget(
                        period=f"{period[0]:04d}-{period[1]:02d}",
                        charged_starts=0,
                    ),
                )
                if self._store.compare_and_swap(snapshot.version, initialized):
                    return True
        except Exception:  # noqa: BLE001 - initialization must stop on Adapter failure
            return False
        return False

    def release(self, run_id: str) -> bool:
        try:
            for _ in range(self._max_attempts):
                snapshot = self._store.read()
                released = release_run(snapshot.state, run_id)
                if released == snapshot.state:
                    return False
                if self._store.compare_and_swap(snapshot.version, released):
                    return True
        except Exception:  # noqa: BLE001 - an expiring lease remains the fail-safe
            return False
        return False


def release_run(state: AdmissionState, run_id: str) -> AdmissionState:
    """Release only the live lease; starts and monthly charges are never refunded."""
    return AdmissionState(
        running=tuple(lease for lease in state.running if lease.run_id != run_id),
        starts_by_visitor=state.starts_by_visitor,
        monthly_budget=state.monthly_budget,
    )


def decide_admission(
    state: AdmissionState,
    attempt: AdmissionAttempt,
) -> AdmissionTransition:
    """Atomically describe one admitted public Query Run start."""
    budget = state.monthly_budget
    invalid = _budget_invalid_outcome(budget, attempt.now)
    if invalid is not None:
        return AdmissionTransition(state=state, outcome=invalid)
    assert isinstance(budget, MonthlyBudget)
    current_period = _period_key(attempt.now)
    budget_period = _parse_period(budget.period)
    assert current_period is not None and budget_period is not None
    if budget_period < current_period:
        budget = MonthlyBudget(
            period=f"{current_period[0]:04d}-{current_period[1]:02d}",
            charged_starts=0,
        )
    if budget.charged_starts >= MONTHLY_START_LIMIT:
        return AdmissionTransition(
            state=state,
            outcome=_retry_outcome(
                "allowance_paused",
                "monthly_start_budget_exhausted",
                now=attempt.now,
                retry_at=_next_month(attempt.now),
            ),
        )

    live_running = tuple(lease for lease in state.running if lease.expires_at > attempt.now)
    visitor_lease = next(
        (lease for lease in live_running if lease.visitor == attempt.visitor),
        None,
    )
    if visitor_lease is not None:
        return AdmissionTransition(
            state=state,
            outcome=_retry_outcome(
                "busy",
                "visitor_run_active",
                now=attempt.now,
                retry_at=visitor_lease.expires_at,
            ),
        )
    if len(live_running) >= DEPLOYMENT_CONCURRENCY_LIMIT:
        return AdmissionTransition(
            state=state,
            outcome=_retry_outcome(
                "busy",
                "deployment_capacity_occupied",
                now=attempt.now,
                retry_at=min(lease.expires_at for lease in live_running),
            ),
        )

    starts = {
        visitor: tuple(
            start for start in visitor_starts if start > attempt.now - timedelta(hours=1)
        )
        for visitor, visitor_starts in state.starts_by_visitor
    }
    visitor_starts = starts.get(attempt.visitor, ())
    minute_starts = tuple(
        start for start in visitor_starts if start > attempt.now - timedelta(minutes=1)
    )
    if len(minute_starts) >= VISITOR_STARTS_PER_MINUTE:
        return AdmissionTransition(
            state=state,
            outcome=_retry_outcome(
                "rate_limited",
                "three_starts_per_minute",
                now=attempt.now,
                retry_at=min(minute_starts) + timedelta(minutes=1),
            ),
        )
    if len(visitor_starts) >= VISITOR_STARTS_PER_HOUR:
        return AdmissionTransition(
            state=state,
            outcome=_retry_outcome(
                "rate_limited",
                "twelve_starts_per_hour",
                now=attempt.now,
                retry_at=min(visitor_starts) + timedelta(hours=1),
            ),
        )
    starts[attempt.visitor] = (*visitor_starts, attempt.now)
    admitted = AdmissionState(
        running=(
            *live_running,
            RunLease(
                visitor=attempt.visitor,
                run_id=attempt.run_id,
                expires_at=attempt.now + RUN_LEASE_DURATION,
            ),
        ),
        starts_by_visitor=tuple(
            sorted(
                (visitor, visitor_starts)
                for visitor, visitor_starts in starts.items()
                if visitor_starts
            )
        ),
        monthly_budget=MonthlyBudget(
            period=budget.period,
            charged_starts=budget.charged_starts + 1,
        ),
    )
    return AdmissionTransition(
        state=admitted,
        outcome=AdmissionOutcome("admitted", "within_policy"),
    )


def _budget_invalid_outcome(
    budget: object,
    now: datetime,
) -> AdmissionOutcome | None:
    if budget is None:
        return AdmissionOutcome("allowance_paused", "monthly_budget_unavailable")
    current_period = _period_key(now)
    if not isinstance(budget, MonthlyBudget):
        return AdmissionOutcome("allowance_paused", "monthly_budget_invalid")
    budget_period = _parse_period(budget.period)
    charged_starts = budget.charged_starts
    if (
        current_period is None
        or budget_period is None
        or isinstance(charged_starts, bool)
        or not isinstance(charged_starts, int)
        or not 0 <= charged_starts <= MONTHLY_START_LIMIT
        or budget_period > current_period
    ):
        return AdmissionOutcome("allowance_paused", "monthly_budget_invalid")
    return None


def _retry_outcome(
    kind: str,
    reason: str,
    *,
    now: datetime,
    retry_at: datetime,
) -> AdmissionOutcome:
    retry_after_seconds = max(0, math.ceil((retry_at - now).total_seconds()))
    return AdmissionOutcome(kind, reason, retry_at, retry_after_seconds)


def _next_month(now: datetime) -> datetime:
    utc_now = now.astimezone(UTC)
    year = utc_now.year + (1 if utc_now.month == 12 else 0)
    month = 1 if utc_now.month == 12 else utc_now.month + 1
    return datetime(year, month, 1, tzinfo=UTC)


def _period_key(now: datetime) -> tuple[int, int] | None:
    if now.utcoffset() is None:
        return None
    utc_now = now.astimezone(UTC)
    return utc_now.year, utc_now.month


def _parse_period(period: object) -> tuple[int, int] | None:
    if not isinstance(period, str):
        return None
    match = _BUDGET_PERIOD_PATTERN.fullmatch(period)
    if match is None:
        return None
    year, month = (int(part) for part in match.groups())
    if not 1 <= year <= 9999 or not 1 <= month <= 12:
        return None
    return year, month
