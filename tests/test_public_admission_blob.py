"""Local contract proof for the private Vercel Blob coordination Adapter."""

from __future__ import annotations

import asyncio
import base64
import json
import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
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
    BlobProviderError,
    HttpResponse,
    OidcBlobCredentialProvider,
    PublicAdmissionConfigurationError,
    RequestsHttpTransport,
    StaticBlobCredentialProvider,
    load_blob_public_admission,
    request_oidc_token_context,
)
from baseball_rag.public_admission_blob import (
    BlobCoordinationStore as _BlobCoordinationStore,
)
from baseball_rag.public_admission_state import (
    MAX_STATE_BYTES,
    AdmissionStateCodecError,
    decode_admission_state,
    encode_admission_state,
)
from baseball_rag.public_release_config import load_runtime_configuration

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
VISITOR = "a" * 64
STORE_ID = "ProofStore123"
DATE = "Sun, 19 Jul 2026 12:00:00 GMT"
STARTUP_OIDC = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJzdGFydHVwIn0.startup-signature"
REQUEST_OIDC_A = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJyZXF1ZXN0LWEifQ.request-signature-a"
REQUEST_OIDC_B = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJyZXF1ZXN0LWIifQ.request-signature-b"


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


class FakeResponse:
    def __init__(self, *chunks: bytes) -> None:
        self.status_code = 200
        self.headers = {"Content-Type": "application/json"}
        self.chunks = chunks
        self.closed = False

    def iter_content(self, *, chunk_size: int) -> tuple[bytes, ...]:
        assert chunk_size == 8192
        return self.chunks

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def request(self, *args: Any, **kwargs: Any) -> FakeResponse:
        self.calls.append((args, kwargs))
        return self.response


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
        store_id=f"store_{STORE_ID}",
        proof_id="wave-3",
    )


def BlobCoordinationStore(  # noqa: N802 - test factory mirrors the production class
    config: BlobCoordinationConfig,
    *,
    credential_provider=None,
    **kwargs: Any,
) -> _BlobCoordinationStore:
    return _BlobCoordinationStore(
        config,
        credential_provider=credential_provider
        or StaticBlobCredentialProvider("synthetic-proof-token"),
        **kwargs,
    )


@pytest.fixture(autouse=True)
def block_accidental_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def blocked(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("Wave 3 tests must not contact the network")

    monkeypatch.setattr("socket.socket.connect", blocked)
    monkeypatch.setattr("socket.create_connection", blocked)


def test_request_only_oidc_provider_requires_a_valid_bound_request_credential() -> None:
    provider = OidcBlobCredentialProvider()

    with pytest.raises(BlobProviderError) as raised:
        provider.resolve()
    with request_oidc_token_context(REQUEST_OIDC_A):
        assert provider.resolve() == REQUEST_OIDC_A

    rendered = f"{raised.value!s} {raised.value!r} {provider!r}"
    assert REQUEST_OIDC_A not in rendered
    assert rendered.count("Blob coordination request failed.") == 2


def test_blob_configuration_is_credential_free_and_oidc_resolution_is_request_scoped() -> None:
    config = BlobCoordinationConfig.proof(store_id=f"store_{STORE_ID}", proof_id="wave-7")
    provider = OidcBlobCredentialProvider(startup_token=STARTUP_OIDC)

    assert "token" not in asdict(config)
    assert STARTUP_OIDC not in repr(config)
    assert STARTUP_OIDC not in json.dumps(asdict(config), sort_keys=True)
    assert provider.resolve() == STARTUP_OIDC
    with request_oidc_token_context(REQUEST_OIDC_A):
        assert provider.resolve() == REQUEST_OIDC_A
    assert provider.resolve() == STARTUP_OIDC


def test_two_interleaved_request_contexts_never_swap_or_retain_oidc_credentials() -> None:
    provider = OidcBlobCredentialProvider(startup_token=STARTUP_OIDC)

    async def exercise() -> tuple[tuple[str, str], tuple[str, str]]:
        ready = asyncio.Event()
        release = asyncio.Event()

        async def first() -> tuple[str, str]:
            with request_oidc_token_context(REQUEST_OIDC_A):
                before = provider.resolve()
                ready.set()
                await release.wait()
                return before, provider.resolve()

        async def second() -> tuple[str, str]:
            await ready.wait()
            with request_oidc_token_context(REQUEST_OIDC_B):
                before = provider.resolve()
                release.set()
                await asyncio.sleep(0)
                return before, provider.resolve()

        first_result, second_result = await asyncio.gather(first(), second())
        return first_result, second_result

    assert asyncio.run(exercise()) == (
        (REQUEST_OIDC_A, REQUEST_OIDC_A),
        (REQUEST_OIDC_B, REQUEST_OIDC_B),
    )
    assert provider.resolve() == STARTUP_OIDC


@pytest.mark.parametrize(
    "token",
    [None, "", "   ", "not-a-jwt", "a.b", "a.b.c d", "a.b." + "x" * 8191],
)
def test_missing_malformed_or_oversized_request_oidc_fails_closed_and_sanitized(
    token: str | None,
) -> None:
    provider = OidcBlobCredentialProvider(startup_token=STARTUP_OIDC)

    with request_oidc_token_context(token):
        with pytest.raises(BlobProviderError) as raised:
            provider.resolve()

    rendered = f"{raised.value!s} {raised.value!r} {provider!r}"
    if token:
        assert token not in rendered
    assert STARTUP_OIDC not in rendered
    assert provider.resolve() == STARTUP_OIDC


def test_static_credential_provider_is_secret_safe_and_proof_only_by_construction() -> None:
    provider = StaticBlobCredentialProvider("synthetic-static-secret")

    assert provider.resolve() == "synthetic-static-secret"
    assert "synthetic-static-secret" not in repr(provider)


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


def test_state_codec_rejects_duplicate_json_object_keys() -> None:
    payload = (
        b'{"schema_version":1,"schema_version":1,"monthly_budget":null,'
        b'"running":[],"starts_by_visitor":[]}'
    )

    with pytest.raises(AdmissionStateCodecError, match="malformed"):
        decode_admission_state(payload)


def test_state_codec_rejects_same_period_start_undercount() -> None:
    payload = (
        b'{"schema_version":1,'
        b'"monthly_budget":{"period":"2026-07","charged_starts":1},'
        b'"running":[],"starts_by_visitor":[{"visitor":"'
        + VISITOR.encode()
        + b'","starts":["2026-07-01T00:00:00Z","2026-07-19T12:00:00Z"]}]}'
    )

    with pytest.raises(AdmissionStateCodecError, match="contradictory"):
        decode_admission_state(payload)


def test_state_codec_preserves_previous_month_history_and_boundary_lease() -> None:
    state = AdmissionState(
        running=(
            RunLease(
                visitor=VISITOR,
                run_id="month-boundary",
                expires_at=datetime(2026, 7, 1, 0, 0, 10, tzinfo=UTC),
            ),
        ),
        starts_by_visitor=((VISITOR, (datetime(2026, 6, 30, 23, 59, 55, tzinfo=UTC),)),),
        monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0),
    )

    assert decode_admission_state(encode_admission_state(state)) == state


def test_requests_transport_streams_with_bound_timeout_and_disables_redirects() -> None:
    response = FakeResponse(b'{"ok":', b"true}")
    session = FakeSession(response)
    transport = RequestsHttpTransport(session)  # type: ignore[arg-type]

    result = transport.request(
        method="GET",
        url="https://example.invalid/state?cache=0",
        headers={"authorization": "Bearer synthetic"},
        data=None,
        timeout=3.5,
        max_response_bytes=11,
    )

    assert result.body == b'{"ok":true}'
    assert session.calls == [
        (
            ("GET", "https://example.invalid/state?cache=0"),
            {
                "headers": {"authorization": "Bearer synthetic"},
                "data": None,
                "timeout": 3.5,
                "stream": True,
                "allow_redirects": False,
            },
        )
    ]
    assert response.closed is True

    oversized_response = FakeResponse(b"1234", b"56")
    oversized_transport = RequestsHttpTransport(FakeSession(oversized_response))  # type: ignore[arg-type]
    with pytest.raises(BlobProviderError):
        oversized_transport.request(
            method="GET",
            url="https://example.invalid/state?cache=0",
            headers={},
            data=None,
            timeout=1.0,
            max_response_bytes=5,
        )
    assert oversized_response.closed is True


def test_missing_read_and_create_if_absent_use_exact_private_blob_contract() -> None:
    config = proof_config()
    created_body = (
        b'{"url":"https://proofstore123.private.blob.vercel-storage.com/'
        b'groundball/public-admission/v1/proof/wave-3/state.json",'
        b'"pathname":"groundball/public-admission/v1/proof/wave-3/state.json"}'
    )
    transport = ScriptedTransport(
        HttpResponse(status_code=404, headers={"date": DATE}, body=b""),
        HttpResponse(status_code=201, headers={"date": DATE}, body=created_body),
    )
    store = BlobCoordinationStore(
        config,
        transport=transport,
        request_id_factory=lambda: "ProofStore123:1721390400000:0123456789abcdef0123456789abcdef",
    )

    snapshot = store.read()
    initialized = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=0))

    assert snapshot.state == AdmissionState()
    assert snapshot.observed_at == NOW
    assert store.compare_and_swap(snapshot.version, initialized) is True
    assert transport.requests[0] == RecordedRequest(
        method="GET",
        url=(
            "https://proofstore123.private.blob.vercel-storage.com/"
            "groundball/public-admission/v1/proof/wave-3/state.json?cache=0"
        ),
        headers={
            "accept": "application/json",
            "authorization": "Bearer synthetic-proof-token",
        },
        data=None,
        timeout=5.0,
        max_response_bytes=MAX_STATE_BYTES,
    )
    create = transport.requests[1]
    assert create.method == "PUT"
    assert create.url == (
        "https://vercel.com/api/blob/?pathname="
        "groundball%2Fpublic-admission%2Fv1%2Fproof%2Fwave-3%2Fstate.json"
    )
    assert create.headers == {
        "authorization": "Bearer synthetic-proof-token",
        "content-type": "application/json",
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "0",
        "x-api-blob-request-attempt": "0",
        "x-api-blob-request-id": ("ProofStore123:1721390400000:0123456789abcdef0123456789abcdef"),
        "x-api-version": "12",
        "x-content-type": "application/json",
        "x-vercel-blob-access": "private",
        "x-vercel-blob-store-id": STORE_ID,
    }
    assert create.data == encode_admission_state(initialized)
    assert create.timeout == 5.0
    assert create.max_response_bytes == 4096


def test_weak_read_etag_is_normalized_for_exact_conditional_put() -> None:
    config = proof_config()
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=12))
    transport = ScriptedTransport(
        HttpResponse(
            status_code=200,
            headers={
                "content-type": "application/json; charset=utf-8",
                "date": DATE,
                "etag": 'W/"opaque-provider-etag-12"',
            },
            body=encode_admission_state(state),
        ),
        HttpResponse(
            status_code=200,
            headers={"date": DATE},
            body=(
                b'{"url":"https://proofstore123.private.blob.vercel-storage.com/'
                b'groundball/public-admission/v1/proof/wave-3/state.json",'
                b'"pathname":"groundball/public-admission/v1/proof/wave-3/state.json"}'
            ),
        ),
    )
    store = BlobCoordinationStore(
        config,
        transport=transport,
        request_id_factory=lambda: "ProofStore123:1721390400001:fedcba9876543210fedcba9876543210",
    )

    snapshot = store.read()
    updated = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=13))

    assert snapshot.state == state
    assert store.compare_and_swap(snapshot.version, updated) is True
    assert transport.requests[1].headers == {
        "authorization": "Bearer synthetic-proof-token",
        "content-type": "application/json",
        "x-add-random-suffix": "0",
        "x-allow-overwrite": "1",
        "x-api-blob-request-attempt": "0",
        "x-api-blob-request-id": ("ProofStore123:1721390400001:fedcba9876543210fedcba9876543210"),
        "x-api-version": "12",
        "x-content-type": "application/json",
        "x-if-match": '"opaque-provider-etag-12"',
        "x-vercel-blob-access": "private",
        "x-vercel-blob-store-id": STORE_ID,
    }


def test_strong_read_etag_is_preserved_exactly_for_conditional_put() -> None:
    config = proof_config()
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=12))
    transport = ScriptedTransport(
        HttpResponse(
            200,
            {
                "content-type": "application/json",
                "date": DATE,
                "etag": '"Case-Sensitive\\opaque"',
            },
            encode_admission_state(state),
        ),
        HttpResponse(200, {}, json_write_response(config)),
    )
    store = BlobCoordinationStore(config, transport=transport)

    snapshot = store.read()

    assert store.compare_and_swap(snapshot.version, state) is True
    assert transport.requests[1].headers["x-if-match"] == '"Case-Sensitive\\opaque"'


@pytest.mark.parametrize(
    "etag",
    [
        'W/""',
        'W/"contains space"',
        'W/"contains\t-tab"',
        'W/"unterminated',
        "W/opaque",
        'W/"opaque"extra',
        'w/"opaque"',
        '""',
        '"contains space"',
        '"opaque"extra',
        "unquoted",
    ],
)
def test_malformed_or_unsafe_read_etag_fails_before_conditional_write(etag: str) -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=12))
    transport = ScriptedTransport(
        HttpResponse(
            200,
            {"content-type": "application/json", "date": DATE, "etag": etag},
            encode_admission_state(state),
        )
    )
    store = BlobCoordinationStore(proof_config(), transport=transport)

    with pytest.raises(BlobProviderError):
        store.read()

    assert [request.method for request in transport.requests] == ["GET"]


def test_store_resolves_oidc_again_for_each_read_and_write_with_request_precedence() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=1))
    transport = ScriptedTransport(
        HttpResponse(
            200,
            {"content-type": "application/json", "date": DATE, "etag": '"etag-1"'},
            encode_admission_state(state),
        ),
        HttpResponse(200, {}, json_write_response(proof_config())),
    )
    store = _BlobCoordinationStore(
        proof_config(),
        credential_provider=OidcBlobCredentialProvider(startup_token=STARTUP_OIDC),
        transport=transport,
    )

    with request_oidc_token_context(REQUEST_OIDC_A):
        snapshot = store.read()
    with request_oidc_token_context(REQUEST_OIDC_B):
        assert store.compare_and_swap(snapshot.version, state) is True

    assert transport.requests[0].headers["authorization"] == f"Bearer {REQUEST_OIDC_A}"
    assert transport.requests[1].headers["authorization"] == f"Bearer {REQUEST_OIDC_B}"
    assert REQUEST_OIDC_A not in repr(store)
    assert REQUEST_OIDC_B not in repr(store)


@pytest.mark.parametrize("status_code", [401, 403, 429, 500, 503])
def test_read_authentication_rate_and_provider_failures_are_never_missing_reads(
    status_code: int,
) -> None:
    store = BlobCoordinationStore(
        proof_config(),
        transport=ScriptedTransport(HttpResponse(status_code, {}, b"private detail")),
    )

    with pytest.raises(BlobProviderError):
        store.read()

    counts = store.operation_counts()
    assert counts.missing_reads == 0
    assert counts.failed_reads == 1


@pytest.mark.parametrize("status_code", [401, 403, 429, 500, 503])
@pytest.mark.parametrize("create", [True, False])
def test_authentication_rate_and_provider_failures_are_never_create_or_cas_conflicts(
    status_code: int,
    create: bool,
) -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=1))
    read = (
        HttpResponse(404, {"date": DATE}, b"")
        if create
        else HttpResponse(
            200,
            {"content-type": "application/json", "date": DATE, "etag": '"etag-1"'},
            encode_admission_state(state),
        )
    )
    store = BlobCoordinationStore(
        proof_config(),
        transport=ScriptedTransport(read, HttpResponse(status_code, {}, b"private detail")),
    )
    snapshot = store.read()

    with pytest.raises(BlobProviderError):
        store.compare_and_swap(snapshot.version, state)

    counts = store.operation_counts()
    assert counts.create_conflicts == 0
    assert counts.conditional_conflicts == 0
    assert (counts.failed_create_if_absent if create else counts.failed_conditional_writes) == 1


def test_default_write_request_ids_are_unique_opaque_hex_and_not_retried() -> None:
    backend = SharedScriptedBlobBackend(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0)))
    store = BlobCoordinationStore(proof_config(), transport=backend)

    first = store.read()
    assert store.compare_and_swap(
        first.version,
        AdmissionState(monthly_budget=MonthlyBudget("2026-07", 1)),
    )
    second = store.read()
    assert store.compare_and_swap(
        second.version,
        AdmissionState(monthly_budget=MonthlyBudget("2026-07", 2)),
    )

    request_ids = [
        request.headers["x-api-blob-request-id"]
        for request in backend.requests
        if request.method == "PUT"
    ]
    assert len(request_ids) == 2
    assert len(set(request_ids)) == 2
    assert all(
        re.fullmatch(r"ProofStore123:\d{13}:[0-9a-f]{32}", request_id) for request_id in request_ids
    )
    assert all(
        request.headers["x-api-blob-request-attempt"] == "0"
        for request in backend.requests
        if request.method == "PUT"
    )


def test_ambiguous_write_failure_is_not_automatically_retried() -> None:
    state = AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))
    transport = ScriptedTransport(
        HttpResponse(
            200,
            {"content-type": "application/json", "date": DATE, "etag": '"etag"'},
            encode_admission_state(state),
        ),
        BlobProviderError(),
    )
    store = BlobCoordinationStore(proof_config(), transport=transport)
    snapshot = store.read()

    with pytest.raises(BlobProviderError):
        store.compare_and_swap(snapshot.version, state)

    assert [request.method for request in transport.requests] == ["GET", "PUT"]


def test_only_precondition_failure_is_a_conflict_and_other_failures_are_sanitized() -> None:
    config = proof_config()
    state = AdmissionState(monthly_budget=MonthlyBudget(period="2026-07", charged_starts=1))
    read = HttpResponse(
        status_code=200,
        headers={
            "content-type": "application/json",
            "date": DATE,
            "etag": '"opaque-etag"',
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


@pytest.mark.parametrize(
    "date",
    [
        None,
        "not-a-date",
        "Sun, 19 Jul 2026 12:00:00 UTC",
        "Sunday, 19-Jul-26 12:00:00 GMT",
        "Sun Jul 19 12:00:00 2026",
        "Mon, 19 Jul 2026 12:00:00 GMT",
    ],
)
def test_noncanonical_provider_date_fails_closed_without_guessing(date: str | None) -> None:
    body = encode_admission_state(AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0)))
    headers = {"content-type": "application/json", "etag": '"etag"'}
    if date is not None:
        headers["date"] = date
    store = BlobCoordinationStore(
        proof_config(),
        transport=ScriptedTransport(HttpResponse(200, headers, body)),
    )
    outcome = CasCoordinator(store, clock=lambda: NOW).readiness()
    assert outcome.kind == "provider_unavailable"


def test_vercel_oidc_configuration_uses_connected_private_blob_identity_without_rendering_it() -> (
    None
):
    key = b"stable-synthetic-digest-key-material"
    oidc = STARTUP_OIDC
    configured = load_blob_public_admission(
        {
            "GROUNDBALL_BLOB_NAMESPACE": "proof",
            "GROUNDBALL_BLOB_PROOF_ID": "wave-7",
            "BLOB_STORE_ID": f"store_{STORE_ID}",
            "VERCEL_OIDC_TOKEN": oidc,
            "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(key).decode(),
        },
        transport=ScriptedTransport(),
    )

    assert configured.authentication_mode == "vercel_oidc_request_scoped"
    assert configured.store.store_id == STORE_ID
    assert oidc not in repr(configured)
    assert oidc not in repr(configured.store)


def test_stable_digest_key_configuration_decodes_at_least_32_bytes_without_rendering_it() -> None:
    key = b"stable-synthetic-digest-key-material"
    encoded_key = base64.urlsafe_b64encode(key).decode()
    configured = load_blob_public_admission(
        {
            "GROUNDBALL_BLOB_NAMESPACE": "proof",
            "GROUNDBALL_BLOB_PROOF_ID": "wave-3",
            "GROUNDBALL_BLOB_STORE_ID": f"store_{STORE_ID}",
            "GROUNDBALL_BLOB_TOKEN": "synthetic-proof-token",
            "GROUNDBALL_VISITOR_DIGEST_KEY": encoded_key,
        },
        transport=ScriptedTransport(),
    )

    assert configured.authentication_mode == "groundball_static_token"
    assert configured.digest_key == key
    assert configured.store.object_key.endswith("/proof/wave-3/state.json")
    assert configured.store.state_url == (
        "https://proofstore123.private.blob.vercel-storage.com/"
        "groundball/public-admission/v1/proof/wave-3/state.json"
    )
    assert configured.store.store_id == STORE_ID
    assert encoded_key not in repr(configured)
    assert "synthetic-proof-token" not in repr(configured)


def test_mixed_case_store_id_preserves_header_identity_and_uses_canonical_lowercase_host() -> None:
    config = BlobCoordinationConfig.production(store_id="store_xgwLdzdOghF780pq")

    assert config.store_id == "xgwLdzdOghF780pq"
    assert config.state_url == (
        "https://xgwldzdoghf780pq.private.blob.vercel-storage.com/"
        "groundball/public-admission/v1/production/state.json"
    )


@pytest.mark.parametrize(
    "store_id",
    [
        "",
        "store_",
        "contains-hyphen",
        "contains.dot",
        "public.blob.vercel-storage.com",
        "user@host",
        "host:443",
        "host/path",
        "host?cache=0",
        "host#fragment",
        "a" * 64,
    ],
)
def test_store_id_cannot_select_an_arbitrary_or_public_origin(store_id: str) -> None:
    with pytest.raises(ValueError, match="store identifier"):
        BlobCoordinationConfig.production(store_id=store_id)


def test_mixed_case_store_write_accepts_only_the_exact_canonical_provider_response() -> None:
    config = BlobCoordinationConfig.production(store_id="store_xgwLdzdOghF780pq")
    state = AdmissionState(monthly_budget=MonthlyBudget("2026-07", 0))
    transport = ScriptedTransport(
        HttpResponse(404, {"date": DATE}, b""),
        HttpResponse(200, {}, json_write_response(config)),
    )
    store = BlobCoordinationStore(
        config,
        transport=transport,
        request_id_factory=lambda: (
            "xgwLdzdOghF780pq:1721390400000:0123456789abcdef0123456789abcdef"
        ),
    )

    snapshot = store.read()

    assert store.compare_and_swap(snapshot.version, state) is True
    assert transport.requests[1].headers["x-vercel-blob-store-id"] == "xgwLdzdOghF780pq"
    assert config.state_url == (
        "https://xgwldzdoghf780pq.private.blob.vercel-storage.com/"
        "groundball/public-admission/v1/production/state.json"
    )


@pytest.mark.parametrize(
    "url,pathname",
    [
        (
            "https://foreign.private.blob.vercel-storage.com/"
            "groundball/public-admission/v1/production/state.json",
            PRODUCTION_OBJECT_KEY,
        ),
        (
            "https://xgwldzdoghf780pq.private.blob.vercel-storage.com/"
            "groundball/public-admission/v1/production/state.json",
            "groundball/public-admission/v1/production/foreign.json",
        ),
        (
            "https://xgwLdzdOghF780pq.private.blob.vercel-storage.com/"
            "groundball/public-admission/v1/production/state.json",
            PRODUCTION_OBJECT_KEY,
        ),
    ],
)
def test_mixed_case_store_write_rejects_noncanonical_host_or_foreign_pathname(
    url: str,
    pathname: str,
) -> None:
    config = BlobCoordinationConfig.production(store_id="store_xgwLdzdOghF780pq")
    transport = ScriptedTransport(
        HttpResponse(404, {"date": DATE}, b""),
        HttpResponse(
            200,
            {},
            json.dumps({"url": url, "pathname": pathname}).encode(),
        ),
    )
    store = BlobCoordinationStore(config, transport=transport)
    snapshot = store.read()

    with pytest.raises(BlobProviderError):
        store.compare_and_swap(snapshot.version, AdmissionState())


def test_server_declares_only_the_strict_blob_configuration_environment() -> None:
    assert api_server._BLOB_CONFIGURATION_ENV_VARS == {
        "BLOB_READ_WRITE_TOKEN",
        "BLOB_STORE_ID",
        "VERCEL_OIDC_TOKEN",
        "GROUNDBALL_BLOB_NAMESPACE",
        "GROUNDBALL_BLOB_PROOF_ID",
        "GROUNDBALL_BLOB_STORE_ID",
        "GROUNDBALL_BLOB_TOKEN",
        "GROUNDBALL_VISITOR_DIGEST_KEY",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"GROUNDBALL_BLOB_NAMESPACE": "unknown"},
        {"GROUNDBALL_BLOB_NAMESPACE": "proof", "GROUNDBALL_BLOB_PROOF_ID": ""},
        {"GROUNDBALL_BLOB_STORE_ID": ""},
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
        "GROUNDBALL_BLOB_STORE_ID": f"store_{STORE_ID}",
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


@pytest.mark.parametrize(
    "ambiguous",
    [
        {"VERCEL_OIDC_TOKEN": "synthetic-oidc"},
        {
            "BLOB_STORE_ID": f"store_{STORE_ID}",
            "VERCEL_OIDC_TOKEN": "synthetic-oidc",
            "GROUNDBALL_BLOB_STORE_ID": f"store_{STORE_ID}",
            "GROUNDBALL_BLOB_TOKEN": "synthetic-static",
        },
        {
            "BLOB_STORE_ID": "store_ForeignStore",
            "VERCEL_OIDC_TOKEN": "synthetic-oidc",
            "GROUNDBALL_BLOB_STORE_ID": f"store_{STORE_ID}",
        },
    ],
)
def test_blob_configuration_rejects_partial_mixed_or_ambiguous_auth(
    ambiguous: dict[str, str],
) -> None:
    environment = {
        "GROUNDBALL_BLOB_NAMESPACE": "proof",
        "GROUNDBALL_BLOB_PROOF_ID": "wave-7",
        "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
        **ambiguous,
    }

    with pytest.raises(PublicAdmissionConfigurationError) as raised:
        load_blob_public_admission(environment, transport=ScriptedTransport())

    rendered = f"{raised.value!s} {raised.value!r}"
    assert "synthetic" not in rendered
    assert "ForeignStore" not in rendered


@pytest.mark.parametrize(
    ("namespace", "expected_object_key"),
    [
        (
            "protected_preview",
            "groundball/public-admission/v1/protected-preview/state.json",
        ),
        ("production", "groundball/public-admission/v1/production/state.json"),
    ],
)
def test_deployed_runtime_constructs_with_request_only_oidc_configuration(
    namespace: str,
    expected_object_key: str,
) -> None:
    configured = load_blob_public_admission(
        {
            "BLOB_STORE_ID": f"store_{STORE_ID}",
            "GROUNDBALL_BLOB_NAMESPACE": namespace,
            "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
        },
        transport=ScriptedTransport(),
    )

    assert configured.authentication_mode == "vercel_oidc_request_scoped"
    assert configured.store.object_key == expected_object_key


def test_protected_preview_requires_oidc_store_namespace_digest_and_valid_startup_fallback() -> (
    None
):
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    environment = {
        "BLOB_STORE_ID": f"store_{STORE_ID}",
        "GROUNDBALL_BLOB_NAMESPACE": "protected_preview",
        "GROUNDBALL_VISITOR_DIGEST_KEY": key,
        "VERCEL_OIDC_TOKEN": STARTUP_OIDC,
    }

    configured = load_blob_public_admission(environment, transport=ScriptedTransport())

    assert configured.authentication_mode == "vercel_oidc_request_scoped"
    assert configured.store.object_key == (
        "groundball/public-admission/v1/protected-preview/state.json"
    )

    for forbidden in (
        {"BLOB_READ_WRITE_TOKEN": "synthetic-static"},
        {
            "GROUNDBALL_BLOB_STORE_ID": f"store_{STORE_ID}",
            "GROUNDBALL_BLOB_TOKEN": "synthetic-static",
        },
        {"GROUNDBALL_BLOB_TOKEN": "synthetic-static"},
        {"VERCEL_OIDC_TOKEN": "not-a-jwt"},
    ):
        with pytest.raises(PublicAdmissionConfigurationError) as raised:
            load_blob_public_admission(
                {**environment, **forbidden},
                transport=ScriptedTransport(),
            )
        rendered = f"{raised.value!s} {raised.value!r}"
        assert "synthetic" not in rendered
        assert STARTUP_OIDC not in rendered


def test_protected_provider_runtime_cannot_start_against_a_proof_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_server,
        "_public_runtime_configuration",
        load_runtime_configuration(ROOT / "release/config/protected-preview-runtime.json"),
    )

    with pytest.raises(PublicAdmissionConfigurationError):
        api_server.configure_public_admission_from_environment(
            environment={
                "BLOB_STORE_ID": f"store_{STORE_ID}",
                "GROUNDBALL_BLOB_NAMESPACE": "proof",
                "GROUNDBALL_BLOB_PROOF_ID": "wave-7",
                "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
                "VERCEL_OIDC_TOKEN": STARTUP_OIDC,
            },
            transport=ScriptedTransport(),
        )


def test_static_token_mode_is_bounded_to_isolated_operator_proof() -> None:
    with pytest.raises(PublicAdmissionConfigurationError):
        load_blob_public_admission(
            {
                "GROUNDBALL_BLOB_NAMESPACE": "production",
                "GROUNDBALL_BLOB_STORE_ID": f"store_{STORE_ID}",
                "GROUNDBALL_BLOB_TOKEN": "synthetic-static-token",
                "GROUNDBALL_VISITOR_DIGEST_KEY": base64.urlsafe_b64encode(b"k" * 32).decode(),
            },
            transport=ScriptedTransport(),
        )


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
            "GROUNDBALL_BLOB_STORE_ID": f"store_{STORE_ID}",
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
        {"content-type": "application/json", "date": DATE, "etag": '"etag-1"'},
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
                {"content-type": "application/json", "date": DATE, "etag": '"etag"'},
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
            store_id=STORE_ID,
            proof_id="../production",
        )
