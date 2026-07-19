"""Behavior contract for the server-owned Public Admission Policy."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest

from baseball_rag.public_admission import (
    AdmissionAttempt,
    AdmissionState,
    CasCoordinator,
    CasStore,
    InMemoryCasStore,
    MonthlyBudget,
    decide_admission,
    release_run,
    visitor_digest,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)


def test_admitted_start_atomically_charges_monthly_budget_and_creates_lease() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "admitted"
    assert transition.state.monthly_budget == MonthlyBudget(
        period="2026-07",
        charged_starts=1,
    )
    assert transition.state.starts_for("visitor-a") == (NOW,)
    assert transition.state.running[0].expires_at.isoformat() == "2026-07-19T12:00:15+00:00"


def test_101st_monthly_start_is_refused_until_the_next_utc_month() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=100))

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.state == state
    assert transition.outcome.kind == "allowance_paused"
    assert transition.outcome.reason == "monthly_start_budget_exhausted"
    assert transition.outcome.retry_at.isoformat() == "2026-08-01T00:00:00+00:00"


def test_first_start_in_a_later_month_atomically_rolls_the_budget_forward() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-06", charged_starts=87))

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "admitted"
    assert transition.state.monthly_budget == MonthlyBudget(
        period="2026-07",
        charged_starts=1,
    )


def test_second_live_run_for_one_visitor_is_busy_without_a_second_charge() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))
    first = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    second = decide_admission(
        first.state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-b", now=NOW),
    )

    assert second.state == first.state
    assert second.outcome.kind == "busy"
    assert second.outcome.reason == "visitor_run_active"
    assert second.outcome.retry_at == first.state.running[0].expires_at
    assert second.state.monthly_budget.charged_starts == 1


def test_fifth_live_run_is_deployment_busy_without_a_fifth_charge() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))
    for index in range(4):
        state = decide_admission(
            state,
            AdmissionAttempt(visitor=f"visitor-{index}", run_id=f"run-{index}", now=NOW),
        ).state

    fifth = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-4", run_id="run-4", now=NOW),
    )

    assert fifth.state == state
    assert fifth.outcome.kind == "busy"
    assert fifth.outcome.reason == "deployment_capacity_occupied"
    assert fifth.outcome.retry_at == min(lease.expires_at for lease in state.running)
    assert fifth.state.monthly_budget.charged_starts == 4


def test_fourth_start_in_a_rolling_minute_is_rate_limited_without_a_charge() -> None:
    starts = (NOW - timedelta(seconds=50), NOW - timedelta(seconds=30), NOW - timedelta(seconds=10))
    state = AdmissionState(
        starts_by_visitor=(("visitor-a", starts),),
        monthly_budget=MonthlyBudget(period="2026-07", charged_starts=3),
    )

    fourth = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-4", now=NOW),
    )

    assert fourth.state == state
    assert fourth.outcome.kind == "rate_limited"
    assert fourth.outcome.reason == "three_starts_per_minute"
    assert fourth.outcome.retry_at == NOW + timedelta(seconds=10)
    assert fourth.state.monthly_budget.charged_starts == 3


def test_cas_coordinator_allows_only_one_competing_start_for_a_visitor() -> None:
    store = InMemoryCasStore(
        AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))
    )
    coordinators = (
        CasCoordinator(store, clock=lambda: NOW),
        CasCoordinator(store, clock=lambda: NOW),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda index: coordinators[index].admit(
                    AdmissionAttempt(visitor="visitor-a", run_id=f"run-{index}", now=NOW)
                ),
                range(2),
            )
        )

    assert sorted(outcome.kind for outcome in outcomes) == ["admitted", "busy"]
    state, _ = store.read()
    assert len(state.running) == 1
    assert state.monthly_budget.charged_starts == 1


def test_thirteenth_start_in_a_rolling_hour_is_rate_limited_until_exact_expiry() -> None:
    starts = tuple(NOW - timedelta(minutes=55 - index * 5) for index in range(12))
    state = AdmissionState(
        starts_by_visitor=(("visitor-a", starts),),
        monthly_budget=MonthlyBudget(period="2026-07", charged_starts=12),
    )

    thirteenth = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-13", now=NOW),
    )

    assert thirteenth.state == state
    assert thirteenth.outcome.kind == "rate_limited"
    assert thirteenth.outcome.reason == "twelve_starts_per_hour"
    assert thirteenth.outcome.retry_at == NOW + timedelta(minutes=5)


def test_release_and_cookie_rotation_cannot_refund_deployment_budget() -> None:
    state = decide_admission(
        AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0)),
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    ).state

    released = release_run(state, "run-a")

    assert released.running == ()
    assert released.starts_for("visitor-a") == (NOW,)
    assert released.monthly_budget.charged_starts == 1
    assert visitor_digest("cookie-a", digest_key=b"key") != visitor_digest(
        "cookie-b", digest_key=b"key"
    )


def test_budget_initialization_is_create_if_absent_and_never_overwrites() -> None:
    store = InMemoryCasStore()
    coordinator = CasCoordinator(store, clock=lambda: NOW)

    assert coordinator.initialize_current_budget() is True
    assert coordinator.initialize_current_budget() is False

    state, _ = store.read()
    assert state.monthly_budget == MonthlyBudget(period="2026-07", charged_starts=0)


def test_competing_first_period_initialization_is_create_if_absent() -> None:
    store = InMemoryCasStore()
    coordinators = (
        CasCoordinator(store, clock=lambda: NOW),
        CasCoordinator(store, clock=lambda: NOW),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        initialized = tuple(
            executor.map(lambda item: item.initialize_current_budget(), coordinators)
        )

    assert sorted(initialized) == [False, True]
    state, _ = store.read()
    assert state.monthly_budget == MonthlyBudget(period="2026-07", charged_starts=0)


@pytest.mark.parametrize(
    "budget",
    [
        None,
        MonthlyBudget(period="not-a-period", charged_starts=1),
        MonthlyBudget(period="0000-01", charged_starts=1),
        MonthlyBudget(period="2026-13", charged_starts=1),
        MonthlyBudget(period="2026-07", charged_starts=-1),
        MonthlyBudget(period="2026-07", charged_starts=True),
        MonthlyBudget(period="2026-07", charged_starts=101),
        MonthlyBudget(period="2026-08", charged_starts=0),
        cast(MonthlyBudget, {"period": "2026-07", "charged_starts": 0}),
    ],
)
def test_invalid_budget_states_pause_without_mutating_state(
    budget: MonthlyBudget | None,
) -> None:
    state = AdmissionState(monthly_budget=budget)

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.state == state
    assert transition.outcome.kind == "allowance_paused"
    assert transition.outcome.reason in {
        "monthly_budget_unavailable",
        "monthly_budget_invalid",
    }


def test_atomic_hundredth_and_hundred_first_competing_starts() -> None:
    store = InMemoryCasStore(
        AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=99))
    )
    coordinators = (
        CasCoordinator(store, clock=lambda: NOW),
        CasCoordinator(store, clock=lambda: NOW),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda index: coordinators[index].admit(
                    AdmissionAttempt(
                        visitor=f"visitor-{index}",
                        run_id=f"run-{index}",
                        now=NOW,
                    )
                ),
                range(2),
            )
        )

    assert sorted(outcome.kind for outcome in outcomes) == ["admitted", "allowance_paused"]
    state, _ = store.read()
    assert state.monthly_budget == MonthlyBudget(period="2026-07", charged_starts=100)
    assert len(state.running) == 1


def test_expired_lease_recovers_capacity_without_refunding_its_start() -> None:
    first = decide_admission(
        AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0)),
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    replacement = decide_admission(
        first.state,
        AdmissionAttempt(
            visitor="visitor-a",
            run_id="run-b",
            now=NOW + timedelta(seconds=15),
        ),
    )

    assert replacement.outcome.kind == "admitted"
    assert [lease.run_id for lease in replacement.state.running] == ["run-b"]
    assert replacement.state.monthly_budget.charged_starts == 2


def test_rate_window_boundaries_expire_at_the_exact_retry_time() -> None:
    state = AdmissionState(
        starts_by_visitor=(
            (
                "visitor-a",
                (
                    NOW - timedelta(hours=1),
                    NOW - timedelta(minutes=1),
                    NOW - timedelta(seconds=30),
                ),
            ),
        ),
        monthly_budget=MonthlyBudget(period="2026-07", charged_starts=3),
    )

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "admitted"
    assert transition.state.starts_for("visitor-a") == (
        NOW - timedelta(minutes=1),
        NOW - timedelta(seconds=30),
        NOW,
    )


class _UnavailableStore:
    def read(self):
        raise OSError("sensitive internal provider detail")

    def compare_and_swap(self, version: int, state: AdmissionState) -> bool:
        raise AssertionError("compare-and-swap should not follow a failed read")


def test_store_failure_and_bounded_contention_fail_closed() -> None:
    unavailable = CasCoordinator(cast(CasStore, _UnavailableStore()), clock=lambda: NOW)
    contention_store = InMemoryCasStore(
        AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))
    )
    contention_store.compare_and_swap = lambda _version, _state: False  # type: ignore[method-assign]
    contended = CasCoordinator(contention_store, max_attempts=2, clock=lambda: NOW)
    attempt = AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW)

    assert unavailable.admit(attempt).reason == "coordination_store_unavailable"
    assert contended.admit(attempt).reason == "coordination_contention"
    state, _ = contention_store.read()
    assert state.monthly_budget.charged_starts == 0


def test_current_budget_readiness_distinguishes_invalid_state_from_store_failure() -> None:
    ready = CasCoordinator(
        InMemoryCasStore(
            AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=100))
        ),
        clock=lambda: NOW,
    )
    invalid = CasCoordinator(InMemoryCasStore(), clock=lambda: NOW)
    unavailable = CasCoordinator(cast(CasStore, _UnavailableStore()), clock=lambda: NOW)

    assert ready.readiness().kind == "ready"
    assert invalid.readiness().kind == "allowance_paused"
    assert unavailable.readiness().kind == "provider_unavailable"


def test_visitor_digest_is_stable_keyed_and_never_contains_cookie_material() -> None:
    first = visitor_digest("opaque-cookie", digest_key=b"a" * 32)

    assert first == visitor_digest("opaque-cookie", digest_key=b"a" * 32)
    assert first != visitor_digest("opaque-cookie", digest_key=b"b" * 32)
    assert "opaque-cookie" not in first
    assert len(first) == 64
