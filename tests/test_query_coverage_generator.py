from baseball_rag.query.generate_coverage_report import (
    _outcome_gate,
    _plan_safety_gate,
    _promoted_gate,
)


def test_plan_safety_obligations_are_executed_assertions():
    gate = _plan_safety_gate()

    assert [item["identity"] for item in gate["obligations"]] == gate["asserted_obligations"]


def test_evidence_obligations_are_field_assertions_on_a_real_query_run():
    gate = _outcome_gate()

    evidence = [
        item["identity"] for item in gate["obligations"] if item["identity"].startswith("evidence:")
    ]
    assert evidence == gate["asserted_evidence"]
    assert "outcome:ExecutionFailed" in {item["identity"] for item in gate["obligations"]}


def test_promoted_obligations_only_count_exercised_public_operations():
    gate = _promoted_gate()
    identities = [item["identity"] for item in gate["obligations"]]

    assert not any(identity.startswith("internal-dependency:") for identity in identities)
    assert not any(identity.startswith("rollup:") for identity in identities)
    assert not any(identity.startswith("grouping:") for identity in identities)
    assert any(":group" in identity for identity in identities)
    assert gate["relationship_directions"] == gate["relationships_observed_in_plans"]
    assert len(gate["relationship_reverse_rejections"]) == len(gate["relationship_directions"])
    assert [
        identity
        for identity in identities
        if identity.startswith(("rollup-allowed:", "rollup-forbidden:"))
    ] == gate["rollup_assertions"]
