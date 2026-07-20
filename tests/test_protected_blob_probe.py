from __future__ import annotations

import base64
import re

import pytest

from baseball_rag.protected_blob_probe import (
    BlobProbeError,
    _write_raw_missing,
    main,
    run_live_blob_probe,
)
from baseball_rag.public_admission_blob import HttpResponse, load_blob_public_admission


def _identity() -> dict[str, object]:
    return {
        "admission_policy_digest": "1" * 64,
        "artifact_commit": "2" * 40,
        "bundle_digest": "3" * 64,
        "deployment_id": "dpl_wave7proof",
        "provider_image_digest": "sha256:" + "4" * 64,
        "runtime_configuration_digest": "5" * 64,
        "source_commit": "6" * 40,
    }


class NoNetworkTransport:
    def request(self, **kwargs: object):
        raise AssertionError(f"offline test attempted provider contact: {sorted(kwargs)}")


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
                "dpl_wave7proof",
                "--provider-image-digest",
                "sha256:" + "4" * 64,
                "--output",
                str(tmp_path / "blob.json"),
            ]
        )

    assert raised.value.code == 2
    assert not (tmp_path / "blob.json").exists()
