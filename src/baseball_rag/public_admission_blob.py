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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from threading import Lock
from typing import Mapping, Protocol
from urllib.parse import urlparse

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

PRODUCTION_OBJECT_KEY = "groundball/public-admission/v1/production/state.json"
_PROOF_OBJECT_PREFIX = "groundball/public-admission/v1/proof"
_UPLOAD_API_ORIGIN = "https://blob.vercel-storage.com"
_PROOF_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_MAX_WRITE_RESPONSE_BYTES = 4096


class PublicAdmissionConfigurationError(ValueError):
    """Sanitized fail-closed public admission configuration error."""

    def __init__(self) -> None:
        super().__init__("Public admission configuration is invalid.")


class BlobProviderError(RuntimeError):
    """Sanitized Vercel Blob transport or response failure."""

    def __init__(self) -> None:
        super().__init__("Blob coordination request failed.")


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
    state_url: str
    token: str = field(repr=False)
    timeout_seconds: float = 5.0

    @classmethod
    def proof(
        cls,
        *,
        token: str,
        state_origin: str,
        proof_id: str,
    ) -> BlobCoordinationConfig:
        if not isinstance(proof_id, str) or _PROOF_ID_PATTERN.fullmatch(proof_id) is None:
            raise ValueError("Blob proof identifier is invalid.")
        object_key = f"{_PROOF_OBJECT_PREFIX}/{proof_id}/state.json"
        return cls._validated(token=token, state_origin=state_origin, object_key=object_key)

    @classmethod
    def production(
        cls,
        *,
        token: str,
        state_origin: str,
    ) -> BlobCoordinationConfig:
        return cls._validated(
            token=token,
            state_origin=state_origin,
            object_key=PRODUCTION_OBJECT_KEY,
        )

    @classmethod
    def _validated(
        cls,
        *,
        token: str,
        state_origin: str,
        object_key: str,
    ) -> BlobCoordinationConfig:
        if not isinstance(token, str) or not token or any(char.isspace() for char in token):
            raise ValueError("Blob credential configuration is invalid.")
        parsed = urlparse(state_origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not parsed.hostname.endswith(".blob.vercel-storage.com")
            or parsed.path not in {"", "/"}
            or parsed.params
            or parsed.query
            or parsed.fragment
            or parsed.username
            or parsed.password
        ):
            raise ValueError("Blob state origin configuration is invalid.")
        origin = state_origin.rstrip("/")
        return cls(
            object_key=object_key,
            state_url=f"{origin}/{object_key}",
            token=token,
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
    digest_key: bytes = field(repr=False)


def load_blob_public_admission(
    environment: Mapping[str, str],
    *,
    transport: HttpTransport | None = None,
) -> ConfiguredPublicAdmission:
    """Build strict shared coordination from explicit environment configuration."""
    try:
        namespace = environment["GROUNDBALL_BLOB_NAMESPACE"]
        token = environment["GROUNDBALL_BLOB_TOKEN"]
        state_origin = environment["GROUNDBALL_BLOB_STATE_ORIGIN"]
        encoded_digest_key = environment["GROUNDBALL_VISITOR_DIGEST_KEY"]
        proof_id = environment.get("GROUNDBALL_BLOB_PROOF_ID")
        if namespace == "proof":
            if proof_id is None:
                raise ValueError
            config = BlobCoordinationConfig.proof(
                token=token,
                state_origin=state_origin,
                proof_id=proof_id,
            )
        elif namespace == "production":
            if proof_id is not None:
                raise ValueError
            config = BlobCoordinationConfig.production(
                token=token,
                state_origin=state_origin,
            )
        else:
            raise ValueError
        digest_key = base64.b64decode(
            encoded_digest_key.encode("ascii"),
            altchars=b"-_",
            validate=True,
        )
        if len(digest_key) < 32:
            raise ValueError
    except (KeyError, ValueError, UnicodeEncodeError, binascii.Error):
        raise PublicAdmissionConfigurationError from None
    return ConfiguredPublicAdmission(
        store=BlobCoordinationStore(config, transport=transport),
        digest_key=digest_key,
    )


class BlobCoordinationStore(CasStore):
    """One-object private, uncached Vercel Blob compare-and-swap store."""

    def __init__(
        self,
        config: BlobCoordinationConfig,
        *,
        transport: HttpTransport | None = None,
    ) -> None:
        self._config = config
        self._transport = transport or RequestsHttpTransport()
        self._counts = OperationCounts()
        self._counts_lock = Lock()

    @property
    def deployment_shared(self) -> bool:
        return True

    @property
    def object_key(self) -> str:
        return self._config.object_key

    def operation_counts(self) -> OperationCounts:
        with self._counts_lock:
            return self._counts

    def read(self) -> CasSnapshot:
        self._increment("attempted_reads")
        try:
            response = self._transport.request(
                method="GET",
                url=self._config.state_url,
                headers={
                    "accept": "application/json",
                    "authorization": f"Bearer {self._config.token}",
                    "cache-control": "no-cache",
                    "x-vercel-blob-access": "private",
                    "x-vercel-blob-cache-control-max-age": "0",
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
        headers = {
            "authorization": f"Bearer {self._config.token}",
            "content-type": "application/json",
            "x-add-random-suffix": "0",
            "x-allow-overwrite": "0" if create else "1",
            "x-content-type": "application/json",
            "x-vercel-blob-access": "private",
        }
        if not create:
            assert blob_version.etag is not None
            headers["x-if-match"] = blob_version.etag
        try:
            response = self._transport.request(
                method="PUT",
                url=f"{_UPLOAD_API_ORIGIN}/{self._config.object_key}",
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


def _header(headers: Mapping[str, str], name: str) -> str:
    for key, value in headers.items():
        if key.lower() == name:
            return value
    raise BlobProviderError


def _trusted_date(headers: Mapping[str, str]) -> datetime:
    raw_date = _header(headers, "date")
    try:
        parsed = parsedate_to_datetime(raw_date)
    except (TypeError, ValueError) as exc:
        raise BlobProviderError from exc
    if parsed.utcoffset() is None:
        raise BlobProviderError
    return parsed.astimezone(UTC).replace(microsecond=0)


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
