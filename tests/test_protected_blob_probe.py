from __future__ import annotations

import base64

import pytest

from baseball_rag.protected_blob_probe import BlobProbeError, main, run_live_blob_probe


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
