"""Throwaway behavior proof for the Public Admission Policy prototype."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import cast

from demo import render_frame
from policy import (
    AdmissionAttempt,
    AdmissionState,
    AllowanceSnapshot,
    BrowserReadModel,
    CasCoordinator,
    InMemoryCasStore,
    decide_admission,
    release_run,
    visitor_digest,
)

NOW = datetime(2026, 7, 18, 18, 0, tzinfo=UTC)
CURRENT_ALLOWANCE = AllowanceSnapshot(
    observed_at=NOW,
    active_cpu_hours=1.0,
    provisioned_memory_gb_hours=100.0,
    trustworthy_until=NOW + timedelta(hours=2),
)


def state_with_allowance(
    allowance: AllowanceSnapshot = CURRENT_ALLOWANCE,
) -> AdmissionState:
    return replace(AdmissionState.empty(), allowance=allowance)


def test_missing_provider_allowance_signal_fails_closed_without_changing_state() -> None:
    state = AdmissionState.empty()

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "allowance_paused"
    assert transition.outcome.reason == "provider_usage_unavailable"
    assert transition.outcome.retry_at is None
    assert transition.state == state


def test_current_allowance_below_target_atomically_admits_one_run() -> None:
    transition = decide_admission(
        state_with_allowance(
            AllowanceSnapshot(
                observed_at=NOW,
                active_cpu_hours=2.79,
                provisioned_memory_gb_hours=251.99,
                trustworthy_until=NOW,
            )
        ),
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "admitted"
    assert transition.outcome.reason == "within_policy"
    assert len(transition.state.running) == 1
    assert transition.state.starts_for("visitor-a") == (NOW,)


def test_70_percent_allowance_threshold_pauses_without_changing_state() -> None:
    state = state_with_allowance(
        AllowanceSnapshot(
            observed_at=NOW,
            active_cpu_hours=2.8,
            provisioned_memory_gb_hours=100.0,
            trustworthy_until=NOW,
        )
    )

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "allowance_paused"
    assert transition.outcome.reason == "active_cpu_at_safety_target"
    assert transition.state == state


def test_70_percent_memory_threshold_pauses_without_changing_state() -> None:
    state = state_with_allowance(
        AllowanceSnapshot(
            observed_at=NOW,
            active_cpu_hours=1.0,
            provisioned_memory_gb_hours=252.0,
            trustworthy_until=NOW,
        )
    )

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "allowance_paused"
    assert transition.outcome.reason == "provisioned_memory_at_safety_target"
    assert transition.state == state


def test_second_running_query_for_same_visitor_is_busy_with_exact_retry() -> None:
    first = decide_admission(
        state_with_allowance(),
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    second = decide_admission(
        first.state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-b", now=NOW),
    )

    assert second.outcome.kind == "busy"
    assert second.outcome.reason == "visitor_run_active"
    assert second.outcome.retry_at == first.state.running[0].expires_at
    assert second.state == first.state


def test_fifth_running_query_is_deployment_busy_with_earliest_retry() -> None:
    state = state_with_allowance()
    for index in range(4):
        state = decide_admission(
            state,
            AdmissionAttempt(visitor=f"visitor-{index}", run_id=f"run-{index}", now=NOW),
        ).state

    fifth = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-4", run_id="run-4", now=NOW),
    )

    assert fifth.outcome.kind == "busy"
    assert fifth.outcome.reason == "deployment_capacity_occupied"
    assert fifth.outcome.retry_at == min(lease.expires_at for lease in state.running)
    assert fifth.state == state


def test_fourth_start_in_one_minute_is_rate_limited_until_exact_expiry() -> None:
    state = state_with_allowance()
    for index in range(3):
        started_at = NOW + timedelta(seconds=index * 10)
        state = decide_admission(
            state,
            AdmissionAttempt(visitor="visitor-a", run_id=f"run-{index}", now=started_at),
        ).state
        state = release_run(state, f"run-{index}")

    fourth = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-3", now=NOW + timedelta(seconds=30)),
    )

    assert fourth.outcome.kind == "rate_limited"
    assert fourth.outcome.reason == "three_starts_per_minute"
    assert fourth.outcome.retry_at == NOW + timedelta(seconds=60)
    assert fourth.state == state


def test_thirteenth_start_in_one_hour_is_rate_limited_until_exact_expiry() -> None:
    state = state_with_allowance()
    for index in range(12):
        started_at = NOW + timedelta(minutes=index * 5)
        state = decide_admission(
            state,
            AdmissionAttempt(visitor="visitor-a", run_id=f"run-{index}", now=started_at),
        ).state
        state = release_run(state, f"run-{index}")

    thirteenth = decide_admission(
        state,
        AdmissionAttempt(
            visitor="visitor-a",
            run_id="run-12",
            now=NOW + timedelta(minutes=55, seconds=10),
        ),
    )

    assert thirteenth.outcome.kind == "rate_limited"
    assert thirteenth.outcome.reason == "twelve_starts_per_hour"
    assert thirteenth.outcome.retry_at == NOW + timedelta(hours=1)
    assert thirteenth.state == state


def test_provider_allowance_signal_past_its_trust_window_fails_closed() -> None:
    state = state_with_allowance(
        AllowanceSnapshot(
            observed_at=NOW - timedelta(days=1),
            trustworthy_until=NOW - timedelta(microseconds=1),
            active_cpu_hours=0.0,
            provisioned_memory_gb_hours=0.0,
        )
    )

    transition = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
    )

    assert transition.outcome.kind == "allowance_paused"
    assert transition.outcome.reason == "provider_usage_stale"
    assert transition.state == state


def test_shared_cas_allows_only_one_stateless_instance_to_admit_a_visitor() -> None:
    store = InMemoryCasStore()
    assert store.compare_and_swap(0, state_with_allowance())
    coordinators = (
        CasCoordinator(store, clock=lambda: NOW),
        CasCoordinator(store, clock=lambda: NOW),
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda index: coordinators[index].admit(
                    AdmissionAttempt(
                        visitor="visitor-a",
                        run_id=f"run-{index}",
                        now=NOW,
                    )
                ),
                range(2),
            )
        )

    assert sorted(outcome.kind for outcome in outcomes) == ["admitted", "busy"]
    assert len(store.read()[0].running) == 1


def test_actionable_refusal_does_not_replace_last_completed_query_run() -> None:
    browser = BrowserReadModel(last_completed_run={"kind": "rows", "rows": [153]})

    updated = browser.with_attempt_outcome(
        outcome_kind="rate_limited",
        message="Three starts per minute reached.",
        retry_at=NOW + timedelta(seconds=30),
    )

    assert updated.last_completed_run == {"kind": "rows", "rows": [153]}
    assert updated.attempt_outcome == {
        "kind": "rate_limited",
        "message": "Three starts per minute reached.",
        "retry_at": "2026-07-18T18:00:30+00:00",
    }


def test_visitor_state_uses_a_one_way_digest_not_the_opaque_cookie_value() -> None:
    opaque_cookie = "random-first-party-visitor-token"

    digest = visitor_digest(opaque_cookie, digest_key=b"prototype-only-key")

    assert digest == "3279d43ae9a8c0fd195192b8673fcc470bbd963a5d697b5534c9acedb78e7ad8"
    assert opaque_cookie not in digest


def test_completion_releases_only_the_running_lease_and_keeps_rate_history() -> None:
    store = InMemoryCasStore()
    assert store.compare_and_swap(0, state_with_allowance())
    coordinator = CasCoordinator(store, clock=lambda: NOW)
    coordinator.admit(AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW))

    assert coordinator.release("run-a") is True

    state, _ = store.read()
    assert state.running == ()
    assert state.starts_for("visitor-a") == (NOW,)


def test_terminal_frame_surfaces_full_coordination_and_allowance_state() -> None:
    frame = render_frame(
        state=AdmissionState.empty(),
        last_outcome="allowance_paused: provider_usage_unavailable",
    )

    assert "running leases: 0 / 4" in frame
    assert "provider allowance: unavailable -> FAIL CLOSED" in frame
    assert "allowance_paused: provider_usage_unavailable" in frame


def test_allowance_snapshot_is_versioned_in_the_shared_cas_state() -> None:
    store = InMemoryCasStore()
    coordinator = CasCoordinator(store)

    assert coordinator.set_allowance(CURRENT_ALLOWANCE) is True

    state, version = store.read()
    assert state.allowance == CURRENT_ALLOWANCE
    assert version == 1


def test_concurrent_allowance_pause_invalidates_an_admission_cas() -> None:
    class PauseOnFirstAdmissionStore(InMemoryCasStore):
        armed = False

        def compare_and_swap(self, version: int, state: AdmissionState) -> bool:
            if self.armed:
                self.armed = False
                current, current_version = self.read()
                paused = replace(
                    current,
                    allowance=replace(CURRENT_ALLOWANCE, active_cpu_hours=2.8),
                )
                assert super().compare_and_swap(current_version, paused) is True
                return False
            return super().compare_and_swap(version, state)

    store = PauseOnFirstAdmissionStore()
    assert store.compare_and_swap(
        0,
        replace(AdmissionState.empty(), allowance=CURRENT_ALLOWANCE),
    )
    store.armed = True
    coordinator = CasCoordinator(store, clock=lambda: NOW)

    outcome = coordinator.admit(AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW))

    assert outcome.kind == "allowance_paused"
    assert outcome.reason == "active_cpu_at_safety_target"
    assert store.read()[0].running == ()


def test_retried_admission_lease_outlives_the_ten_second_run_deadline() -> None:
    class ConflictOnceStore(InMemoryCasStore):
        armed = False

        def compare_and_swap(self, version: int, state: AdmissionState) -> bool:
            if self.armed:
                self.armed = False
                current, current_version = self.read()
                assert super().compare_and_swap(current_version, current) is True
                return False
            return super().compare_and_swap(version, state)

    store = ConflictOnceStore()
    assert store.compare_and_swap(0, state_with_allowance())
    store.armed = True
    times = iter((NOW, NOW + timedelta(seconds=3)))
    coordinator = CasCoordinator(store, clock=lambda: next(times))

    assert (
        coordinator.admit(AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW)).kind
        == "admitted"
    )

    state, _ = store.read()
    assert state.running[0].expires_at == NOW + timedelta(seconds=18)
    at_deadline = decide_admission(
        state,
        AdmissionAttempt(visitor="visitor-a", run_id="run-b", now=NOW + timedelta(seconds=10)),
    )
    assert at_deadline.outcome.kind == "busy"
    assert at_deadline.outcome.retry_at == NOW + timedelta(seconds=18)


def test_malformed_provider_allowance_values_fail_closed() -> None:
    invalid_snapshots = (
        replace(CURRENT_ALLOWANCE, active_cpu_hours=float("nan")),
        replace(CURRENT_ALLOWANCE, provisioned_memory_gb_hours=-1.0),
        replace(CURRENT_ALLOWANCE, observed_at=NOW + timedelta(seconds=1)),
        replace(CURRENT_ALLOWANCE, trustworthy_until=NOW - timedelta(seconds=1)),
        replace(CURRENT_ALLOWANCE, observed_at=cast(datetime, "not-a-time")),
        replace(CURRENT_ALLOWANCE, trustworthy_until=cast(datetime, None)),
        replace(CURRENT_ALLOWANCE, observed_at=datetime(2026, 7, 18, 18, 0)),
    )

    for allowance in invalid_snapshots:
        transition = decide_admission(
            state_with_allowance(allowance),
            AdmissionAttempt(visitor="visitor-a", run_id="run-a", now=NOW),
        )
        assert transition.outcome.kind == "allowance_paused"
        assert transition.outcome.reason == "provider_usage_invalid"
