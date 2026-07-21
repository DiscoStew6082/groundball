"""Committed provider-neutral container contract proof."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from baseball_rag.public_release_config import canonical_json_bytes
from baseball_rag.release_container_probe import validate_release_container_proof

ROOT = Path(__file__).resolve().parents[1]
PROOF = ROOT / "release/proof/release-container-proof.json"


def test_committed_container_contract_proof_is_canonical_and_identity_free() -> None:
    checked = validate_release_container_proof(PROOF.read_bytes())

    assert checked["status"] == "pass"
    assert checked["runtime_configuration"]["network_policy"] == "none"
    assert checked["interface"]["public_interface_revision"] == ("ground-ball-public-interface-v1")
    assert not ({"source_commit", "artifact_commit", "release_bundle_digest"} & set(checked))


@pytest.mark.parametrize("field", ["status", "runtime_configuration", "interface"])
def test_container_contract_proof_rejects_semantic_drift(field: str) -> None:
    value = copy.deepcopy(validate_release_container_proof(PROOF.read_bytes()))
    value[field] = "foreign"

    with pytest.raises(ValueError, match="container proof"):
        validate_release_container_proof(canonical_json_bytes(value))
