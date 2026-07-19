"""Local contract proof for the private Vercel Blob coordination Adapter."""

from __future__ import annotations

import base64
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import Any

import pytest

import baseball_rag.api.server as api_server
from baseball_rag.public_admission import (
    AdmissionAttempt,
    AdmissionState,
    CasCoordinator,
    MonthlyBudget,
    RunLease,
)
from baseball_rag.public_admission_blob import (
    PRODUCTION_OBJECT_KEY,
    BlobCoordinationConfig,
    BlobCoordinationStore,
    BlobProviderError,
    HttpResponse,
    PublicAdmissionConfigurationError,
    load_blob_public_admission,
)
from baseball_rag.public_admission_state import (
    MAX_STATE_BYTES,
    AdmissionStateCodecError,
    decode_admission_state,
    encode_admission_state,
)

NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
VISITOR = "a" * 64
STATE_ORIGIN = "https://proof.private.blob.vercel-storage.com"
API_ORIGIN = "https://blob.vercel-storage.com"
DATE = "Sun, 19 Jul 2026 12:00:00 GMT"


@dataclass(frozen=True)
class RecordedRequest:
    method: str
    url: str
    headers: dict[str, str]
    data: bytes | None
    timeout: float
    max_response_bytes: int


class ScriptedTransport:
    def __init__(self, *responses: HttpResponse | Exception) -> None:
        self.responses = deque(responses)
        self.requests: list[RecordedRequest] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        self.requests.append(RecordedRequest(**kwargs))
        response = self.responses.popleft()
        if isinstance(response, Exception):
            raise response
        return response


class SharedScriptedBlobBackend:
    """Atomic fake of the narrow provider contract; it never opens a socket."""

    def __init__(self, state: AdmissionState | None, *, date: str = DATE) -> None:
        self._body = None if state is None else encode_admission_state(state)
        self._etag_number = 0
        self._date = date
        self._lock = Lock()
        self.requests: list[RecordedRequest] = []

    def request(self, **kwargs: Any) -> HttpResponse:
        request = RecordedRequest(**kwargs)
        with self._lock:
            self.requests.append(request)
            if request.method == "GET":
                if self._body is None:
                    return HttpResponse(404, {"date": self._date}, b"")
                return HttpResponse(
                    200,
                    {
                        "content-type": "application/json",
                        "date": self._date,
                        "etag": f'"etag-{self._etag_number}"',
                    },
                    self._body,
                )
            assert request.method == "PUT"
            if request.headers["x-allow-overwrite"] == "0":
                if self._body is not None:
                    return HttpResponse(412, {"date": self._date}, b"")
            elif request.headers.get("x-if-match") != f'"etag-{self._etag_number}"':
                return HttpResponse(412, {"date": self._date}, b"")
            self._body = request.data
            self._etag_number += 1
            config = proof_config()
            return HttpResponse(
                200,
                {"date": self._date},
                json_write_response(config),
            )

    def state(self) -> AdmissionState:
        with self._lock:
            assert self._body is not None
            return decode_admission_state(self._body)


def json_write_response(config: BlobCoordinationConfig) -> bytes:
    return ('{"url":"' + config.state_url + '","pathname":"' + config.object_key + '"}').encode()


def proof_config() -> BlobCoordinationConfig:
    return BlobCoordinationConfig.proof(
        token="synthetic-proof-token",
        state_origin=STATE_ORIGIN,
        proof_id="wave-3",
    )


@pytest.fixture(autouse=True)
def block_accidental_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Wave 3 tests must not contact the network")

    monkeypatch.setattr("socket.socket.connect", blocked)
    monkeypatch.setattr("socket.create_connection", blocked)


def test_state_codec_is_deterministic_and_round_trips_schema_version_one() -> None:
    state = AdmissionState(
        running=(
            RunLease(
                visitor=VISITOR,
                run_id="0123456789abcdef0123456789abcdef",
                expires_at=datetime(2026, 7, 19, 12, 0, 15, tzinfo=UTC),
            ),
        ),
        starts_by_visitor=((VISITOR, (NOW,)),),
        monthly_budget=MonthlyBudget(period="2026-07", charged_starts=1),
    )
    expected = (
        b'{"monthly_budget":{"charged_starts":1,"period":"2026-07"},'
        b'"running":[{"expires_at":"2026-07-19T12:00:15Z",'
        b'"run_id":"0123456789abcdef0123456789abcdef",'
        b'"visitor":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}],'
        b'"schema_version":1,"starts_by_visitor":'
        b'[{"starts":["2026-07-19T12:00:00Z"],'
        b'"visitor":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]}'
    )

    assert encode_admission_state(state) == expected
    assert decode_admission_state(expected) == state


@pytest.mark.parametrize(
    "payload",
    [
        b"{}",
        b'{"schema_version":2,"monthly_budget":null,"running":[],"starts_by_visitor":[]}',
        b'{"schema_version":1,"monthly_budget":null,"running":[],"starts_by_visitor":[],"extra":1}',
        b'{"schema_version":true,"monthly_budget":null,"running":[],"starts_by_visitor":[]}',
        b'{"schema_version":1,"monthly_budget":{"period":"2026-07","charged_starts":true},"running":[],"starts_by_visitor":[]}',
        b'{"schema_version":1,"monthly_budget":{"period":"2026-07","charged_starts":101},"running":[],"starts_by_visitor":[]}',
        b'{"schema_version":1,"monthly_budget":null,"running":{},"starts_by_visitor":[]}',
    ],
)
def test_state_codec_rejects_malformed_unsupported_and_contradictory_state(
    payload: bytes,
) -> None:
    with pytest.raises(AdmissionStateCodecError):
        decode_admission_state(payload)


def test_state_codec_rejects_oversized_provider_state_before_json_parsing() -> None:
    with pytest.raises(AdmissionStateCodecError, match="size"):
        decode_admission_state(b"{" + b" " * MAX_STATE_BYTES)


def test_missing_read_and_create_if_absent_use_exact_private_blob_contract() -> None:
    config = proof_config()
    created_body = (
        b'{"url":"https://proof.private.blob.vercel-storage.com/'
        b'groundball/public-admission/v1/proof/wave-3/state.json",'
        b'"pathname":"groundball/public-admission/v1/proof/wave-3/state.json"}'
    )
    transport = ScriptedTransport(
        HttpResponse(status_code=404, headers={"date": DATE}, body=b""),
        HttpResponse(status_code=201, headers={"date": DATE}, body=created_body),
    )
    store = BlobCoordinationStore(config, transport=transport)

    snapshot = store.read()
    initialized = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))

    assert snapshot.state == AdmissionState()
    assert snapshot.observed_at == NOW
    assert store.compare_and_swap(snapshot.version, initialized) is True
    assert transport.requests[0] == RecordedRequest(
        method="GET",
        url=(
            "https://proof.private.blob.vercel-storage.com/"
            "groundball/public-admission/v1/proof/wave-3/state.json"
        ),
        headers={
            "accept": "application/json",
            "authorization": "Bearer synthetic-proof-token",
            "cache-control": "no-cache",
            "x-vercel-blob-access": "private",
            "x-vercel-blob-cache-control-max-age": "0",
        },
        data=None,
        timeout=5.0,
        max_response_bytes=MAX_STATE_BYTES,
    )
    create = transport.requests[1]
    assert create.method == "PUT"
    assert create.url == (
        "https://blob.vercel-storage.com/groundball/public-admission/v1/proof/wave-3/state.json"
    )
    assert create.headers == {
        "authorization": "Bearer synthetic-proof-token",
        "content-type": "application/json",
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "0",
        "x-content-type": "application/json",
        "x-vercel-blob-access": "private",
    }
    assert create.data == encode_admission_state(initialized)
    assert create.timeout == 5.0
    assert create.max_response_bytes == 4096


def test_uncached_read_captures_opaque_etag_for_exact_conditional_put() -> None:
    config = proof_config()
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=12))
    transport = ScriptedTransport(
        HttpResponse(
            status_code=200,
            headers={
                "content-type": "application/json; charset=utf-8",
                "date": DATE,
                "etag": '"opaque-provider-etag-12"',
            },
            body=encode_admission_state(state),
        ),
        HttpResponse(
            status_code=200,
            headers={"date": DATE},
            body=(
                b'{"url":"https://proof.private.blob.vercel-storage.com/'
                b'groundball/public-admission/v1/proof/wave-3/state.json",'
                b'"pathname":"groundball/public-admission/v1/proof/wave-3/state.json"}'
            ),
        ),
    )
    store = BlobCoordinationStore(config, transport=transport)

    snapshot = store.read()
    updated = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=13))

    assert snapshot.state == state
    assert store.compare_and_swap(snapshot.version, updated) is True
    assert transport.requests[1].headers == {
        "authorization": "Bearer synthetic-proof-token",
        "content-type": "application/json",
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1",
        "x-content-type": "application/json",
        "x-if-match": '"opaque-provider-etag-12"',
        "x-vercel-blob-access": "private",
    }


def test_only_precondition_failure_is_a_conflict_and_other_failures_are_sanitized() -> None:
    config = proof_config()
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=1))
    read = HttpResponse(
        status_code=200,
        headers={
            "content-type": "application/json",
            "date": DATE,
            "etag": "opaque-etag",
        },
        body=encode_admission_state(state),
    )
    conflict_store = BlobCoordinationStore(
        config,
        transport=ScriptedTransport(
            read,
            HttpResponse(status_code=412, headers={"date": DATE}, body=b"private body"),
        ),
    )
    snapshot = conflict_store.read()
    assert conflict_store.compare_and_swap(snapshot.version, state) is False

    failed_store = BlobCoordinationStore(
        config,
        transport=ScriptedTransport(
            read,
            HttpResponse(status_code=503, headers={"date": DATE}, body=b"secret detail"),
        ),
    )
    failed_snapshot = failed_store.read()
    with pytest.raises(BlobProviderError) as raised:
        failed_store.compare_and_swap(failed_snapshot.version, state)
    assert "503" not in str(raised.value)
    assert "secret" not in str(raised.value)
    assert "synthetic-proof-token" not in repr(failed_store)


def test_initialization_refuses_to_rewrite_an_existing_object_without_a_budget() -> None:
    backend = SharedScriptedBlobBackend(AdmissionState())
    coordinator = CasCoordinator(BlobCoordinationStore(proof_config(), transport=backend))

    assert coordinator.initialize_current_budget() is False
    assert all(request.method == "GET" for request in backend.requests)


def test_two_blob_coordinators_have_one_initialization_winner() -> None:
    backend = SharedScriptedBlobBackend(None)
    coordinators = tuple(
        CasCoordinator(BlobCoordinationStore(proof_config(), transport=backend)) for _ in range(2)
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        initialized = tuple(
            executor.map(lambda item: item.initialize_current_budget(), coordinators)
        )

    assert sorted(initialized) == [False, True]
    assert backend.state().monthly_budget == MonthlyBudget(period="2026-07", charged_starts=0)
    creates = [
        request
        for request in backend.requests
        if request.method == "PUT" and request.headers["x-allow-overwrite"] == "0"
    ]
    assert creates
    assert all(request.headers["x-allow-overwrite"] == "0" for request in creates)


def test_two_blob_coordinators_cannot_both_admit_the_same_visitor() -> None:
    backend = SharedScriptedBlobBackend(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0)))
    coordinators = tuple(
        CasCoordinator(BlobCoordinationStore(proof_config(), transport=backend)) for _ in range(2)
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda index: coordinators[index].admit(
                    AdmissionAttempt(VISITOR, f"run-{index}", NOW)
                ),
                range(2),
            )
        )

    assert sorted(outcome.kind for outcome in outcomes) == ["admitted", "busy"]
    assert backend.state().monthly_budget == MonthlyBudget("2026-07", 1)
    assert len(backend.state().running) == 1


def test_two_blob_coordinators_cannot_admit_a_101st_monthly_start() -> None:
    backend = SharedScriptedBlobBackend(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 99)))
    coordinators = tuple(
        CasCoordinator(BlobCoordinationStore(proof_config(), transport=backend)) for _ in range(2)
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(
            executor.map(
                lambda index: coordinators[index].admit(
                    AdmissionAttempt(f"{index + 1:064x}", f"run-{index}", NOW)
                ),
                range(2),
            )
        )

    assert sorted(outcome.kind for outcome in outcomes) == ["admitted", "allowance_paused"]
    assert backend.state().monthly_budget == MonthlyBudget("2026-07", 100)


def test_provider_date_drives_rollover_start_time_and_lease_when_local_clock_disagrees() -> None:
    backend = SharedScriptedBlobBackend(AdmissionState(monthly_budget=MonthlyBudget("2026-06", 87)))
    coordinator = CasCoordinator(
        BlobCoordinationStore(proof_config(), transport=backend),
        clock=lambda: datetime(2038, 1, 1, tzinfo=UTC),
    )

    outcome = coordinator.admit(
        AdmissionAttempt(VISITOR, "run-trusted-time", datetime(1999, 1, 1, tzinfo=UTC))
    )

    state = backend.state()
    assert outcome.kind == "admitted"
    assert state.monthly_budget == MonthlyBudget("2026-07", 1)
    assert state.starts_for(VISITOR) == (NOW,)
    assert state.running[0].expires_at == NOW + timedelta(seconds=15)


def test_provider_date_drives_monthly_retry_when_local_clock_disagrees() -> None:
    backend = SharedScriptedBlobBackend(
        AdmissionState(monthly_budget=MonthlyBudget("2026-07", 100))
    )
    coordinator = CasCoordinator(
        BlobCoordinationStore(proof_config(), transport=backend),
        clock=lambda: datetime(2038, 1, 1, tzinfo=UTC),
    )

    outcome = coordinator.admit(
        AdmissionAttempt(VISITOR, "run-month", datetime(1999, 1, 1, tzinfo=UTC))
    )

    assert outcome.kind == "allowance_paused"
    assert outcome.retry_at == datetime(2026, 8, 1, tzinfo=UTC)
    assert outcome.retry_after_seconds == 1_080_000


def test_provider_date_drives_rate_retry_when_local_clock_disagrees() -> None:
    starts = (NOW - timedelta(seconds=50), NOW - timedelta(seconds=30), NOW - timedelta(seconds=10))
    backend = SharedScriptedBlobBackend(
        AdmissionState(
            starts_by_visitor=((VISITOR, starts),),
            monthly_budget=MonthlyBudget("2026-07", 3),
        )
    )
    coordinator = CasCoordinator(
        BlobCoordinationStore(proof_config(), transport=backend),
        clock=lambda: datetime(2038, 1, 1, tzinfo=UTC),
    )

    outcome = coordinator.admit(
        AdmissionAttempt(VISITOR, "run-rate", datetime(1999, 1, 1, tzinfo=UTC))
    )

    assert outcome.kind == "rate_limited"
    assert outcome.retry_at == NOW + timedelta(seconds=10)
    assert outcome.retry_after_seconds == 10


def test_provider_date_drives_hour_window_when_local_clock_disagrees() -> None:
    starts = tuple(NOW - timedelta(minutes=55 - index * 5) for index in range(12))
    backend = SharedScriptedBlobBackend(
        AdmissionState(
            starts_by_visitor=((VISITOR, starts),),
            monthly_budget=MonthlyBudget("2026-07", 12),
        )
    )
    coordinator = CasCoordinator(
        BlobCoordinationStore(proof_config(), transport=backend),
        clock=lambda: datetime(1999, 1, 1, tzinfo=UTC),
    )

    outcome = coordinator.admit(
        AdmissionAttempt(VISITOR, "run-hour", datetime(2038, 1, 1, tzinfo=UTC))
    )

    assert outcome.kind == "rate_limited"
    assert outcome.reason == "twelve_starts_per_hour"
    assert outcome.retry_at == NOW + timedelta(minutes=5)


def test_missing_or_malformed_provider_date_fails_closed_without_guessing() -> None:
    body = encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0)))
    for headers in (
        {"content-type": "application/json", "etag": "etag"},
        {"content-type": "application/json", "etag": "etag", "date": "not-a-date"},
    ):
        store = BlobCoordinationStore(
            proof_config(),
            transport=ScriptedTransport(HttpResponse(200, headers, body)),
        )
        outcome = CasCoordinator(store, clock=lambda: NOW).readiness()
        assert outcome.kind == "provider_unavailable"


def test_stable_digest_key_configuration_decodes_at_least_32_bytes_without_rendering_it() -> None:
    key = b"stable-synthetic-digest-key-material"
    encoded_key = base64.urlsafe_b64encode(key).decode()
    configured = load_blob_public_admission(
        {
            "GROUNDBALL_BLOB_NAMESPACE": "proof",
            "GROUNDBALL_BLOB_PROOF_ID": "wave-3",
            "GROUNDBALL_BLOB_STATE_ORIGIN": STATE_ORIGIN,
            "GROUNDBALL_BLOB_TOKEN": "synthetic-proof-token",
            "GROUNDBALL_VISITOR_DIGEST_KEY": encoded_key,
        },
        transport=ScriptedTransport(),
    )

    assert configured.digest_key == key
    assert configured.store.object_key.endswith("/proof/wave-3/state.json")
    assert encoded_key not in repr(configured)
    assert "synthetic-proof-token" not in repr(configured)


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"GROUNDBALL_BLOB_NAMESPACE": "unknown"},
        {"GROUNDBALL_BLOB_NAMESPACE": "proof", "GROUNDBALL_BLOB_PROOF_ID": ""},
        {
            "GROUNDBALL_BLOB_NAMESPACE": "production",
            "GROUNDBALL_BLOB_PROOF_ID": "wave-3",
        },
        {"GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"short").decode()},
        {"GROUNDBALL_VISITOR_DIGEST_KEY": "private-key-material-not-base64"},
    ],
)
def test_missing_or_inconsistent_blob_configuration_fails_closed_and_sanitized(
    overrides: dict[str, str],
) -> None:
    secret_key_text = base64.urlsafe_b64encode(b"k" * 32).decode()
    environment = {
        "GROUNDBALL_BLOB_NAMESPACE": "proof",
        "GROUNDBALL_BLOB_PROOF_ID": "wave-3",
        "GROUNDBALL_BLOB_STATE_ORIGIN": STATE_ORIGIN,
        "GROUNDBALL_BLOB_TOKEN": "synthetic-secret-token",
        "GROUNDBALL_VISITOR_DIGEST_KEY": secret_key_text,
        **overrides,
    }
    if not overrides:
        environment.pop("GROUNDBALL_BLOB_TOKEN")

    with pytest.raises(PublicAdmissionConfigurationError) as raised:
        load_blob_public_admission(environment, transport=ScriptedTransport())

    rendered = f"{raised.value!s} {raised.value!r}"
    assert "synthetic-secret-token" not in rendered
    assert secret_key_text not in rendered
    assert "private-key-material-not-base64" not in rendered


def test_blob_configuration_integrates_through_existing_server_cas_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = b"stable-synthetic-digest-key-material"
    backend = SharedScriptedBlobBackend(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0)))
    monkeypatch.setattr(api_server, "_public_admission", None)
    monkeypatch.setattr(api_server, "_visitor_digest_key", None)
    monkeypatch.setattr(api_server, "_public_admission_is_shared", False)

    coordinator = api_server.configure_public_admission_from_environment(
        environment={
            "GROUNDBALL_BLOB_NAMESPACE": "proof",
            "GROUNDBALL_BLOB_PROOF_ID": "wave-3",
            "GROUNDBALL_BLOB_STATE_ORIGIN": STATE_ORIGIN,
            "GROUNDBALL_BLOB_TOKEN": "synthetic-proof-token",
            "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(key).decode(),
        },
        transport=backend,
    )

    assert coordinator.readiness().kind == "ready"
    assert api_server._shared_public_admission_components() == (coordinator, key)


def test_readiness_proves_supported_state_and_counts_the_uncached_read() -> None:
    backend = SharedScriptedBlobBackend(
        AdmissionState(monthly_budget=MonthlyBudget("2026-06", 100))
    )
    store = BlobCoordinationStore(proof_config(), transport=backend)

    outcome = CasCoordinator(store, clock=lambda: datetime(2038, 1, 1, tzinfo=UTC)).readiness()

    assert outcome.kind == "ready"
    assert store.operation_counts().attempted_reads == 1
    assert store.operation_counts().successful_reads == 1


def test_operation_counts_include_conflicts_and_failures_by_local_operation_class() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))
    valid_read = HttpResponse(
        200,
        {"content-type": "application/json", "date": DATE, "etag": "etag-1"},
        encode_admission_state(state),
    )
    transport = ScriptedTransport(
        HttpResponse(404, {"date": DATE}, b""),
        HttpResponse(412, {"date": DATE}, b"conflict"),
        valid_read,
        HttpResponse(412, {"date": DATE}, b"conflict"),
        HttpResponse(503, {"date": DATE}, b"private failure"),
    )
    store = BlobCoordinationStore(proof_config(), transport=transport)

    missing = store.read()
    assert store.compare_and_swap(missing.version, state) is False
    present = store.read()
    assert store.compare_and_swap(present.version, state) is False
    with pytest.raises(BlobProviderError):
        store.read()

    assert store.operation_counts().as_dict() == {
        "attempted_reads": 3,
        "successful_reads": 1,
        "missing_reads": 1,
        "failed_reads": 1,
        "attempted_conditional_writes": 1,
        "successful_conditional_writes": 0,
        "conditional_conflicts": 1,
        "failed_conditional_writes": 0,
        "attempted_create_if_absent": 1,
        "successful_create_if_absent": 0,
        "create_conflicts": 1,
        "failed_create_if_absent": 0,
    }


def test_malformed_provider_state_is_allowance_invalid_not_provider_unavailable() -> None:
    store = BlobCoordinationStore(
        proof_config(),
        transport=ScriptedTransport(
            HttpResponse(
                200,
                {"content-type": "application/json", "date": DATE, "etag": "etag"},
                b'{"schema_version":99}',
            )
        ),
    )

    outcome = CasCoordinator(store, clock=lambda: datetime(2038, 1, 1, tzinfo=UTC)).readiness()

    assert outcome.kind == "allowance_paused"
    assert outcome.reason == "monthly_budget_invalid"


def test_proof_namespace_cannot_spell_the_production_object_key() -> None:
    config = proof_config()

    assert config.object_key == "groundball/public-admission/v1/proof/wave-3/state.json"
    assert config.object_key != PRODUCTION_OBJECT_KEY
    with pytest.raises(ValueError, match="proof identifier"):
        BlobCoordinationConfig.proof(
            token="synthetic-proof-token",
            state_origin=STATE_ORIGIN,
            proof_id="../production",
        )
