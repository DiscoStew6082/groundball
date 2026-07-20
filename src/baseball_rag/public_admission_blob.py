"""Vercel Blob Adapter for shared public admission coordination.

This module owns a narrow raw-HTTP contract because the current public Python
SDK does not expose the conditional-write precondition required by this policy.
Real-service compatibility remains a separately approved protected proof.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from typing import Mapping, Protocol
from urllib.parse import quote
from uuid import uuid4

import requests

from baseball_rag.public_admission import (
    AdmissionState,
    CasSnapshot,
    CasStore,
    CasVersion,
)
from baseball_rag.public_admission_state import (
    MAX_STATE_BYTES,
    decode_admission_state,
    encode_admission_state,
)
from baseball_rag.public_release_config import MINIMUM_VISITOR_DIGEST_KEY_BYTES

PRODUCTION_OBJECT_KEY = "groundball/public-admission/v1/production/state.json"
PROTECTED_PREVIEW_OBJECT_KEY = "groundball/public-admission/v1/protected-preview/state.json"
_PROOF_OBJECT_PREFIX = "groundball/public-admission/v1/proof"
_UPLOAD_API_ORIGIN = "https://vercel.com/api/blob/"
_PROOF_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_STORE_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,63}$")
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9]{1,63}:\d{13}:[0-9a-f]+$")
_OIDC_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$")
_MAX_OIDC_TOKEN_CHARACTERS = 8192
_NO_REQUEST = object()
_INVALID_REQUEST_CREDENTIAL = object()
_request_oidc_token: ContextVar[str | object] = ContextVar(
    "groundball_request_oidc_token",
    default=_NO_REQUEST,
)
_IMF_FIXDATE_PATTERN = re.compile(
    r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun), (\d{2}) "
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) "
    r"([1-9]\d{3}) (\d{2}):(\d{2}):(\d{2}) GMT$"
)
_IMF_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_IMF_MONTHS = {
    month: index
    for index, month in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
        start=1,
    )
}
_MAX_WRITE_RESPONSE_BYTES = 4096


class PublicAdmissionConfigurationError(ValueError):
    """Sanitized fail-closed public admission configuration error."""

    def __init__(self) -> None:
        super().__init__("Public admission configuration is invalid.")


class BlobProviderError(RuntimeError):
    """Sanitized Vercel Blob transport or response failure."""

    def __init__(self) -> None:
        super().__init__("Blob coordination request failed.")


class BlobCredentialProvider(Protocol):
    """Resolve one credential immediately before a provider operation."""

    def resolve(self) -> str: ...


class OidcBlobCredentialProvider:
    """Request-scoped OIDC with a startup-only environment fallback."""

    def __init__(self, *, startup_token: str) -> None:
        if not _valid_oidc_token(startup_token):
            raise ValueError("Blob OIDC credential configuration is invalid.")
        self._startup_token = startup_token

    def resolve(self) -> str:
        request_token = _request_oidc_token.get()
        if request_token is _NO_REQUEST:
            return self._startup_token
        if isinstance(request_token, str):
            return request_token
        raise BlobProviderError


class StaticBlobCredentialProvider:
    """Long-lived credential restricted by configuration loading to proof scope."""

    def __init__(self, token: str) -> None:
        if not _valid_static_token(token):
            raise ValueError("Blob static credential configuration is invalid.")
        self._token = token

    def resolve(self) -> str:
        return self._token


@contextmanager
def request_oidc_token_context(raw_token: str | None) -> Iterator[None]:
    """Bind one validated incoming Vercel OIDC header to the current request."""
    value: str | object = raw_token if _valid_oidc_token(raw_token) else _INVALID_REQUEST_CREDENTIAL
    context_token: Token[str | object] = _request_oidc_token.set(value)
    try:
        yield
    finally:
        _request_oidc_token.reset(context_token)


def _valid_oidc_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= _MAX_OIDC_TOKEN_CHARACTERS
        and _OIDC_TOKEN_PATTERN.fullmatch(value) is not None
    )


def _valid_static_token(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= _MAX_OIDC_TOKEN_CHARACTERS
        and value.strip() == value
        and not any(char.isspace() or ord(char) < 33 or ord(char) == 127 for char in value)
    )


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        data: bytes | None,
        timeout: float,
        max_response_bytes: int,
    ) -> HttpResponse: ...


class RequestsHttpTransport:
    """Bounded requests transport with no provider-body logging."""

    def __init__(self, session: requests.Session | None = None) -> None:
        self._session = session or requests.Session()

    def request(
        self,
        *,
        method: str,
        url: str,
        headers: dict[str, str],
        data: bytes | None,
        timeout: float,
        max_response_bytes: int,
    ) -> HttpResponse:
        try:
            response = self._session.request(
                method,
                url,
                headers=headers,
                data=data,
                timeout=timeout,
                stream=True,
                allow_redirects=False,
            )
            try:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > max_response_bytes:
                        raise BlobProviderError
                return HttpResponse(
                    status_code=response.status_code,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    body=bytes(body),
                )
            finally:
                response.close()
        except BlobProviderError:
            raise
        except requests.RequestException:
            raise BlobProviderError from None


@dataclass(frozen=True)
class BlobCoordinationConfig:
    """Validated private object location and credential-free namespace shape."""

    object_key: str
    store_id: str
    timeout_seconds: float = 5.0
    state_url: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.store_id, str):
            raise ValueError("Blob store identifier is invalid.")
        bare_store_id = self.store_id.removeprefix("store_")
        if _STORE_ID_PATTERN.fullmatch(bare_store_id) is None:
            raise ValueError("Blob store identifier is invalid.")
        proof_key_prefix = f"{_PROOF_OBJECT_PREFIX}/"
        proof_key_suffix = "/state.json"
        proof_id = self.object_key.removeprefix(proof_key_prefix).removesuffix(proof_key_suffix)
        valid_proof_key = (
            self.object_key.startswith(proof_key_prefix)
            and self.object_key.endswith(proof_key_suffix)
            and _PROOF_ID_PATTERN.fullmatch(proof_id) is not None
        )
        if (
            self.object_key
            not in {
                PRODUCTION_OBJECT_KEY,
                PROTECTED_PREVIEW_OBJECT_KEY,
            }
            and not valid_proof_key
        ):
            raise ValueError("Blob object key is invalid.")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not 0 < self.timeout_seconds <= 30
        ):
            raise ValueError("Blob timeout configuration is invalid.")
        state_origin = f"https://{bare_store_id}.private.blob.vercel-storage.com"
        object.__setattr__(self, "store_id", bare_store_id)
        object.__setattr__(self, "state_url", f"{state_origin}/{self.object_key}")

    @classmethod
    def proof(
        cls,
        *,
        store_id: str,
        proof_id: str,
    ) -> BlobCoordinationConfig:
        if not isinstance(proof_id, str) or _PROOF_ID_PATTERN.fullmatch(proof_id) is None:
            raise ValueError("Blob proof identifier is invalid.")
        return cls(
            store_id=store_id,
            object_key=f"{_PROOF_OBJECT_PREFIX}/{proof_id}/state.json",
        )

    @classmethod
    def production(
        cls,
        *,
        store_id: str,
    ) -> BlobCoordinationConfig:
        return cls(
            store_id=store_id,
            object_key=PRODUCTION_OBJECT_KEY,
        )

    @classmethod
    def protected_preview(cls, *, store_id: str) -> BlobCoordinationConfig:
        return cls(
            store_id=store_id,
            object_key=PROTECTED_PREVIEW_OBJECT_KEY,
        )


@dataclass(frozen=True)
class _BlobVersion:
    etag: str | None


@dataclass(frozen=True)
class OperationCounts:
    attempted_reads: int = 0
    successful_reads: int = 0
    missing_reads: int = 0
    failed_reads: int = 0
    attempted_conditional_writes: int = 0
    successful_conditional_writes: int = 0
    conditional_conflicts: int = 0
    failed_conditional_writes: int = 0
    attempted_create_if_absent: int = 0
    successful_create_if_absent: int = 0
    create_conflicts: int = 0
    failed_create_if_absent: int = 0

    def as_dict(self) -> dict[str, int]:
        """Return local attempts by operation class, not provider billing units."""
        return {
            "attempted_reads": self.attempted_reads,
            "successful_reads": self.successful_reads,
            "missing_reads": self.missing_reads,
            "failed_reads": self.failed_reads,
            "attempted_conditional_writes": self.attempted_conditional_writes,
            "successful_conditional_writes": self.successful_conditional_writes,
            "conditional_conflicts": self.conditional_conflicts,
            "failed_conditional_writes": self.failed_conditional_writes,
            "attempted_create_if_absent": self.attempted_create_if_absent,
            "successful_create_if_absent": self.successful_create_if_absent,
            "create_conflicts": self.create_conflicts,
            "failed_create_if_absent": self.failed_create_if_absent,
        }


@dataclass(frozen=True)
class ConfiguredPublicAdmission:
    store: BlobCoordinationStore
    authentication_mode: str
    digest_key: bytes = field(repr=False)


def load_blob_public_admission(
    environment: Mapping[str, str],
    *,
    transport: HttpTransport | None = None,
) -> ConfiguredPublicAdmission:
    """Build strict shared coordination from explicit environment configuration."""
    try:
        namespace = environment["GROUNDBALL_BLOB_NAMESPACE"]
        encoded_digest_key = environment["GROUNDBALL_VISITOR_DIGEST_KEY"]
        static_keys = {"GROUNDBALL_BLOB_STORE_ID", "GROUNDBALL_BLOB_TOKEN"}
        oidc_keys = {"BLOB_STORE_ID", "VERCEL_OIDC_TOKEN"}
        supplied_static = {key for key in static_keys if key in environment}
        supplied_oidc = {key for key in oidc_keys if key in environment}
        if "BLOB_READ_WRITE_TOKEN" in environment:
            raise ValueError
        credential_provider: BlobCredentialProvider
        if supplied_static == static_keys and not supplied_oidc and namespace == "proof":
            store_id = environment["GROUNDBALL_BLOB_STORE_ID"]
            credential_provider = StaticBlobCredentialProvider(environment["GROUNDBALL_BLOB_TOKEN"])
            authentication_mode = "groundball_static_token"
        elif supplied_oidc == oidc_keys and not supplied_static:
            store_id = environment["BLOB_STORE_ID"]
            credential_provider = OidcBlobCredentialProvider(
                startup_token=environment["VERCEL_OIDC_TOKEN"]
            )
            authentication_mode = "vercel_oidc_request_scoped"
        else:
            raise ValueError
        proof_id = environment.get("GROUNDBALL_BLOB_PROOF_ID")
        if namespace == "proof":
            if proof_id is None:
                raise ValueError
            config = BlobCoordinationConfig.proof(
                store_id=store_id,
                proof_id=proof_id,
            )
        elif namespace == "protected_preview":
            if proof_id is not None or authentication_mode != "vercel_oidc_request_scoped":
                raise ValueError
            config = BlobCoordinationConfig.protected_preview(store_id=store_id)
        elif namespace == "production":
            if proof_id is not None or authentication_mode != "vercel_oidc_request_scoped":
                raise ValueError
            config = BlobCoordinationConfig.production(store_id=store_id)
        else:
            raise ValueError
        digest_key = base64.b64decode(
            encoded_digest_key.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        if len(digest_key) < MINIMUM_VISITOR_DIGEST_KEY_BYTES:
            raise ValueError
    except (KeyError, ValueError, UnicodeEncodeError, binascii.Error):
        raise PublicAdmissionConfigurationError from None
    return ConfiguredPublicAdmission(
        store=BlobCoordinationStore(
            config,
            credential_provider=credential_provider,
            transport=transport,
        ),
        authentication_mode=authentication_mode,
        digest_key=digest_key,
    )


class BlobCoordinationStore(CasStore):
    """One-object private, uncached Vercel Blob compare-and-swap store."""

    def __init__(
        self,
        config: BlobCoordinationConfig,
        *,
        credential_provider: BlobCredentialProvider,
        transport: HttpTransport | None = None,
        request_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._credential_provider = credential_provider
        self._transport = transport or RequestsHttpTransport()
        self._request_id_factory = request_id_factory or (
            lambda: new_blob_request_id(self._config.store_id)
        )
        self._counts = OperationCounts()
        self._counts_lock = Lock()

    @property
    def deployment_shared(self) -> bool:
        return True

    @property
    def object_key(self) -> str:
        return self._config.object_key

    @property
    def state_url(self) -> str:
        return self._config.state_url

    @property
    def store_id(self) -> str:
        return self._config.store_id

    def operation_counts(self) -> OperationCounts:
        with self._counts_lock:
            return self._counts

    def read(self) -> CasSnapshot:
        self._increment("attempted_reads")
        try:
            credential = self._credential_provider.resolve()
            response = self._transport.request(
                method="GET",
                url=f"{self._config.state_url}?cache=0",
                headers={
                    "accept": "application/json",
                    "authorization": f"Bearer {credential}",
                },
                data=None,
                timeout=self._config.timeout_seconds,
                max_response_bytes=MAX_STATE_BYTES,
            )
            observed_at = _trusted_date(response.headers)
            if response.status_code == 404:
                self._increment("missing_reads")
                return CasSnapshot(
                    state=AdmissionState(),
                    version=CasVersion(_BlobVersion(None)),
                    observed_at=observed_at,
                    exists=False,
                )
            if response.status_code != 200:
                raise BlobProviderError
            content_type = _header(response.headers, "content-type")
            if content_type.split(";", 1)[0].strip().lower() != "application/json":
                raise BlobProviderError
            etag = _opaque_etag(response.headers)
            state = decode_admission_state(response.body)
            self._increment("successful_reads")
            return CasSnapshot(
                state=state,
                version=CasVersion(_BlobVersion(etag)),
                observed_at=observed_at,
            )
        except Exception:
            self._increment("failed_reads")
            raise

    def compare_and_swap(self, version: CasVersion, state: AdmissionState) -> bool:
        blob_version = version._token
        if not isinstance(blob_version, _BlobVersion):
            raise BlobProviderError
        create = blob_version.etag is None
        attempted_field = "attempted_create_if_absent" if create else "attempted_conditional_writes"
        self._increment(attempted_field)
        try:
            try:
                request_id = self._request_id_factory()
            except Exception:
                raise BlobProviderError from None
            if not isinstance(request_id, str) or _REQUEST_ID_PATTERN.fullmatch(request_id) is None:
                raise BlobProviderError
            credential = self._credential_provider.resolve()
            headers = {
                "authorization": f"Bearer {credential}",
                "content-type": "application/json",
                "x-add-random-suffix": "0",
                "x-allow-overwrite": "0" if create else "1",
                "x-api-blob-request-attempt": "0",
                "x-api-blob-request-id": request_id,
                "x-api-version": "12",
                "x-content-type": "application/json",
                "x-vercel-blob-access": "private",
                "x-vercel-blob-store-id": self._config.store_id,
            }
            if not create:
                assert blob_version.etag is not None
                headers["x-if-match"] = blob_version.etag
            response = self._transport.request(
                method="PUT",
                url=blob_upload_url(self._config.object_key),
                headers=headers,
                data=encode_admission_state(state),
                timeout=self._config.timeout_seconds,
                max_response_bytes=_MAX_WRITE_RESPONSE_BYTES,
            )
            if response.status_code == 412:
                self._increment("create_conflicts" if create else "conditional_conflicts")
                return False
            if response.status_code not in {200, 201}:
                raise BlobProviderError
            _validate_write_response(response.body, self._config)
            self._increment(
                "successful_create_if_absent" if create else "successful_conditional_writes"
            )
            return True
        except Exception:
            self._increment("failed_create_if_absent" if create else "failed_conditional_writes")
            raise

    def _increment(self, field_name: str) -> None:
        with self._counts_lock:
            values = self._counts.__dict__.copy()
            values[field_name] += 1
            self._counts = OperationCounts(**values)


def blob_upload_url(object_key: str) -> str:
    """Return the pinned v12 upload endpoint without credentials in the query."""
    return f"{_UPLOAD_API_ORIGIN}?pathname={quote(object_key, safe='')}"


def new_blob_request_id(store_id: str) -> str:
    """Return the current first-party store:milliseconds:hex request ID shape."""
    return f"{store_id}:{int(time.time() * 1000)}:{uuid4().hex}"


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    raise BlobProviderError


def _trusted_date(headers: Mapping[str, str]) -> datetime:
    raw_date = _header(headers, "date")
    try:
        matched = _IMF_FIXDATE_PATTERN.fullmatch(raw_date)
    except TypeError as exc:
        raise BlobProviderError from exc
    if matched is None:
        raise BlobProviderError
    weekday, day, month, year, hour, minute, second = matched.groups()
    try:
        parsed = datetime(
            int(year),
            _IMF_MONTHS[month],
            int(day),
            int(hour),
            int(minute),
            int(second),
            tzinfo=UTC,
        )
    except (KeyError, ValueError) as exc:
        raise BlobProviderError from exc
    if _IMF_WEEKDAYS[parsed.weekday()] != weekday:
        raise BlobProviderError
    return parsed


def _opaque_etag(headers: Mapping[str, str]) -> str:
    etag = _header(headers, "etag")
    if not etag or len(etag) > 1024 or etag.strip() != etag:
        raise BlobProviderError
    if any(ord(char) < 32 or ord(char) == 127 for char in etag):
        raise BlobProviderError
    return etag


def _validate_write_response(payload: bytes, config: BlobCoordinationConfig) -> None:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BlobProviderError from exc
    if not isinstance(document, dict):
        raise BlobProviderError
    if document.get("url") != config.state_url or document.get("pathname") != config.object_key:
        raise BlobProviderError
