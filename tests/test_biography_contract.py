import pytest

from baseball_rag.biography_contract import (
    BiographyContractError,
    build_biography_json_repair_prompt,
    parse_biography_json,
    request_biography_json,
)
from baseball_rag.db.biography_stat_vocabulary import biography_claim_prompt_stat_list
from baseball_rag.db.player_stat_claims import PlayerStatClaim
from baseball_rag.generation.llm import LLMResponse


def test_biography_contract_parses_valid_supported_claims():
    contract = parse_biography_json(
        '{"answer":"Nolan Ryan was a Hall of Fame pitcher.",'
        '"stat_claims":[{"stat":"SO","value":5714,"scope":"career",'
        '"year":null,"text":"5,714 strikeouts","table":"pitching"}]}'
    )

    assert contract["answer"] == "Nolan Ryan was a Hall of Fame pitcher."
    assert contract["claims"] == [
        PlayerStatClaim(
            stat="SO",
            value=5714,
            scope="career",
            text="5,714 strikeouts",
            table="pitching",
        )
    ]


def test_biography_contract_extracts_final_json_from_planning_chatter():
    contract = parse_biography_json(
        "* Draft\n"
        '{"answer":"","stat_claims":[]}\n'
        '```json\n{"answer":"Babe Ruth was a two-way star.","stat_claims":[]}\n```'
    )

    assert contract == {"answer": "Babe Ruth was a two-way star.", "claims": []}


def test_biography_contract_prefers_final_contract_over_valid_draft_json():
    contract = parse_biography_json(
        '{"answer":"Draft biography that should not be used.","stat_claims":[]}\n'
        '```json\n{"answer":"Final Babe Ruth biography.","stat_claims":[]}\n```'
    )

    assert contract == {"answer": "Final Babe Ruth biography.", "claims": []}


def test_biography_contract_repairs_malformed_first_response_once():
    responses = iter(
        [
            LLMResponse(content="planning notes", model="m", done=True),
            LLMResponse(
                content='{"answer":"Fixed biography.","stat_claims":[]}',
                model="m",
                done=True,
            ),
        ]
    )
    prompts = []

    def fake_llm(prompt, **kwargs):
        prompts.append((prompt, kwargs))
        return next(responses)

    contract = request_biography_json(fake_llm, ("system", "user"))

    assert contract == {"answer": "Fixed biography.", "claims": []}
    assert len(prompts) == 2
    assert "Repair this invalid response" in prompts[1][0][1]


def test_biography_repair_prompt_uses_claim_vocabulary_stat_list():
    system_prompt, user_prompt = build_biography_json_repair_prompt("not json")

    assert biography_claim_prompt_stat_list() in system_prompt
    assert "not json" in user_prompt


def test_biography_contract_invalid_claim_payload_becomes_typed_failure():
    with pytest.raises(BiographyContractError, match="stat claim scope"):
        parse_biography_json(
            '{"answer":"Bad claim.","stat_claims":[{"stat":"HR","value":1,"scope":"game"}]}'
        )


def test_biography_contract_rejects_missing_supported_stat_claim():
    with pytest.raises(BiographyContractError, match="missing from stat_claims"):
        parse_biography_json('{"answer":"Babe Ruth hit 714 career home runs.","stat_claims":[]}')


def test_biography_contract_rejects_stat_before_value_supported_claim():
    with pytest.raises(BiographyContractError, match="missing from stat_claims"):
        parse_biography_json(
            '{"answer":"Ted Williams had a batting average of .406 in 1941.","stat_claims":[]}'
        )


def test_biography_contract_requires_matching_season_claim_year():
    with pytest.raises(BiographyContractError, match="missing from stat_claims"):
        parse_biography_json(
            '{"answer":"Babe Ruth hit 60 home runs in 1927.",'
            '"stat_claims":[{"stat":"HR","value":60,"scope":"career",'
            '"text":"60 home runs"}]}'
        )


def test_biography_contract_detects_capitalized_year_before_claim():
    with pytest.raises(BiographyContractError, match="missing from stat_claims"):
        parse_biography_json(
            '{"answer":"In 1927, Babe Ruth hit 60 home runs.",'
            '"stat_claims":[{"stat":"HR","value":60,"scope":"career",'
            '"text":"60 home runs"}]}'
        )


def test_biography_contract_requires_matching_career_claim_scope():
    with pytest.raises(BiographyContractError, match="missing from stat_claims"):
        parse_biography_json(
            '{"answer":"Babe Ruth hit 60 career home runs.",'
            '"stat_claims":[{"stat":"HR","value":60,"scope":"season","year":1927,'
            '"text":"60 home runs"}]}'
        )


def test_biography_contract_does_not_use_next_sentence_year_for_career_claim():
    contract = parse_biography_json(
        '{"answer":"Babe Ruth hit 714 career home runs. In 1927, he hit 60.",'
        '"stat_claims":[{"stat":"HR","value":714.0,"scope":"career",'
        '"text":"714 career home runs"}]}'
    )

    assert contract["claims"][0].value == 714.0


def test_biography_contract_does_not_treat_context_year_as_season_for_career_claim():
    contract = parse_biography_json(
        '{"answer":"By 1935, Babe Ruth had 714 career home runs.",'
        '"stat_claims":[{"stat":"HR","value":714,"scope":"career",'
        '"text":"714 career home runs"}]}'
    )

    assert contract["claims"][0].resolved_scope == "career"


def test_biography_contract_ignores_unsupported_stat_like_prose():
    contract = parse_biography_json(
        '{"answer":"Babe Ruth wore number 3 and won seven World Series titles.","stat_claims":[]}'
    )

    assert contract == {
        "answer": "Babe Ruth wore number 3 and won seven World Series titles.",
        "claims": [],
    }


def test_biography_contract_ignores_dates_without_supported_stat_claims():
    contract = parse_biography_json(
        '{"answer":"Babe Ruth debuted in 1914 and last played in 1935.","stat_claims":[]}'
    )

    assert contract == {
        "answer": "Babe Ruth debuted in 1914 and last played in 1935.",
        "claims": [],
    }


@pytest.mark.parametrize(
    "content",
    [
        '{"answer":"No claim array."}',
        '{"answer":"Null claim array.","stat_claims":null}',
    ],
)
def test_biography_contract_requires_stat_claims_array(content):
    with pytest.raises(BiographyContractError, match="stat_claims must be a list"):
        parse_biography_json(content)


def test_biography_contract_does_not_accept_context_as_claim_text_alias():
    contract = parse_biography_json(
        '{"answer":"Nolan Ryan was a Hall of Fame pitcher.",'
        '"stat_claims":[{"stat":"SO","value":5714,"scope":"career",'
        '"year":null,"context":"5,714 strikeouts","table":"pitching"}]}'
    )

    assert contract["claims"][0].text is None
