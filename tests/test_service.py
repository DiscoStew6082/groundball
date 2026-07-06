import pytest

from baseball_rag.generation.llm import LLMResponse, LLMUnavailableError
from baseball_rag.llm_narration_guard import apply_llm_flavored_narration
from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.service import answer


def test_answer_surfaces_stats_only_answer_mode_metadata():
    result = answer("who had the most RBIs in 1962", answer_mode="stats_only")

    assert result.metadata["answer_mode"] == "stats_only"


def test_answer_rejects_unknown_answer_mode_before_dispatch():
    with pytest.raises(ValueError, match="Unsupported answer_mode"):
        answer(
            "who had the most RBIs in 1962",
            answer_mode="box_score_poetry",  # type: ignore[arg-type]
        )


def test_llm_flavored_stat_query_uses_verified_stats(monkeypatch):
    seen_prompts = []

    def fake_llm(prompt, **_kwargs):
        seen_prompts.append(prompt)
        return LLMResponse(
            content="Tommy Davis led MLB with 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert result.answer == "Tommy Davis led MLB with 153 RBI in 1962."
    assert result.metadata["answer_mode"] == "llm_flavored"
    assert result.sources[0].type == "duckdb"
    assert "Davis, Tommy" in str(seen_prompts[0])
    assert "153" in str(seen_prompts[0])


def test_llm_flavored_stat_query_uses_source_evidence_not_rendered_stat_text(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)
    result = StructuredAnswer(
        answer="Top result: Davis, Tommy had 153 in 1962.",
        intent="stat_query",
        sources=[
            SourceRecord(
                type="duckdb",
                label="RBI leaderboard for 1962-1962",
                rows=[{"name": "Davis, Tommy", "team": "LAN", "stat_value": 153, "year": 1962}],
            )
        ],
    )

    flavored = apply_llm_flavored_narration(
        "who had the most RBIs in 1962",
        result,
    )

    assert flavored.answer == "Tommy Davis led MLB with 153 RBI in 1962."


def test_llm_flavored_stat_value_rejects_ambiguous_source_stat(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153 home runs in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)
    result = StructuredAnswer(
        answer="Top result: Davis, Tommy had 153 in 1962.",
        intent="stat_query",
        sources=[
            SourceRecord(
                type="duckdb",
                label="Leaderboard for 1962-1962",
                detail="Available columns mention home runs, RBI, and AVG.",
                rows=[{"name": "Davis, Tommy", "team": "LAN", "stat_value": 153, "year": 1962}],
            )
        ],
    )

    flavored = apply_llm_flavored_narration(
        "who had the most RBIs in 1962",
        result,
    )

    assert "153 home runs" not in flavored.answer
    assert "unverified numbers" not in flavored.answer


def test_llm_flavored_stat_query_rejects_unverified_numbers(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153 RBI in 1962 and also hit 300 home runs.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "300 home runs" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_reused_number_wrong_stat(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153 home runs in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "153 home runs" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_spelled_out_numeric_claims(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with one hundred fifty three RBI.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "one hundred fifty three RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_unit_before_reused_number(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB in home runs with 153 in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "home runs with 153" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_stat_total_wrong_stat(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB; his home run total was 153 in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "home run total was 153" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_row_misattributed_claim(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Frank Robinson led MLB with 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Frank Robinson led MLB with 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_unitless_row_misattribution(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Frank Robinson led MLB with 153 in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Frank Robinson led MLB with 153" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_unknown_name_stat_claim(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Mickey Mantle led MLB with 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Mickey Mantle led MLB with 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_unknown_single_name_stat_claim(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Mantle led MLB with 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Mantle led MLB with 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_same_surname_wrong_player(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Jackie Robinson had 136 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Jackie Robinson had 136 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_last_name_misattributed_claim(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Robinson led MLB with 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Robinson led MLB with 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_non_numeric_wrong_player_claim(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Frank Robinson led MLB that season.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Frank Robinson led MLB" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_multi_name_non_leader_claim(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis, Willie Mays led MLB that season.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Tommy Davis, Willie Mays led MLB" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_bad_clause_after_good_clause(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153 RBI; Frank Robinson had 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Frank Robinson had 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_bad_clause_without_semicolon_space(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153 RBI;Mickey Mantle had 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Mickey Mantle had 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_bad_and_clause_after_good_clause(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content=("Tommy Davis led MLB with 153 RBI and Mickey Mantle had 153 RBI in 1962."),
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Mickey Mantle had 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_lowercase_bad_and_clause(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153 RBI and mickey mantle had 153 RBI in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "mickey mantle had 153 RBI" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_number_before_punctuated_wrong_stat(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB with 153-HR in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "153-HR" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_supported_stat_unit_swap(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Earl Webb led MLB with 67 triples in 1931.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most 2B in 1931", answer_mode="llm_flavored")

    assert "Webb, Earl: 67 2B" in result.answer
    assert "67 triples" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_does_not_verify_number_inside_stat_unit(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Earl Webb led MLB with 2 triples in 1931.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most 2B in 1931", answer_mode="llm_flavored")

    assert "Webb, Earl: 67 2B" in result.answer
    assert "2 triples" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_punctuated_unit_before_reused_number(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB in home runs, with 153 in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "home runs, with 153" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_rejects_spelled_unit_before_number(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB in home runs with one hundred fifty three.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "home runs with one hundred fifty three" not in result.answer
    assert "unverified numbers" not in result.answer


def test_llm_flavored_stat_query_accepts_verified_unit_before_number(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis led MLB in RBI with 153 in 1962.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert result.answer == "Tommy Davis led MLB in RBI with 153 in 1962."


def test_llm_flavored_stat_query_rejects_unverified_role_claim_with_verified_stat(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis was a pitcher in 1962 with 153 RBI.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Tommy Davis was a pitcher" not in result.answer
    assert result.warnings == []
    assert result.metadata["llm_narration"]["status"] == "verification_failed"


def test_llm_flavored_stat_query_rejects_unverified_role_verb_with_verified_stat(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis pitched in 1962 with 153 RBI.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Tommy Davis pitched" not in result.answer
    assert result.warnings == []
    assert result.metadata["llm_narration"]["status"] == "verification_failed"


def test_llm_flavored_stat_query_rejects_unverified_state_claim_with_verified_stat(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis was injured in 1962 with 153 RBI.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Tommy Davis was injured" not in result.answer
    assert result.warnings == []
    assert result.metadata["llm_narration"]["status"] == "verification_failed"


def test_llm_flavored_grounded_template_accepts_verified_stat_claims(monkeypatch):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Rogers Hornsby won in 1922 with 42 HR, 152 RBI, and a .401 AVG.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who won the Triple Crown and which years", answer_mode="llm_flavored")

    assert result.answer == ("Rogers Hornsby won in 1922 with 42 HR, 152 RBI, and a .401 AVG.")


def test_llm_flavored_grounded_template_accepts_live_style_triple_crown_list(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content=(
                "The following players won the Triple Crown in these years:\n\n"
                "*   **Nap Lajoie**: 1901 (AL)\n"
                "*   **Ty Cobb**: 1909 (AL)\n"
                "*   **Rogers Hornsby**: 1922 (NL) and 1925 (NL)\n"
                "*   **Ted Williams**: 1942 (AL) and 1947 (AL)\n"
                "*   **Miguel Cabrera**: 2012 (AL)"
            ),
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who won the Triple Crown and which years", answer_mode="llm_flavored")

    assert "The following players won the Triple Crown in these years" in result.answer
    assert "**Nap Lajoie**: 1901 (AL)" in result.answer
    assert "unverified numbers" not in result.answer
    assert result.metadata["llm_narration"]["status"] == "accepted"


def test_llm_flavored_grounded_template_accepts_common_generic_opener(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content=(
                "Here are the Triple Crown winners:\n\n"
                "* Nap Lajoie: 1901\n"
                "* Ty Cobb: 1909\n"
                "* Rogers Hornsby: 1922 and 1925"
            ),
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who won the Triple Crown and which years", answer_mode="llm_flavored")

    assert "Here are the Triple Crown winners" in result.answer
    assert "unverified numbers" not in result.answer
    assert result.metadata["llm_narration"]["status"] == "accepted"


def test_llm_flavored_grounded_template_rejects_cross_row_year_stat_claim(
    monkeypatch,
):
    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Rogers Hornsby won in 1942 with 42 HR, 152 RBI, and a .401 AVG.",
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who won the Triple Crown and which years", answer_mode="llm_flavored")

    assert "Rogers Hornsby won in 1942" not in result.answer
    assert "14 Triple Crown seasons matched:" in result.answer
    assert "Rogers Hornsby (NL, 1922): 42 HR, 152 RBI, .401 AVG" in result.answer
    assert "yearID:" not in result.answer
    assert "unverified numbers" not in result.answer
    assert "did not pass verification" not in result.answer
    assert result.warnings == []
    assert result.metadata["llm_narration"]["status"] == "verification_failed"
    assert "Gemma prose did not pass verification" in result.metadata["llm_narration"]["message"]


def test_llm_flavored_grounded_template_repairs_unverified_prose_with_verified_stats(
    monkeypatch,
):
    responses = iter(
        [
            "Rogers Hornsby won in 1942 with 42 HR, 152 RBI, and a .401 AVG.",
            "Rogers Hornsby won Triple Crown seasons in 1922 and 1925.",
        ]
    )

    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content=next(responses),
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who won the Triple Crown and which years", answer_mode="llm_flavored")

    assert result.answer == "Rogers Hornsby won Triple Crown seasons in 1922 and 1925."
    assert result.warnings == []
    assert result.metadata["llm_narration"]["status"] == "accepted_after_repair"


def test_llm_flavored_stat_query_rejects_repaired_name_only_prose_for_stat_answer(
    monkeypatch,
):
    responses = iter(
        [
            "Frank Robinson led MLB with 153 RBI in 1962.",
            "Tommy Davis was a pitcher in 1962 with 153 RBI.",
        ]
    )

    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content=next(responses),
            model="test-model",
            done=True,
        )

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "Tommy Davis was a pitcher" not in result.answer
    assert result.warnings == []
    assert result.metadata["llm_narration"]["status"] == "verification_failed"


def test_llm_flavored_grounded_name_only_result_rejects_unverified_name(
    monkeypatch,
):
    from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Mickey Mantle was listed on that roster.",
            model="test-model",
            done=True,
        )

    result = GroundedDatabaseResult(
        sql="SELECT name FROM people",
        rows=[("Davis, Tommy",), ("Mays, Willie",)],
        columns=["name"],
        row_count=2,
        truncated=False,
        source_label="LLM-backed typed grounded database query",
        source_detail="LLM extracted a typed intent.",
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)
    monkeypatch.setattr("baseball_rag.db.grounded_database_runtime.query", lambda *_, **__: result)

    answer_result = answer("who played for the Braves in 1936", answer_mode="llm_flavored")

    assert "Davis, Tommy" in answer_result.answer
    assert "Mickey Mantle" not in answer_result.answer
    assert "unverified numbers" not in answer_result.answer


def test_llm_flavored_grounded_name_only_result_accepts_verified_name_prose(
    monkeypatch,
):
    from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis was listed on that roster.",
            model="test-model",
            done=True,
        )

    result = GroundedDatabaseResult(
        sql="SELECT name FROM people",
        rows=[("Davis, Tommy",), ("Mays, Willie",)],
        columns=["name"],
        row_count=2,
        truncated=False,
        source_label="LLM-backed typed grounded database query",
        source_detail="LLM extracted a typed intent.",
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)
    monkeypatch.setattr("baseball_rag.db.grounded_database_runtime.query", lambda *_, **__: result)

    answer_result = answer("who played for the Braves in 1936", answer_mode="llm_flavored")

    assert answer_result.answer == "Tommy Davis was listed on that roster."


def test_llm_flavored_grounded_name_only_result_accepts_multiple_verified_names(
    monkeypatch,
):
    from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis, Willie Mays, and Hank Aaron were listed on that roster.",
            model="test-model",
            done=True,
        )

    result = GroundedDatabaseResult(
        sql="SELECT name FROM people",
        rows=[("Davis, Tommy",), ("Mays, Willie",), ("Aaron, Hank",)],
        columns=["name"],
        row_count=3,
        truncated=False,
        source_label="LLM-backed typed grounded database query",
        source_detail="LLM extracted a typed intent.",
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)
    monkeypatch.setattr("baseball_rag.db.grounded_database_runtime.query", lambda *_, **__: result)

    answer_result = answer("who played for the Braves in 1936", answer_mode="llm_flavored")

    assert answer_result.answer == (
        "Tommy Davis, Willie Mays, and Hank Aaron were listed on that roster."
    )


def test_llm_flavored_grounded_name_only_result_rejects_lowercase_unverified_name(
    monkeypatch,
):
    from baseball_rag.db.grounded_database_types import GroundedDatabaseResult

    def fake_llm(_prompt, **_kwargs):
        return LLMResponse(
            content="Tommy Davis and mickey mantle were listed on that roster.",
            model="test-model",
            done=True,
        )

    result = GroundedDatabaseResult(
        sql="SELECT name FROM people",
        rows=[("Davis, Tommy",)],
        columns=["name"],
        row_count=1,
        truncated=False,
        source_label="LLM-backed typed grounded database query",
        source_detail="LLM extracted a typed intent.",
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)
    monkeypatch.setattr("baseball_rag.db.grounded_database_runtime.query", lambda *_, **__: result)

    answer_result = answer("who played for the Braves in 1936", answer_mode="llm_flavored")

    assert "Davis, Tommy" in answer_result.answer
    assert "mickey mantle" not in answer_result.answer
    assert "unverified numbers" not in answer_result.answer


def test_llm_flavored_unsupported_answer_skips_final_narration(monkeypatch):
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("unsupported answers must not call final narration")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

    result = answer("who is in the 500 club", answer_mode="llm_flavored")

    assert result.unsupported is True
    assert result.unsupported_reason == "ambiguous"
    assert result.metadata["answer_mode"] == "llm_flavored"


def test_llm_flavored_returns_stats_when_llm_unavailable(monkeypatch):
    def unavailable_llm(_prompt, **_kwargs):
        raise LLMUnavailableError("local LLM unavailable")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", unavailable_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "LLM unavailable" not in result.answer
    assert result.warnings == []
    assert result.metadata["llm_narration"]["status"] == "unavailable"
    assert "Gemma prose is unavailable" in result.metadata["llm_narration"]["message"]
    assert result.metadata["answer_mode"] == "llm_flavored"
    assert result.sources[0].type == "duckdb"


def test_llm_flavored_returns_stats_when_connection_error_marks_llm_unavailable(
    monkeypatch,
):
    def unavailable_llm(_prompt, **_kwargs):
        raise ConnectionError("socket closed")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", unavailable_llm)

    result = answer("who had the most RBIs in 1962", answer_mode="llm_flavored")

    assert "Davis, Tommy: 153 RBI" in result.answer
    assert "LLM unavailable" not in result.answer
    assert result.metadata["answer_mode"] == "llm_flavored"
    assert result.sources[0].type == "duckdb"
