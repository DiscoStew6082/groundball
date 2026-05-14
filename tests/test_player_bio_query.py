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
    assert result.answer == "Nolan Ryan recorded 5,714 career strikeouts."
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
    assert "Note:" in result.answer
    assert result.warnings
    assert result.sources[0].rows[0]["status"] == "contradicted"
    assert result.sources[0].rows[0]["actual_value"] == 714


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
