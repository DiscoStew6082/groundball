"""Guarded live proof of the real Vercel Blob admission Adapter.

The CLI creates only unique ``proof`` namespace objects. It never provisions a
store, changes provider settings, touches production state, or deletes objects.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Mapping
from uuid import uuid4

from baseball_rag.protected_provider_proof import (
    EVIDENCE_SCHEMAS,
    ProviderProofError,
    validate_provider_evidence,
    validate_provider_identity,
)
from baseball_rag.public_admission import (
    AdmissionAttempt,
    AdmissionState,
    CasCoordinator,
    MonthlyBudget,
    RunLease,
)
from baseball_rag.public_admission_blob import (
    BlobCoordinationConfig,
    BlobCoordinationStore,
    BlobCredentialProvider,
    BlobProviderError,
    HttpResponse,
    HttpTransport,
    OidcBlobCredentialProvider,
    OperationCounts,
    RequestsHttpTransport,
    StaticBlobCredentialProvider,
    _opaque_etag,
    blob_upload_url,
    load_blob_public_admission,
    new_blob_request_id,
)
from baseball_rag.public_admission_state import (
    MAX_RUNNING_LEASES,
    MAX_STATE_BYTES,
    decode_admission_state,
    encode_admission_state,
)
from baseball_rag.public_release_config import canonical_json_bytes

_REQUIRED_CHECKS = (
    "bounded_contention",
    "conflict",
    "create_if_absent",
    "current_partial_month_initialization",
    "etag_conditional_write",
    "expired_lease",
    "fifth_deployment_busy",
    "future_state_fail_closed",
    "hour_limit",
    "malformed_state_fail_closed",
    "minute_limit",
    "nonrefund_after_interruption",
    "older_period_utc_rollover",
    "private_uncached_read",
    "rejected_attempts_uncharged",
    "same_visitor_busy",
    "state_codec",
    "unavailable_store",
    "unused_rollover_forbidden",
    "hundredth_admit_101st_refusal",
)


class BlobProbeError(ValueError):
    """The isolated live Blob exercise is unsafe, incomplete, or failed."""


@dataclass
class MeteredTransport:
    delegate: HttpTransport
    request_bytes: int = 0
    response_bytes: int = 0

    def request(self, **kwargs: object) -> HttpResponse:
        data = kwargs.get("data")
        if isinstance(data, bytes):
            self.request_bytes += len(data)
        response = self.delegate.request(**kwargs)  # type: ignore[arg-type]
        self.response_bytes += len(response.body)
        return response


class _UnavailableTransport:
    def request(self, **kwargs: object) -> HttpResponse:
        del kwargs
        raise BlobProviderError


_CONFLICT_MARKER_VISITOR = "f" * 64
_CONFLICT_MARKER_RUN_PREFIX = "blob-proof-contention-"
_CONFLICT_MARKER_DEADLINE = datetime(1970, 1, 1, tzinfo=UTC)


class _RealConflictTransport:
    """Cause a real ETag change immediately before each tested conditional PUT."""

    def __init__(
        self,
        delegate: HttpTransport,
        config: BlobCoordinationConfig,
        *,
        marker_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._delegate = delegate
        self._config = config
        self._marker_id_factory = marker_id_factory or (
            lambda: f"{_CONFLICT_MARKER_RUN_PREFIX}{uuid4().hex}"
        )

    def request(self, **kwargs: object) -> HttpResponse:
        method = kwargs.get("method")
        headers = kwargs.get("headers")
        if method != "PUT" or not isinstance(headers, dict) or "x-if-match" not in headers:
            return self._delegate.request(**kwargs)  # type: ignore[arg-type]
        try:
            current = self._delegate.request(
                method="GET",
                url=f"{self._config.state_url}?cache=0",
                headers={
                    "accept": "application/json",
                    "authorization": headers["authorization"],
                },
                data=None,
                timeout=5.0,
                max_response_bytes=MAX_STATE_BYTES,
            )
            if current.status_code != 200:
                raise BlobProviderError
            etag = _opaque_etag(current.headers)
            competing_body = _competing_state_body(current.body, self._marker_id_factory())
            if competing_body == current.body:
                raise BlobProviderError
            competing_headers = dict(headers)
            competing_headers["x-if-match"] = etag
            competing_headers["x-api-blob-request-id"] = new_blob_request_id(self._config.store_id)
            timeout = kwargs.get("timeout")
            max_response_bytes = kwargs.get("max_response_bytes")
            if (
                isinstance(timeout, bool)
                or not isinstance(timeout, (int, float))
                or type(max_response_bytes) is not int
            ):
                raise BlobProviderError
            competing = self._delegate.request(
                method="PUT",
                url=str(kwargs["url"]),
                headers=competing_headers,
                data=competing_body,
                timeout=float(timeout),
                max_response_bytes=max_response_bytes,
            )
            if competing.status_code not in {200, 201}:
                raise BlobProviderError
            reread = self._delegate.request(
                method="GET",
                url=f"{self._config.state_url}?cache=0",
                headers={
                    "accept": "application/json",
                    "authorization": headers["authorization"],
                },
                data=None,
                timeout=5.0,
                max_response_bytes=MAX_STATE_BYTES,
            )
            if reread.status_code != 200 or reread.body != competing_body:
                raise BlobProviderError
            competing_etag = _opaque_etag(reread.headers)
            if competing_etag == etag:
                raise BlobProviderError
            original = self._delegate.request(**kwargs)  # type: ignore[arg-type]
            if original.status_code != 412:
                raise BlobProviderError
            return original
        except BlobProviderError:
            raise
        except Exception:
            raise BlobProviderError from None


def _competing_state_body(current_body: bytes, marker_run_id: str) -> bytes:
    if not _is_conflict_marker_run_id(marker_run_id):
        raise BlobProviderError
    state = decode_admission_state(current_body)
    if any(visitor == _CONFLICT_MARKER_VISITOR for visitor, _ in state.starts_by_visitor):
        raise BlobProviderError
    retained: list[RunLease] = []
    for lease in state.running:
        owned_marker = (
            lease.visitor == _CONFLICT_MARKER_VISITOR
            and _is_conflict_marker_run_id(lease.run_id)
            and lease.expires_at == _CONFLICT_MARKER_DEADLINE
        )
        if owned_marker:
            continue
        if lease.visitor == _CONFLICT_MARKER_VISITOR or lease.run_id.startswith(
            _CONFLICT_MARKER_RUN_PREFIX
        ):
            raise BlobProviderError
        retained.append(lease)
    if len(retained) >= MAX_RUNNING_LEASES or any(
        lease.run_id == marker_run_id for lease in retained
    ):
        raise BlobProviderError
    competing = AdmissionState(
        running=(
            *retained,
            RunLease(
                visitor=_CONFLICT_MARKER_VISITOR,
                run_id=marker_run_id,
                expires_at=_CONFLICT_MARKER_DEADLINE,
            ),
        ),
        starts_by_visitor=state.starts_by_visitor,
        monthly_budget=state.monthly_budget,
    )
    return encode_admission_state(competing)


def _is_conflict_marker_run_id(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith(_CONFLICT_MARKER_RUN_PREFIX):
        return False
    suffix = value.removeprefix(_CONFLICT_MARKER_RUN_PREFIX)
    return len(suffix) == 32 and all(character in "0123456789abcdef" for character in suffix)


def run_live_blob_probe(
    identity: Mapping[str, object],
    environment: Mapping[str, str],
    proof_id: str,
    *,
    transport: HttpTransport,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Exercise isolated real Adapter semantics without reset/delete operations."""
    validate_provider_identity(identity)
    if (
        not proof_id
        or len(proof_id) > 40
        or proof_id != proof_id.lower()
        or not proof_id.replace("-", "a").isalnum()
        or proof_id.startswith("-")
        or proof_id.endswith("-")
    ):
        raise BlobProbeError("Blob proof identifier is invalid.")
    if environment.get("GROUNDBALL_BLOB_NAMESPACE") != "proof":
        raise BlobProbeError("Live Blob proof is restricted to the proof namespace.")
    if environment.get("GROUNDBALL_BLOB_PROOF_ID") not in {None, proof_id}:
        raise BlobProbeError("Blob proof namespace is ambiguous.")
    meter = MeteredTransport(transport)
    stores: list[BlobCoordinationStore] = []

    def store(
        suffix: str, *, selected_transport: HttpTransport | None = None
    ) -> BlobCoordinationStore:
        child_id = f"{proof_id}-{suffix}"
        child_environment = {
            **environment,
            "GROUNDBALL_BLOB_NAMESPACE": "proof",
            "GROUNDBALL_BLOB_PROOF_ID": child_id,
        }
        configured = load_blob_public_admission(
            child_environment,
            transport=selected_transport or meter,
        )
        stores.append(configured.store)
        return configured.store

    checks = {name: False for name in _REQUIRED_CHECKS}

    base = store("base")
    missing = base.read()
    checks["private_uncached_read"] = missing.exists is False and missing.observed_at is not None
    now = _require_provider_time(missing.observed_at)
    period = now.strftime("%Y-%m")
    initialized = CasCoordinator(base).initialize_current_budget()
    checks["create_if_absent"] = initialized
    checks["current_partial_month_initialization"] = (
        base.read().state.monthly_budget == MonthlyBudget(period, 0)
    )
    checks["state_codec"] = encode_admission_state(base.read().state).startswith(
        b'{"monthly_budget"'
    )
    first = base.read()
    stale = base.read()
    changed = AdmissionState(monthly_budget=MonthlyBudget(period, 1))
    checks["etag_conditional_write"] = base.compare_and_swap(first.version, changed)
    checks["conflict"] = base.compare_and_swap(stale.version, changed) is False

    same = store("same-visitor")
    _seed_missing(same, AdmissionState(monthly_budget=MonthlyBudget(period, 0)))
    same_coordinator = CasCoordinator(same)
    visitor = "1" * 64
    first_same = same_coordinator.admit(AdmissionAttempt(visitor, "same-1", now))
    second_same = same_coordinator.admit(AdmissionAttempt(visitor, "same-2", now))
    same_state = same.read().state
    checks["same_visitor_busy"] = first_same.kind == "admitted" and second_same.kind == "busy"
    checks["rejected_attempts_uncharged"] = same_state.monthly_budget == MonthlyBudget(period, 1)

    deployment = store("deployment-busy")
    _seed_missing(deployment, AdmissionState(monthly_budget=MonthlyBudget(period, 0)))
    deployment_coordinator = CasCoordinator(deployment)
    deployment_outcomes = [
        deployment_coordinator.admit(AdmissionAttempt(f"{index:064x}", f"deployment-{index}", now))
        for index in range(1, 6)
    ]
    checks["fifth_deployment_busy"] = [item.kind for item in deployment_outcomes[:4]] == [
        "admitted"
    ] * 4 and deployment_outcomes[4].kind == "busy"

    minute = store("minute-limit")
    _seed_missing(minute, AdmissionState(monthly_budget=MonthlyBudget(period, 0)))
    minute_coordinator = CasCoordinator(minute)
    minute_outcomes = []
    for index in range(1, 5):
        outcome = minute_coordinator.admit(AdmissionAttempt(visitor, f"minute-{index}", now))
        minute_outcomes.append(outcome)
        if outcome.kind == "admitted":
            minute_coordinator.release(f"minute-{index}")
    checks["minute_limit"] = [item.kind for item in minute_outcomes] == [
        "admitted",
        "admitted",
        "admitted",
        "rate_limited",
    ]

    hour = store("hour-limit")
    hour_starts = tuple(now - timedelta(minutes=55 - index * 5) for index in range(12))
    _seed_missing(
        hour,
        AdmissionState(
            starts_by_visitor=((visitor, hour_starts),),
            monthly_budget=MonthlyBudget(period, 12),
        ),
    )
    hour_outcome = CasCoordinator(hour).admit(AdmissionAttempt(visitor, "hour-13", now))
    checks["hour_limit"] = (
        hour_outcome.kind == "rate_limited" and hour_outcome.reason == "twelve_starts_per_hour"
    )

    monthly = store("monthly-limit")
    _seed_missing(monthly, AdmissionState(monthly_budget=MonthlyBudget(period, 99)))
    monthly_coordinator = CasCoordinator(monthly)
    hundredth = monthly_coordinator.admit(AdmissionAttempt("2" * 64, "monthly-100", now))
    monthly_coordinator.release("monthly-100")
    hundred_first = monthly_coordinator.admit(AdmissionAttempt("3" * 64, "monthly-101", now))
    charged_after_release = monthly.read().state.monthly_budget
    checks["hundredth_admit_101st_refusal"] = (
        hundredth.kind == "admitted" and hundred_first.kind == "allowance_paused"
    )
    checks["nonrefund_after_interruption"] = charged_after_release == MonthlyBudget(period, 100)

    older = store("older-rollover")
    older_period = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    _seed_missing(older, AdmissionState(monthly_budget=MonthlyBudget(older_period, 87)))
    rollover = CasCoordinator(older).admit(AdmissionAttempt("4" * 64, "rollover-1", now))
    rollover_budget = older.read().state.monthly_budget
    checks["older_period_utc_rollover"] = (
        rollover.kind == "admitted" and rollover_budget == MonthlyBudget(period, 1)
    )
    checks["unused_rollover_forbidden"] = rollover_budget != MonthlyBudget(period, 88)

    expired = store("expired-lease")
    _seed_missing(
        expired,
        AdmissionState(
            running=(RunLease(visitor, "expired", now - timedelta(seconds=1)),),
            starts_by_visitor=((visitor, (now - timedelta(minutes=2),)),),
            monthly_budget=MonthlyBudget(period, 1),
        ),
    )
    expired_outcome = CasCoordinator(expired).admit(AdmissionAttempt(visitor, "after-expiry", now))
    checks["expired_lease"] = expired_outcome.kind == "admitted"

    future = store("future-state")
    next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m")
    _seed_missing(future, AdmissionState(monthly_budget=MonthlyBudget(next_month, 0)))
    checks["future_state_fail_closed"] = (
        CasCoordinator(future).readiness().kind == "allowance_paused"
    )

    malformed = store("malformed-state")
    _write_raw_missing(malformed, meter, environment, f"{proof_id}-malformed-state", b"{")
    checks["malformed_state_fail_closed"] = (
        CasCoordinator(malformed).readiness().kind == "allowance_paused"
    )

    contradictory = store("contradictory-state")
    contradictory_body = (
        b'{"monthly_budget":{"charged_starts":0,"period":"'
        + period.encode("ascii")
        + b'"},"running":[],"schema_version":1,"starts_by_visitor":'
        + b'[{"starts":["'
        + now.strftime("%Y-%m-%dT%H:%M:%SZ").encode("ascii")
        + b'"],"visitor":"'
        + visitor.encode("ascii")
        + b'"}]}'
    )
    _write_raw_missing(
        contradictory,
        meter,
        environment,
        f"{proof_id}-contradictory-state",
        contradictory_body,
    )
    contradictory_outcome = CasCoordinator(contradictory).readiness()
    checks["malformed_state_fail_closed"] = (
        checks["malformed_state_fail_closed"] and contradictory_outcome.kind == "allowance_paused"
    )

    unavailable = store("unavailable", selected_transport=_UnavailableTransport())
    checks["unavailable_store"] = (
        CasCoordinator(unavailable).readiness().kind == "provider_unavailable"
    )

    contention_config, contention_credentials = _proof_config(environment, f"{proof_id}-contention")
    contention_base = BlobCoordinationStore(
        contention_config,
        credential_provider=contention_credentials,
        transport=meter,
    )
    stores.append(contention_base)
    _seed_missing(contention_base, AdmissionState(monthly_budget=MonthlyBudget(period, 0)))
    conflict_transport = _RealConflictTransport(meter, contention_config)
    contention = BlobCoordinationStore(
        contention_config,
        credential_provider=contention_credentials,
        transport=conflict_transport,
    )
    stores.append(contention)
    contention_outcome = CasCoordinator(contention).admit(
        AdmissionAttempt("5" * 64, "bounded-contention", now)
    )
    checks["bounded_contention"] = (
        contention_outcome.kind == "provider_unavailable"
        and contention_outcome.reason == "coordination_contention"
    )

    counts = _sum_counts(stores)
    timestamp = observed_at or now
    document: dict[str, object] = {
        "identity": dict(identity),
        "observation": {
            "application_operation_counts": counts,
            "checks": checks,
            "namespace": "proof",
            "provider_accounting_observation_id": None,
            "request_bytes": meter.request_bytes,
            "response_bytes": meter.response_bytes,
        },
        "observed_at": timestamp.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": EVIDENCE_SCHEMAS["blob_admission"],
        "status": "pass" if all(checks.values()) else "fail",
    }
    validate_provider_evidence(document)
    return document


def _seed_missing(store: BlobCoordinationStore, state: AdmissionState) -> None:
    snapshot = store.read()
    if snapshot.exists or not store.compare_and_swap(snapshot.version, state):
        raise BlobProbeError("Unique Blob proof namespace is not empty.")


def _write_raw_missing(
    store: BlobCoordinationStore,
    transport: HttpTransport,
    environment: Mapping[str, str],
    proof_id: str,
    body: bytes,
) -> None:
    snapshot = store.read()
    if snapshot.exists:
        raise BlobProbeError("Unique malformed-state namespace is not empty.")
    config, credential_provider = _proof_config(environment, proof_id)
    credential = credential_provider.resolve()
    response = transport.request(
        method="PUT",
        url=blob_upload_url(config.object_key),
        headers={
            "authorization": f"Bearer {credential}",
            "content-type": "application/json",
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "0",
            "x-api-blob-request-attempt": "0",
            "x-api-blob-request-id": new_blob_request_id(config.store_id),
            "x-api-version": "12",
            "x-content-type": "application/json",
            "x-vercel-blob-access": "private",
            "x-vercel-blob-store-id": config.store_id,
        },
        data=body,
        timeout=5.0,
        max_response_bytes=4096,
    )
    if response.status_code not in {200, 201}:
        raise BlobProbeError("Raw isolated proof-state write failed.")


def _proof_config(
    environment: Mapping[str, str], proof_id: str
) -> tuple[BlobCoordinationConfig, BlobCredentialProvider]:
    static = {
        key for key in ("GROUNDBALL_BLOB_STORE_ID", "GROUNDBALL_BLOB_TOKEN") if key in environment
    }
    oidc = {key for key in ("BLOB_STORE_ID", "VERCEL_OIDC_TOKEN") if key in environment}
    if "BLOB_READ_WRITE_TOKEN" in environment:
        raise BlobProbeError("Blob proof authentication is missing or ambiguous.")
    if static == {"GROUNDBALL_BLOB_STORE_ID", "GROUNDBALL_BLOB_TOKEN"} and not oidc:
        store_id = environment["GROUNDBALL_BLOB_STORE_ID"]
        credential_provider: BlobCredentialProvider = StaticBlobCredentialProvider(
            environment["GROUNDBALL_BLOB_TOKEN"]
        )
    elif oidc == {"BLOB_STORE_ID", "VERCEL_OIDC_TOKEN"} and not static:
        store_id = environment["BLOB_STORE_ID"]
        credential_provider = OidcBlobCredentialProvider(
            startup_token=environment["VERCEL_OIDC_TOKEN"]
        )
    else:
        raise BlobProbeError("Blob proof authentication is missing or ambiguous.")
    return (
        BlobCoordinationConfig.proof(store_id=store_id, proof_id=proof_id),
        credential_provider,
    )


def _require_provider_time(value: datetime | None) -> datetime:
    if value is None or value.tzinfo is None:
        raise BlobProbeError("Blob proof lacks trusted provider Date.")
    return value.astimezone(UTC)


def _sum_counts(stores: list[BlobCoordinationStore]) -> dict[str, int]:
    totals = {key: 0 for key in OperationCounts().as_dict()}
    for selected in stores:
        for key, value in selected.operation_counts().as_dict().items():
            totals[key] += value
    return totals


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--proof-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--artifact-commit", required=True)
    parser.add_argument("--bundle-digest", required=True)
    parser.add_argument("--runtime-configuration-digest", required=True)
    parser.add_argument("--admission-policy-digest", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--provider-image-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.live:
        parser.error("Provider contact requires the explicit --live guard.")
    identity = {
        "admission_policy_digest": args.admission_policy_digest,
        "artifact_commit": args.artifact_commit,
        "bundle_digest": args.bundle_digest,
        "deployment_id": args.deployment_id,
        "provider_image_digest": args.provider_image_digest,
        "runtime_configuration_digest": args.runtime_configuration_digest,
        "source_commit": args.source_commit,
    }
    try:
        document = run_live_blob_probe(
            identity,
            os.environ,
            args.proof_id,
            transport=RequestsHttpTransport(),
        )
    except (BlobProbeError, ProviderProofError, ValueError) as exc:
        parser.error(str(exc))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(canonical_json_bytes(document))
    return 0 if document.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
