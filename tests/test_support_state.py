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
