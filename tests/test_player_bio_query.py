"""Player biography and open explanation behavior."""

from __future__ import annotations

import importlib.util

from baseball_rag.generation.llm import LLMResponse
from baseball_rag.routing import GeneralExplanationCase, PlayerBiographyCase
from baseball_rag.service import answer


def _llm_json(answer_text: str, claims: list[dict] | None = None) -> LLMResponse:
    import json

    return LLMResponse(
        content=json.dumps({"answer": answer_text, "stat_claims": claims or []}),
        model="test-model",
        done=True,
    )


def test_llm_biography_with_no_stat_claims_returns_normally(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question="who was Babe Ruth",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json("Babe Ruth was a two-way star."),
    )

    result = answer("who was Babe Ruth")

    assert result.intent == "player_biography"
    assert result.answer == "Babe Ruth was a two-way star."
    assert result.warnings == []
    assert result.sources[0].type == "duckdb"
    assert result.metadata["stat_claims"] == []


def test_llm_biography_with_verified_career_stat_claim_adds_duckdb_provenance(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question="who was Babe Ruth",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json(
            "Babe Ruth hit 714 career home runs.",
            [{"stat": "HR", "value": 714, "scope": "career", "text": "714 career home runs"}],
        ),
    )

    result = answer("who was Babe Ruth")

    assert result.warnings == []
    assert (
        "Stat claim verification: total claims 1, valid claims 1, invalid claims 0. "
        "Score: passing (1/1 verified)."
    ) in result.answer
    assert result.sources[0].type == "duckdb"
    assert result.sources[0].rows[0]["status"] == "verified"
    assert result.sources[0].rows[0]["actual_value"] == 714
    assert result.metadata["stat_claims"][0]["status"] == "verified"


def test_llm_biography_with_verified_season_stat_claim_passes(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question="who was Babe Ruth",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json(
            "Babe Ruth hit 60 home runs in 1927.",
            [{"stat": "HR", "value": 60, "year": 1927, "text": "60 home runs in 1927"}],
        ),
    )

    result = answer("who was Babe Ruth")

    assert result.warnings == []
    assert (
        "Stat claim verification: total claims 1, valid claims 1, invalid claims 0. "
        "Score: passing (1/1 verified)."
    ) in result.answer
    assert result.sources[0].rows[0]["status"] == "verified"
    assert result.sources[0].rows[0]["year"] == 1927


def test_llm_biography_verifies_pitching_strikeout_claim(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Nolan Ryan",
            raw_question="who was Nolan Ryan",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json(
            "Nolan Ryan struck out 5,714 batters in his career.",
            [
                {
                    "stat": "SO",
                    "value": 5714,
                    "scope": "career",
                    "text": "struck out 5,714 batters",
                }
            ],
        ),
    )

    result = answer("who was Nolan Ryan")

    assert result.warnings == []
    assert result.sources[0].rows[0]["status"] == "verified"
    assert result.sources[0].rows[0]["actual_value"] == 5714
    assert result.sources[0].rows[0]["table"] == "pitching"


def test_llm_biography_uses_final_contract_after_planning_json(monkeypatch):
    """Biography parsing should ignore planning snippets and use the final contract."""
    content = "\n".join(
        [
            "* Subject: Nolan Ryan.",
            '* Claim draft: {"stat": "SO", "value": 5714, "scope": "career", "table": "pitching"}',
            (
                '{"answer":"Nolan Ryan was a Hall of Fame pitcher who recorded '
                '5,714 strikeouts.","stat_claims":[{"stat":"SO","value":5714,'
                '"scope":"career","year":null,"text":"recorded 5,714 strikeouts",'
                '"table":"pitching"}]}'
            ),
        ]
    )

    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Nolan Ryan",
            raw_question="who was Nolan Ryan",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: LLMResponse(content=content, model="test-model", done=True),
    )

    result = answer("who was Nolan Ryan")

    assert result.unsupported is False
    assert "Nolan Ryan was a Hall of Fame pitcher" in result.answer
    assert result.sources[0].type == "duckdb"
    assert result.sources[0].rows[0]["status"] == "verified"
    assert result.sources[0].rows[0]["actual_value"] == 5714
    assert result.sources[0].rows[0]["table"] == "pitching"


def test_llm_biography_skips_draft_answer_object_before_final_contract(monkeypatch):
    """A draft answer-shaped JSON object should not preempt the final contract."""
    content = "\n".join(
        [
            '{"answer": ""}',
            (
                '{"answer":"Nolan Ryan recorded 5,714 career strikeouts.",'
                '"stat_claims":[{"stat":"SO","value":5714,"scope":"career",'
                '"year":null,"text":"recorded 5,714 career strikeouts",'
                '"table":"pitching"}]}'
            ),
        ]
    )

    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Nolan Ryan",
            raw_question="who was Nolan Ryan",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: LLMResponse(content=content, model="test-model", done=True),
    )

    result = answer("who was Nolan Ryan")

    assert result.unsupported is False
    assert result.answer.startswith("Nolan Ryan recorded 5,714 career strikeouts.")
    assert (
        "Stat claim verification: total claims 1, valid claims 1, invalid claims 0. "
        "Score: passing (1/1 verified)."
    ) in result.answer
    assert result.sources[0].rows[0]["status"] == "verified"


def test_llm_biography_retries_once_after_malformed_contract(monkeypatch):
    """A malformed first biography response should get one JSON repair attempt."""
    calls: list[tuple] = []

    def fake_llm(prompt, **kwargs):
        calls.append(prompt)
        if len(calls) == 1:
            return LLMResponse(
                content="* Nolan Ryan planning notes without any final JSON contract.",
                model="test-model",
                done=True,
            )
        return _llm_json(
            "Nolan Ryan recorded 5,714 career strikeouts.",
            [
                {
                    "stat": "SO",
                    "value": 5714,
                    "scope": "career",
                    "text": "5,714 career strikeouts",
                    "table": "pitching",
                }
            ],
        )

    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Nolan Ryan",
            raw_question="who was Nolan Ryan",
        ),
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("who was Nolan Ryan")

    assert len(calls) == 2
    assert result.unsupported is False
    assert "5,714 career strikeouts" in result.answer
    assert result.sources[0].rows[0]["status"] == "verified"


def test_llm_biography_with_contradicted_stat_claim_warns_but_returns_prose(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question="who was Babe Ruth",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json(
            "Babe Ruth hit 999 career home runs.",
            [{"stat": "HR", "value": 999, "scope": "career", "text": "999 career home runs"}],
        ),
    )

    result = answer("who was Babe Ruth")

    assert "Babe Ruth hit 999 career home runs." in result.answer
    assert "Most stat claims were verified." not in result.answer
    assert (
        "Stat claim verification: total claims 1, valid claims 0, invalid claims 1. "
        "Score: failing (0/1 verified)."
    ) in result.answer
    assert (
        "One stat claim was contradicted by DuckDB: HR was claimed as 999, "
        "but DuckDB has 714 for career."
    ) in result.answer
    assert "could not be verified" not in result.answer
    assert result.warnings
    assert result.sources[0].rows[0]["status"] == "contradicted"
    assert result.sources[0].rows[0]["actual_value"] == 714


def test_llm_biography_with_mixed_claims_names_only_contradictions(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Alex Rodriguez",
            raw_question="who was Alex Rodriguez",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json(
            "Alex Rodriguez recorded 696 HR, 2,086 RBI, and 301 SB.",
            [
                {"stat": "HR", "value": 696, "scope": "career", "text": "696 HR"},
                {"stat": "RBI", "value": 2086, "scope": "career", "text": "2,086 RBI"},
                {"stat": "SB", "value": 301, "scope": "career", "text": "301 SB"},
            ],
        ),
    )

    result = answer("who was Alex Rodriguez")

    assert (
        "Stat claim verification: total claims 3, valid claims 2, invalid claims 1. "
        "Score: failing (2/3 verified)."
    ) in result.answer
    assert "Most stat claims were verified." in result.answer
    assert (
        "One stat claim was contradicted by DuckDB: SB was claimed as 301, "
        "but DuckDB has 329 for career."
    ) in result.answer
    assert "could not be verified" not in result.answer
    assert [row["status"] for row in result.sources[0].rows] == [
        "verified",
        "verified",
        "contradicted",
    ]


def test_supplied_biography_verification_scores_all_claims_without_llm(monkeypatch):
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("supplied biography verification should not call the LLM")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)
    question = (
        "Alex Rodriguez, often referred to as A-Rod, was a premier talent in Major League "
        "Baseball from 1994 to 2016. Primarily playing shortstop and third base for the "
        "Seattle Mariners, Texas Rangers, and New York Yankees, he established himself as "
        "one of the most prolific hitters of his era. Throughout his career, Rodriguez "
        "recorded 696 HR, 2,086 RBI, and 3,115 H, while also contributing 301 SB. "
        "A three-time American League MVP, his impact on the game remains significant.\n\n"
        "Note: Some stat claims in this biography could not be verified against DuckDB. "
        "Which ones and why?"
    )

    result = answer(question)

    assert result.intent == "player_biography"
    assert (
        "I checked the stat claims in the supplied biography for Alex Rodriguez." in result.answer
    )
    assert (
        "Stat claim verification: total claims 5, valid claims 3, invalid claims 2. "
        "Score: failing (3/5 verified)."
    ) in result.answer
    assert "Most stat claims were verified." in result.answer
    assert "SB was claimed as 301, but DuckDB has 329 for career." in result.answer
    assert (
        "MVP was claimed as 3, but DuckDB verification does not support that stat." in result.answer
    )
    assert [row["status"] for row in result.sources[0].rows] == [
        "verified",
        "verified",
        "verified",
        "contradicted",
        "unsupported_stat",
    ]


def test_supplied_biography_verifies_season_claim_against_that_year(monkeypatch):
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("supplied biography verification should not call the LLM")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

    result = answer("Babe Ruth hit 60 HR in 1927. Which stat claims can be verified by DuckDB?")

    assert (
        "Stat claim verification: total claims 1, valid claims 1, invalid claims 0. "
        "Score: passing (1/1 verified)."
    ) in result.answer
    assert result.sources[0].rows[0]["status"] == "verified"
    assert result.sources[0].rows[0]["scope"] == "season"
    assert result.sources[0].rows[0]["year"] == 1927


def test_supplied_biography_preserves_leading_decimal_rate_claim(monkeypatch):
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("supplied biography verification should not call the LLM")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

    result = answer(
        "Babe Ruth had a .342 batting average. Which stat claims can be verified against DuckDB?"
    )

    assert (
        "Stat claim verification: total claims 1, valid claims 1, invalid claims 0. "
        "Score: passing (1/1 verified)."
    ) in result.answer
    assert result.sources[0].rows[0]["claimed_value"] == ".342"
    assert result.sources[0].rows[0]["status"] == "verified"


def test_llm_biography_does_not_say_most_when_verified_claims_are_not_majority(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Alex Rodriguez",
            raw_question="who was Alex Rodriguez",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json(
            "Alex Rodriguez recorded 696 HR, 1 RBI, and 301 SB.",
            [
                {"stat": "HR", "value": 696, "scope": "career", "text": "696 HR"},
                {"stat": "RBI", "value": 1, "scope": "career", "text": "1 RBI"},
                {"stat": "SB", "value": 301, "scope": "career", "text": "301 SB"},
            ],
        ),
    )

    result = answer("who was Alex Rodriguez")

    assert (
        "Stat claim verification: total claims 3, valid claims 1, invalid claims 2. "
        "Score: failing (1/3 verified)."
    ) in result.answer
    assert "Most stat claims were verified." not in result.answer
    assert "2 stat claims were contradicted by DuckDB:" in result.answer
    assert "RBI was claimed as 1, but DuckDB has 2086 for career" in result.answer
    assert "SB was claimed as 301, but DuckDB has 329 for career" in result.answer


def test_llm_biography_unverifiable_claim_note_summarizes_without_repeating_warning(
    monkeypatch,
):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question="who was Babe Ruth",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: _llm_json(
            "Babe Ruth had 5 career vibes.",
            [{"stat": "VIBES", "value": 5, "scope": "career", "text": "5 career vibes"}],
        ),
    )

    result = answer("who was Babe Ruth")

    assert (
        "Stat claim verification: total claims 1, valid claims 0, invalid claims 1. "
        "Score: failing (0/1 verified)."
    ) in result.answer
    assert (
        "One stat claim was not verifiable against DuckDB: VIBES was claimed as 5, "
        "but DuckDB verification does not support that stat."
    ) in result.answer
    assert "Unsupported biography stat claim" not in result.answer
    assert result.warnings == ["Unsupported biography stat claim 'VIBES'."]
    assert result.sources[0].rows[0]["status"] == "unsupported_stat"


def test_unresolved_player_biography_fails_before_llm_generation(monkeypatch):
    calls = {"llm": 0}

    def fail_if_called(*_args, **_kwargs):
        calls["llm"] += 1
        raise AssertionError("LLM should not be called for unresolved players")

    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Definitely Not A Player",
            raw_question="who was Definitely Not A Player",
        ),
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_if_called)

    result = answer("who was Definitely Not A Player")

    assert result.unsupported is True
    assert result.unsupported_reason == "no_data"
    assert calls["llm"] == 0


def test_ambiguous_player_biography_fails_before_llm_generation(monkeypatch):
    calls = {"llm": 0}

    def fail_if_called(*_args, **_kwargs):
        calls["llm"] += 1
        raise AssertionError("LLM should not be called for ambiguous players")

    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(player_name="Smith", raw_question="who was Smith"),
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_if_called)

    result = answer("who was Smith")

    assert result.unsupported is True
    assert result.unsupported_reason == "ambiguous"
    assert calls["llm"] == 0


def test_llm_unavailable_for_biography_returns_llm_unavailable(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question="who was Babe Ruth",
        ),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ConnectionError("LM Studio down")),
    )

    result = answer("who was Babe Ruth")

    assert result.unsupported is True
    assert result.unsupported_reason == "llm_unavailable"
    assert "LM Studio" in result.answer
    assert not result.sources


def test_general_stat_explanation_routes_to_open_llm_not_corpus(monkeypatch):
    captured = {}

    def fake_llm(prompt, **_kwargs):
        captured["prompt"] = prompt
        return LLMResponse(content="OPS is on-base plus slugging.", model="test-model", done=True)

    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: GeneralExplanationCase(raw_question="what is OPS?", stat="OPS"),
    )
    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

    result = answer("what is OPS?")

    assert result.answer == "OPS is on-base plus slugging."
    assert result.sources == []
    assert "Question: what is OPS?" in captured["prompt"][1]


def test_chroma_runtime_module_is_removed():
    assert importlib.util.find_spec("baseball_rag.retrieval.chroma_store") is None
