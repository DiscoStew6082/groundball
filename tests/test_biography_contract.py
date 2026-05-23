import pytest

from baseball_rag.biography_contract import (
    BiographyContractError,
    parse_biography_json,
    request_biography_json,
)
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


def test_biography_contract_invalid_claim_payload_becomes_typed_failure():
    with pytest.raises(BiographyContractError, match="stat claim scope"):
        parse_biography_json(
            '{"answer":"Bad claim.","stat_claims":[{"stat":"HR","value":1,"scope":"game"}]}'
        )


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
