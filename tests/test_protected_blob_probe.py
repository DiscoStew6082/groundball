from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import UTC, datetime

import pytest

import baseball_rag.protected_blob_probe as protected_blob_probe
from baseball_rag.protected_blob_probe import (
    _CONFLICT_MARKER_DEADLINE,
    _CONFLICT_MARKER_RUN_PREFIX,
    _CONFLICT_MARKER_VISITOR,
    BlobProbeError,
    _RealConflictTransport,
    _write_raw_missing,
    main,
    run_live_blob_probe,
)
from baseball_rag.protected_provider_proof import ProviderProofError
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
    BlobProviderError,
    HttpResponse,
    StaticBlobCredentialProvider,
    blob_upload_url,
    load_blob_public_admission,
)
from baseball_rag.public_admission_state import decode_admission_state, encode_admission_state
from baseball_rag.public_release_config import MAXIMUM_CAS_ATTEMPTS, canonical_json_bytes

DEPLOYMENT = "dpl_9XW9KmE2rqe4XWZ7YBbmetEQLgab"


def _identity() -> dict[str, object]:
    return {
        "admission_policy_digest": "1" * 64,
        "artifact_commit": "2" * 40,
        "bundle_digest": "3" * 64,
        "deployment_id": DEPLOYMENT,
        "provider_image_digest": "sha256:" + "4" * 64,
        "runtime_configuration_digest": "5" * 64,
        "source_commit": "6" * 40,
    }


class ContentAddressedEtagTransport:
    """A Blob-like CAS transport where ETags identify body bytes."""

    def __init__(
        self,
        config: BlobCoordinationConfig,
        body: bytes,
        *,
        competing_status: int | None = None,
        competing_success_status: int = 200,
        missing_get_etag: bool = False,
        reread_status: int = 200,
        missing_reread_etag: bool = False,
        reread_etag: str | None = None,
        reread_body: bytes | None = None,
        fail_reread: bool = False,
        preserve_changed_body_etag: bool = False,
        accept_stale_original: bool = False,
        expose_put_etag: bool = False,
        weak_read_etags: bool = False,
    ) -> None:
        self.config = config
        self.body = body
        self.etag = self._etag(body)
        self.competing_status = competing_status
        self.competing_success_status = competing_success_status
        self.missing_get_etag = missing_get_etag
        self.reread_status = reread_status
        self.missing_reread_etag = missing_reread_etag
        self.reread_etag = reread_etag
        self.reread_body = reread_body
        self.fail_reread = fail_reread
        self.preserve_changed_body_etag = preserve_changed_body_etag
        self.accept_stale_original = accept_stale_original
        self.expose_put_etag = expose_put_etag
        self.weak_read_etags = weak_read_etags
        self.get_attempts: list[dict[str, object]] = []
        self.put_attempts: list[bytes] = []
        self.put_bodies: list[bytes] = []

    @staticmethod
    def _etag(body: bytes) -> str:
        return f'"{hashlib.sha256(body).hexdigest()}"'

    def request(self, **kwargs: object) -> HttpResponse:
        method = kwargs["method"]
        headers = kwargs["headers"]
        assert isinstance(headers, dict)
        if method == "GET":
            self.get_attempts.append(dict(kwargs))
            reread = len(self.get_attempts) > 1
            if reread and self.fail_reread:
                raise OSError("synthetic private read failure")
            response_headers = {
                "content-type": "application/json",
                "date": "Sun, 19 Jul 2026 12:00:00 GMT",
            }
            missing_etag = self.missing_reread_etag if reread else self.missing_get_etag
            if not missing_etag:
                response_etag = (
                    self.reread_etag if reread and self.reread_etag is not None else self.etag
                )
                response_headers["etag"] = (
                    f"W/{response_etag}" if self.weak_read_etags else response_etag
                )
            status = self.reread_status if reread else 200
            body = self.reread_body if reread and self.reread_body is not None else self.body
            return HttpResponse(status, response_headers, body)
        assert method == "PUT"
        assert kwargs["url"] == blob_upload_url(self.config.object_key)
        body = kwargs["data"]
        assert isinstance(body, bytes)
        self.put_attempts.append(body)
        if headers.get("x-if-match") != self.etag and not self.accept_stale_original:
            return HttpResponse(412, {}, b"")
        if self.competing_status is not None and not self.put_bodies:
            return HttpResponse(self.competing_status, {}, b"")
        previous_etag = self.etag
        self.put_bodies.append(body)
        self.body = body
        if not self.preserve_changed_body_etag:
            self.etag = self._etag(body)
        response_headers = {"etag": self.etag} if self.expose_put_etag else {}
        assert self.etag == previous_etag or self.etag == self._etag(body)
        return HttpResponse(
            self.competing_success_status,
            response_headers,
            json.dumps(
                {"pathname": self.config.object_key, "url": self.config.state_url},
                separators=(",", ":"),
            ).encode(),
        )


class NoNetworkTransport:
    def __init__(self) -> None:
        self.calls = 0

    def request(self, **kwargs: object):
        self.calls += 1
        raise AssertionError(f"offline test attempted provider contact: {sorted(kwargs)}")


@pytest.mark.parametrize("competing_status", [200, 201])
def test_real_conflict_transport_normalizes_weak_read_etag_before_original_put(
    competing_status: int,
) -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    current = encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0)))
    backend = ContentAddressedEtagTransport(
        config,
        current,
        competing_success_status=competing_status,
        weak_read_etags=True,
    )
    transport = _RealConflictTransport(backend, config)
    original_etag = backend.etag

    response = transport.request(
        method="PUT",
        url=blob_upload_url(config.object_key),
        headers={"authorization": "Bearer proof", "x-if-match": original_etag},
        data=encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 1))),
        timeout=5.0,
        max_response_bytes=4096,
    )

    assert response.status_code == 412
    assert backend.etag != original_etag
    assert backend.put_bodies[0] != current
    assert len(backend.get_attempts) == 2
    reread = backend.get_attempts[1]
    assert reread == {
        "method": "GET",
        "url": f"{config.state_url}?cache=0",
        "headers": {
            "accept": "application/json",
            "authorization": "Bearer proof",
        },
        "data": None,
        "timeout": 5.0,
        "max_response_bytes": protected_blob_probe.MAX_STATE_BYTES,
    }


def test_real_contention_replaces_expired_markers_until_coordinator_exhausts_retries() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    history = (("1" * 64, (datetime(2026, 7, 19, 11, 0, tzinfo=UTC),)),)
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(
            AdmissionState(
                starts_by_visitor=history,
                monthly_budget=MonthlyBudget("2026-07", 1),
            )
        ),
    )
    marker_ids = iter(
        f"{_CONFLICT_MARKER_RUN_PREFIX}{index:032x}" for index in range(MAXIMUM_CAS_ATTEMPTS)
    )
    conflict_transport = _RealConflictTransport(
        backend,
        config,
        marker_id_factory=lambda: next(marker_ids),
    )
    store = BlobCoordinationStore(
        config,
        credential_provider=StaticBlobCredentialProvider("proof-token"),
        transport=conflict_transport,
    )

    outcome = CasCoordinator(store).admit(
        AdmissionAttempt("5" * 64, "bounded-contention", datetime(2026, 7, 19, 12, tzinfo=UTC))
    )

    assert (outcome.kind, outcome.reason) == (
        "provider_unavailable",
        "coordination_contention",
    )
    counts = store.operation_counts()
    assert counts.attempted_conditional_writes == MAXIMUM_CAS_ATTEMPTS
    assert counts.conditional_conflicts == MAXIMUM_CAS_ATTEMPTS
    assert counts.failed_conditional_writes == 0
    assert len(backend.put_bodies) == MAXIMUM_CAS_ATTEMPTS
    assert len(backend.get_attempts) == MAXIMUM_CAS_ATTEMPTS * 3
    observed_marker_ids = []
    for body in backend.put_bodies:
        state = decode_admission_state(body)
        assert state.monthly_budget == MonthlyBudget("2026-07", 1)
        assert state.starts_by_visitor == history
        assert len(state.running) == 1
        marker = state.running[0]
        assert marker.visitor == _CONFLICT_MARKER_VISITOR
        assert marker.expires_at == _CONFLICT_MARKER_DEADLINE
        observed_marker_ids.append(marker.run_id)
    assert len(set(observed_marker_ids)) == MAXIMUM_CAS_ATTEMPTS


def _conditional_request(
    transport: _RealConflictTransport,
    config: BlobCoordinationConfig,
    etag: str,
) -> HttpResponse:
    return transport.request(
        method="PUT",
        url=blob_upload_url(config.object_key),
        headers={"authorization": "Bearer proof", "x-if-match": etag},
        data=encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 1))),
        timeout=5.0,
        max_response_bytes=4096,
    )


def test_real_conflict_transport_rejects_malformed_current_state() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(config, b"{")

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_rejects_full_running_cardinality() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    leases = tuple(
        RunLease(
            visitor=f"{index:064x}",
            run_id=f"running-{index}",
            expires_at=datetime(2026, 7, 19, 12, 1, tzinfo=UTC),
        )
        for index in range(1, 5)
    )
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(
            AdmissionState(running=leases, monthly_budget=MonthlyBudget("2026-07", 0))
        ),
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


@pytest.mark.parametrize(
    "lease",
    [
        RunLease(
            _CONFLICT_MARKER_VISITOR,
            "foreign-run",
            _CONFLICT_MARKER_DEADLINE,
        ),
        RunLease(
            "e" * 64,
            f"{_CONFLICT_MARKER_RUN_PREFIX}foreign",
            _CONFLICT_MARKER_DEADLINE,
        ),
    ],
    ids=("reserved-visitor", "reserved-run"),
)
def test_real_conflict_transport_rejects_reserved_marker_collisions(lease: RunLease) -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(
            AdmissionState(running=(lease,), monthly_budget=MonthlyBudget("2026-07", 0))
        ),
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_rejects_reserved_visitor_history_collision() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(
            AdmissionState(
                starts_by_visitor=(
                    (
                        _CONFLICT_MARKER_VISITOR,
                        (datetime(2026, 7, 19, 11, tzinfo=UTC),),
                    ),
                ),
                monthly_budget=MonthlyBudget("2026-07", 1),
            )
        ),
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_rejects_noncanonical_marker_id() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
    )
    transport = _RealConflictTransport(
        backend,
        config,
        marker_id_factory=lambda: "foreign-run",
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(transport, config, backend.etag)


def test_real_conflict_transport_rejects_unchanged_competing_body() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    run_id = f"{_CONFLICT_MARKER_RUN_PREFIX}{'0' * 32}"
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(
            AdmissionState(
                running=(
                    RunLease(
                        _CONFLICT_MARKER_VISITOR,
                        run_id,
                        _CONFLICT_MARKER_DEADLINE,
                    ),
                ),
                monthly_budget=MonthlyBudget("2026-07", 0),
            )
        ),
    )
    transport = _RealConflictTransport(backend, config, marker_id_factory=lambda: run_id)

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(transport, config, backend.etag)
    assert backend.put_attempts == []


@pytest.mark.parametrize("missing_at", ["initial-read", "reread"])
def test_real_conflict_transport_rejects_missing_read_etag(missing_at: str) -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        missing_get_etag=missing_at == "initial-read",
        missing_reread_etag=missing_at == "reread",
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


@pytest.mark.parametrize("etag", ["", " changed", "changed ", "bad\x7fvalue", "x" * 1025])
def test_real_conflict_transport_rejects_malformed_reread_etag(etag: str) -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        reread_etag=etag,
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_rejects_unchanged_competing_etag() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        preserve_changed_body_etag=True,
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_rejects_reread_non_200() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        reread_status=503,
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_rejects_reread_body_mismatch() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        reread_body=b'{"different":"state"}',
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_sanitizes_reread_transport_failure() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        fail_reread=True,
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed") as raised:
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)
    assert raised.value.__cause__ is None
    assert "synthetic" not in str(raised.value)


def test_real_conflict_transport_rejects_competing_non_2xx() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        competing_status=503,
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_real_conflict_transport_rejects_unexpected_original_success() -> None:
    config = BlobCoordinationConfig.proof(store_id="ProofStore123", proof_id="contention")
    backend = ContentAddressedEtagTransport(
        config,
        encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))),
        accept_stale_original=True,
    )

    with pytest.raises(BlobProviderError, match="Blob coordination request failed"):
        _conditional_request(_RealConflictTransport(backend, config), config, backend.etag)


def test_blob_probe_accepts_exact_mixed_case_identity_and_rejects_mutation_before_transport() -> (
    None
):
    environment = {
        "BLOB_STORE_ID": "store_ProofStore123",
        "GROUNDBALL_BLOB_NAMESPACE": "proof",
        "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
        "VERCEL_OIDC_TOKEN": ("eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJwcm9iZSJ9.probe-signature"),
    }
    accepted_transport = NoNetworkTransport()
    with pytest.raises(AssertionError, match="provider contact"):
        run_live_blob_probe(_identity(), environment, "wave-7", transport=accepted_transport)
    assert accepted_transport.calls == 1

    mutated = _identity()
    mutated["deployment_id"] = DEPLOYMENT + "/"
    rejected_transport = NoNetworkTransport()
    with pytest.raises(ProviderProofError, match="identity is invalid"):
        run_live_blob_probe(mutated, environment, "wave-7", transport=rejected_transport)
    assert rejected_transport.calls == 0


def test_blob_probe_rejects_production_or_ambiguous_namespace_before_transport() -> None:
    common = {
        "BLOB_STORE_ID": "store_ProofStore123",
        "VERCEL_OIDC_TOKEN": "synthetic-oidc",
        "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
    }
    with pytest.raises(BlobProbeError, match="proof namespace"):
        run_live_blob_probe(
            _identity(),
            {**common, "GROUNDBALL_BLOB_NAMESPACE": "production"},
            "wave-7",
            transport=NoNetworkTransport(),
        )
    with pytest.raises(BlobProbeError, match="ambiguous"):
        run_live_blob_probe(
            _identity(),
            {
                **common,
                "GROUNDBALL_BLOB_NAMESPACE": "proof",
                "GROUNDBALL_BLOB_PROOF_ID": "different-proof",
            },
            "wave-7",
            transport=NoNetworkTransport(),
        )


def test_protected_raw_probe_injection_uses_the_pinned_v12_query_contract() -> None:
    token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJwcm9iZSJ9.probe-signature"
    environment = {
        "BLOB_STORE_ID": "store_ProofStore123",
        "GROUNDBALL_BLOB_NAMESPACE": "proof",
        "GROUNDBALL_BLOB_PROOF_ID": "wave-7-malformed",
        "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
        "VERCEL_OIDC_TOKEN": token,
    }

    class RecordingTransport:
        def __init__(self) -> None:
            self.requests: list[dict[str, object]] = []

        def request(self, **kwargs: object) -> HttpResponse:
            self.requests.append(kwargs)
            if kwargs["method"] == "GET":
                return HttpResponse(404, {"date": "Sun, 19 Jul 2026 12:00:00 GMT"}, b"")
            return HttpResponse(201, {}, b"{}")

    transport = RecordingTransport()
    configured = load_blob_public_admission(environment, transport=transport)

    _write_raw_missing(
        configured.store,
        transport,
        environment,
        "wave-7-malformed",
        b"{",
    )

    request = transport.requests[1]
    assert request["url"] == (
        "https://vercel.com/api/blob/?pathname=groundball%2Fpublic-admission%2Fv1%2Fproof%2F"
        "wave-7-malformed%2Fstate.json"
    )
    headers = request["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == f"Bearer {token}"
    assert headers["x-api-version"] == "12"
    assert headers["x-vercel-blob-store-id"] == "ProofStore123"
    assert headers["x-vercel-blob-access"] == "private"
    assert headers["x-allow-overwrite"] == "0"
    assert "x-if-match" not in headers
    assert re.fullmatch(
        r"ProofStore123:\d{13}:[0-9a-f]{32}",
        str(headers["x-api-blob-request-id"]),
    )


def _cli_args(output: str) -> list[str]:
    return [
        "--live",
        "--proof-id",
        "wave-7",
        "--source-commit",
        "6" * 40,
        "--artifact-commit",
        "2" * 40,
        "--bundle-digest",
        "3" * 64,
        "--runtime-configuration-digest",
        "5" * 64,
        "--admission-policy-digest",
        "1" * 64,
        "--deployment-id",
        DEPLOYMENT,
        "--provider-image-digest",
        "sha256:" + "4" * 64,
        "--output",
        output,
    ]


def test_blob_cli_writes_failure_evidence_and_returns_one(monkeypatch, tmp_path) -> None:
    output = tmp_path / "blob.json"
    document = {"observation": {"checks": {"bounded_contention": False}}, "status": "fail"}
    monkeypatch.setattr(
        protected_blob_probe,
        "run_live_blob_probe",
        lambda *args, **kwargs: document,
    )

    exit_status = main(_cli_args(str(output)))

    assert exit_status == 1
    assert output.read_bytes() == canonical_json_bytes(document)


def test_blob_cli_writes_passing_evidence_and_returns_zero(monkeypatch, tmp_path) -> None:
    output = tmp_path / "blob.json"
    document = {"observation": {"checks": {"bounded_contention": True}}, "status": "pass"}
    monkeypatch.setattr(
        protected_blob_probe,
        "run_live_blob_probe",
        lambda *args, **kwargs: document,
    )

    exit_status = main(_cli_args(str(output)))

    assert exit_status == 0
    assert output.read_bytes() == canonical_json_bytes(document)


def test_blob_cli_requires_explicit_live_guard_without_opening_a_socket(tmp_path) -> None:
    with pytest.raises(SystemExit) as raised:
        main(
            [
                "--proof-id",
                "wave-7",
                "--source-commit",
                "6" * 40,
                "--artifact-commit",
                "2" * 40,
                "--bundle-digest",
                "3" * 64,
                "--runtime-configuration-digest",
                "5" * 64,
                "--admission-policy-digest",
                "1" * 64,
                "--deployment-id",
                DEPLOYMENT,
                "--provider-image-digest",
                "sha256:" + "4" * 64,
                "--output",
                str(tmp_path / "blob.json"),
            ]
        )

    assert raised.value.code == 2
    assert not (tmp_path / "blob.json").exists()
