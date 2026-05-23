"""Player biography and open explanation behavior."""

from __future__ import annotations

from pathlib import Path

from baseball_rag import player_biography
from baseball_rag.generation.llm import LLMResponse
from baseball_rag.routing import GeneralExplanationCase, PlayerBiographyCase
from baseball_rag.service import answer

ROOT = Path(__file__).resolve().parents[1]


def _llm_json(answer_text: str, claims: list[dict] | None = None) -> LLMResponse:
    import json

    return LLMResponse(
        content=json.dumps({"answer": answer_text, "stat_claims": claims or []}),
        model="test-model",
        done=True,
    )


def _consensus_scorecard(
    *,
    total: int,
    verified_by_all: int,
    primary_only: int,
    secondary_only: int,
    contradicted_by_all: int,
    conflicts: int,
    unsupported: int,
    score: str,
) -> str:
    return (
        f"Stat claim consensus: total claims {total}, verified by all {verified_by_all}, "
        f"primary only {primary_only}, secondary only {secondary_only}, "
        f"contradicted by all {contradicted_by_all}, conflicts {conflicts}, "
        f"unsupported {unsupported}. Score: {score} "
        f"({verified_by_all}/{total} verified by all)."
    )


def test_stat_definition_answer_uses_local_definition_text_without_llm(monkeypatch):
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("stat definition should be answered from local Markdown")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

    result = answer("what is an RBI")

    assert result.intent == "general_explanation"
    assert result.unsupported is False
    assert "run batted in" in result.answer.lower()
    assert result.sources[0].type == "stat_definition"


class _ConsensusVerification:
    def __init__(
        self,
        *,
        stat: str,
        claimed_value: object,
        status: str,
        actual_value: object | None = None,
        warning: str | None = None,
        source_label: str = "Lahman and Retrosheet consensus",
    ) -> None:
        self.stat = stat
        self.status = status
        self.actual_value = actual_value
        self.warning = warning
        self.sql = "select consensus evidence"
        self.table = "batting"
        self.source_label = source_label
        self.source_detail = "Lahman batting rows reconciled with Retrosheet event totals."
        self.row = {
            "stat": stat,
            "claimed_value": claimed_value,
            "actual_value": actual_value,
            "year": None,
            "scope": "career",
            "text": f"{claimed_value} {stat}",
            "status": status,
            "table": "batting",
            "warning": warning,
            "primary_source": "Lahman",
            "secondary_source": "Retrosheet",
            "primary_status": "verified"
            if status in {"verified_by_all", "primary_only"}
            else status,
            "secondary_status": (
                "verified" if status in {"verified_by_all", "secondary_only"} else status
            ),
            "primary_actual_value": actual_value,
            "secondary_actual_value": actual_value,
            "source_label": source_label,
        }

    @property
    def verified(self) -> bool:
        return self.status == "verified_by_all"

    @property
    def claim(self):
        return type(
            "Claim",
            (),
            {
                "stat": self.stat,
                "value": self.row["claimed_value"],
                "year": None,
                "resolved_scope": "career",
            },
        )()

    def to_row(self) -> dict:
        return dict(self.row)


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


def test_llm_biography_uses_consensus_verifier_and_labels_evidence(monkeypatch):
    calls = []

    def fake_consensus(player_id, claims, *, conn):
        calls.append((player_id, claims, conn))
        return [
            _ConsensusVerification(
                stat="HR",
                claimed_value=714,
                actual_value=714,
                status="verified_by_all",
            )
        ]

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
    monkeypatch.setattr(
        "baseball_rag.service.verify_player_stat_claims_consensus",
        fake_consensus,
        raising=False,
    )

    result = answer("who was Babe Ruth")

    assert calls
    assert result.sources[0].type == "duckdb"
    assert result.sources[0].label == "DuckDB Lahman + Retrosheet biography stat consensus"
    assert "Lahman" in result.sources[0].detail
    assert "Retrosheet" in result.sources[0].detail
    assert result.sources[0].data_manifest["consensus_sources"] == [
        {
            "name": "Lahman",
            "role": "primary",
            "dataset": "NeuML/baseballdata",
            "upstream": "Lahman Baseball Database",
        },
        {
            "name": "Retrosheet",
            "role": "secondary",
            "dataset": "Retrosheet event/stat consensus",
            "upstream": "Retrosheet",
        },
    ]
    row = result.sources[0].rows[0]
    assert row["status"] == "verified_by_all"
    assert row["actual_value"] == 714
    assert row["primary_source"] == "Lahman"
    assert row["secondary_source"] == "Retrosheet"
    assert result.metadata["stat_claims"][0]["source_label"] == "Lahman and Retrosheet consensus"
    assert result.metadata["stat_claim_summary"] == {
        "total_claims": 1,
        "verified_by_all": 1,
        "primary_only": 0,
        "secondary_only": 0,
        "contradicted_by_all": 0,
        "conflicts": 0,
        "unsupported": 0,
        "score": "passing",
    }


def test_llm_biography_surfaces_secondary_consensus_sql(monkeypatch):
    def fake_consensus(_player_id, _claims, *, conn):
        verification = _ConsensusVerification(
            stat="HR",
            claimed_value=714,
            actual_value=714,
            status="secondary_only",
        )
        verification.row.update(
            {
                "consensus_status": "verified_secondary_only",
                "primary_status": "no_data",
                "secondary_status": "verified",
                "sql": "select lahman evidence",
                "primary_sql": "select lahman evidence",
                "secondary_sql": "select retrosheet evidence",
                "secondary_params": ["ruthb101"],
            }
        )
        return [verification]

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
    monkeypatch.setattr(
        "baseball_rag.service.verify_player_stat_claims_consensus",
        fake_consensus,
        raising=False,
    )

    result = answer("who was Babe Ruth")

    assert result.sources[0].sql == "select retrosheet evidence"
    assert result.sources[0].rows[0]["secondary_sql"] == "select retrosheet evidence"
    assert result.sources[0].rows[0]["secondary_params"] == ["ruthb101"]


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
        _consensus_scorecard(
            total=1,
            verified_by_all=0,
            primary_only=1,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=0,
            score="failing",
        )
        in result.answer
    )
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
        _consensus_scorecard(
            total=1,
            verified_by_all=0,
            primary_only=1,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=0,
            score="failing",
        )
        in result.answer
    )
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
        _consensus_scorecard(
            total=1,
            verified_by_all=0,
            primary_only=1,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=0,
            score="failing",
        )
        in result.answer
    )
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


def test_player_biography_answerer_accepts_biography_request_dependency(monkeypatch):
    """The answerer accepts an explicit biography JSON request dependency."""
    calls = []

    def fake_request_biography(_make_request, _prompt):
        calls.append("called")
        return {"answer": "Patched Babe Ruth biography.", "claims": []}

    answerer = player_biography.PlayerBiographyCaseAnswerer(
        make_request=lambda *_args, **_kwargs: None,
        request_biography=fake_request_biography,
    )

    result = answerer.answer(
        "who was Babe Ruth",
        PlayerBiographyCase(
            player_name="Babe Ruth",
            raw_question="who was Babe Ruth",
        ),
    )

    assert calls == ["called"]
    assert result.answer == "Patched Babe Ruth biography."


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
        _consensus_scorecard(
            total=1,
            verified_by_all=0,
            primary_only=0,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=1,
            score="failing",
        )
        in result.answer
    )
    assert (
        "One stat claim was not verifiable against Lahman and Retrosheet: "
        "HR was claimed as 999, Lahman has 714, and Retrosheet did not verify it."
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
        _consensus_scorecard(
            total=3,
            verified_by_all=0,
            primary_only=2,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=1,
            score="failing",
        )
        in result.answer
    )
    assert "Most stat claims were verified." not in result.answer
    assert (
        "SB was claimed as 301, Lahman has 329, and Retrosheet did not verify it" in result.answer
    )
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
        _consensus_scorecard(
            total=5,
            verified_by_all=0,
            primary_only=3,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=2,
            score="failing",
        )
        in result.answer
    )
    assert "Most stat claims were verified." not in result.answer
    assert (
        "SB was claimed as 301, Lahman has 329, and Retrosheet did not verify it" in result.answer
    )
    assert (
        "MVP was claimed as 3, but Lahman/Retrosheet consensus verification "
        "does not support that stat." in result.answer
    )
    assert [row["status"] for row in result.sources[0].rows] == [
        "verified",
        "verified",
        "verified",
        "contradicted",
        "unsupported_stat",
    ]


def test_supplied_biography_extraction_canonicalizes_supported_aliases():
    claims = player_biography.extract_supplied_stat_claims(
        "Can DuckDB verify these claim totals? The player had 1 home run, "
        "2 stolen base, 3 hit, 4 win, and 5 strikeout."
    )

    assert [claim.stat for claim in claims] == ["HR", "SB", "H", "W", "SO"]
    assert [claim.value for claim in claims] == ["1", "2", "3", "4", "5"]


def test_supplied_biography_consensus_scorecard_counts_source_disagreements(monkeypatch):
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("supplied biography verification should not call the LLM")

    def fake_consensus(_player_id, _claims, *, conn):
        assert conn is not None
        return [
            _ConsensusVerification(
                stat="HR",
                claimed_value=714,
                actual_value=714,
                status="verified_by_all",
            ),
            _ConsensusVerification(
                stat="RBI",
                claimed_value=2214,
                actual_value=2214,
                status="primary_only",
            ),
            _ConsensusVerification(
                stat="H",
                claimed_value=2873,
                actual_value=2873,
                status="secondary_only",
            ),
            _ConsensusVerification(
                stat="SB",
                claimed_value=200,
                actual_value=123,
                status="contradicted_by_all",
                warning="Lahman and Retrosheet both contradict SB.",
            ),
            _ConsensusVerification(
                stat="AVG",
                claimed_value=".400",
                actual_value=None,
                status="conflict",
                warning="Lahman and Retrosheet disagree on AVG.",
            ),
            _ConsensusVerification(
                stat="MVP",
                claimed_value=1,
                actual_value=None,
                status="unsupported_stat",
                warning="Unsupported biography stat claim 'MVP'.",
            ),
        ]

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)
    monkeypatch.setattr(
        "baseball_rag.service.verify_player_stat_claims_consensus",
        fake_consensus,
        raising=False,
    )

    result = answer(
        "Babe Ruth hit 714 HR, 2,214 RBI, 2,873 H, 200 SB, had a .400 batting "
        "average, and was a one-time MVP. Which stat claims can be verified by DuckDB?"
    )

    assert (
        _consensus_scorecard(
            total=6,
            verified_by_all=1,
            primary_only=1,
            secondary_only=1,
            contradicted_by_all=1,
            conflicts=1,
            unsupported=1,
            score="failing",
        )
        in result.answer
    )
    assert "Most stat claims were verified." not in result.answer
    assert result.warnings == [
        "Lahman and Retrosheet both contradict SB.",
        "Lahman and Retrosheet disagree on AVG.",
        "Unsupported biography stat claim 'MVP'.",
    ]
    assert [row["status"] for row in result.sources[0].rows] == [
        "verified_by_all",
        "primary_only",
        "secondary_only",
        "contradicted_by_all",
        "conflict",
        "unsupported_stat",
    ]
    assert result.metadata["stat_claim_summary"]["conflicts"] == 1


def test_supplied_biography_verifies_season_claim_against_that_year(monkeypatch):
    def fail_llm(*_args, **_kwargs):
        raise AssertionError("supplied biography verification should not call the LLM")

    monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

    result = answer("Babe Ruth hit 60 HR in 1927. Which stat claims can be verified by DuckDB?")

    assert (
        _consensus_scorecard(
            total=1,
            verified_by_all=0,
            primary_only=1,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=0,
            score="failing",
        )
        in result.answer
    )
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
        _consensus_scorecard(
            total=1,
            verified_by_all=0,
            primary_only=1,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=0,
            score="failing",
        )
        in result.answer
    )
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
        _consensus_scorecard(
            total=3,
            verified_by_all=0,
            primary_only=1,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=2,
            score="failing",
        )
        in result.answer
    )
    assert "Most stat claims were verified." not in result.answer
    assert "2 stat claims were not verifiable against Lahman and Retrosheet:" in result.answer
    assert (
        "RBI was claimed as 1, Lahman has 2086, and Retrosheet did not verify it" in result.answer
    )
    assert (
        "SB was claimed as 301, Lahman has 329, and Retrosheet did not verify it" in result.answer
    )


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
        _consensus_scorecard(
            total=1,
            verified_by_all=0,
            primary_only=0,
            secondary_only=0,
            contradicted_by_all=0,
            conflicts=0,
            unsupported=1,
            score="failing",
        )
        in result.answer
    )
    assert (
        "One stat claim was not verifiable against Lahman and Retrosheet: "
        "VIBES was claimed as 5, but Lahman/Retrosheet consensus verification "
        "does not support that stat."
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


def test_general_stat_explanation_uses_local_stat_definition_before_open_llm(monkeypatch):
    monkeypatch.setattr(
        "baseball_rag.service.route",
        lambda _question: GeneralExplanationCase(raw_question="what is OPS?", stat="OPS"),
    )
    monkeypatch.setattr(
        "baseball_rag.generation.llm.make_request",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("stat definition should not call the LLM")
        ),
    )

    result = answer("what is OPS?")

    assert "on-base plus slugging" in result.answer.lower()
    assert result.sources[0].type == "stat_definition"


def test_chroma_runtime_module_is_removed():
    retrieval_dir = ROOT / "src" / "baseball_rag" / "retrieval"

    assert not (retrieval_dir / "chroma_store.py").exists()
    assert not (retrieval_dir / "__init__.py").exists()
