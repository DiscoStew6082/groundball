from baseball_rag.generation.llm import LLMResponse
from baseball_rag.player_biography import PlayerBiographyCaseAnswerer
from baseball_rag.routing import PlayerBiographyCase


def test_player_biography_case_answerer_preserves_resolved_player_metadata():
    answerer = PlayerBiographyCaseAnswerer(
        make_request=lambda *_args, **_kwargs: LLMResponse(
            content='{"answer":"Babe Ruth was a two-way star.","stat_claims":[]}',
            model="test-model",
            done=True,
        )
    )

    result = answerer.answer(
        "who was Babe Ruth",
        PlayerBiographyCase(player_name="Babe Ruth", raw_question="who was Babe Ruth"),
    )

    assert result.intent == "player_biography"
    assert result.answer == "Babe Ruth was a two-way star."
    assert result.metadata["resolved_player"] == {
        "player_id": "ruthba01",
        "name": "Babe Ruth",
        "debut": "1914-07-11",
        "final_game": "1935-05-30",
    }


def test_player_biography_case_answerer_repairs_malformed_llm_json():
    responses = iter(
        [
            LLMResponse(
                content="Babe Ruth was a two-way star.",
                model="test-model",
                done=True,
            ),
            LLMResponse(
                content='{"answer":"Babe Ruth was a two-way star.","stat_claims":[]}',
                model="test-model",
                done=True,
            ),
        ]
    )
    prompts = []

    def make_request(prompt, **_kwargs):
        prompts.append(prompt)
        return next(responses)

    answerer = PlayerBiographyCaseAnswerer(
        make_request=make_request,
        verify_claims_consensus=lambda *_args, **_kwargs: [],
    )

    result = answerer.answer(
        "who was Babe Ruth",
        PlayerBiographyCase(player_name="Babe Ruth", raw_question="who was Babe Ruth"),
    )

    assert result.answer == "Babe Ruth was a two-way star."
    assert len(prompts) == 2
    assert "Repair this invalid response" in prompts[1][1]


def test_player_biography_case_answerer_handles_supplied_claims_without_llm():
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("supplied claim verification should not call the LLM")

    answerer = PlayerBiographyCaseAnswerer(make_request=fail_llm)

    result = answerer.answer(
        "Babe Ruth hit 60 HR in 1927. Which stat claims can be verified by DuckDB?",
        PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question=(
                "Babe Ruth hit 60 HR in 1927. Which stat claims can be verified by DuckDB?"
            ),
        ),
    )

    assert "I checked the stat claims in the supplied biography for Babe Ruth." in result.answer
    assert result.sources[0].label == "DuckDB Lahman + Retrosheet supplied biography stat consensus"
    assert result.sources[0].rows[0]["status"] == "verified"
    assert result.metadata["context_player_name"] == "Babe Ruth"
