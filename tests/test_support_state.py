from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.support_state import answer_support_state


def test_support_state_exposes_unsupported_review_and_audit_reason():
    answer = StructuredAnswer(
        answer="Multiple matching players were found.",
        intent="player_biography",
        sources=[
            SourceRecord(
                type="duckdb",
                label="Unsupported template",
                rows=[{"unsupported_reason": "old row reason"}],
            )
        ],
        warnings=["old warning reason"],
        unsupported=True,
        unsupported_reason="ambiguous",
        review_reason="ambiguous",
    )

    state = answer_support_state(answer)

    assert state.unsupported_reason == "ambiguous"
    assert state.review_reason == "ambiguous"
    assert state.audit_reason == "ambiguous"
    assert state.reviewable is True


def test_support_state_regression_for_governance_reviewability():
    cases = [
        (
            StructuredAnswer(
                answer="ambiguous",
                intent="player_biography",
                unsupported=True,
                unsupported_reason="ambiguous",
                review_reason="ambiguous",
            ),
            "ambiguous",
            "ambiguous",
        ),
        (
            StructuredAnswer(
                answer="no data",
                intent="player_biography",
                unsupported=True,
                unsupported_reason="no_data",
            ),
            "no_data",
            "unsupported",
        ),
        (
            StructuredAnswer(
                answer="unsupported",
                intent="stat_query",
                unsupported=True,
                unsupported_reason="unsupported",
            ),
            "unsupported",
            "unsupported",
        ),
        (
            StructuredAnswer(
                answer="llm unavailable",
                intent="general_explanation",
                unsupported=True,
                unsupported_reason="llm_unavailable",
            ),
            "llm_unavailable",
            "unsupported",
        ),
    ]

    for answer, audit_reason, review_reason in cases:
        state = answer_support_state(answer)

        assert state.audit_reason == audit_reason
        assert state.review_reason == review_reason
        assert state.reviewable is True
