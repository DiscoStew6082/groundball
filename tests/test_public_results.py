"""Public-only result, pagination, and complete-export contract."""

import pytest

import baseball_rag.public_results as public_results
from baseball_rag.public_results import (
    EXPORT_CONTENT_MAX_BYTES,
    EXPORT_RESPONSE_MAX_BYTES,
    EXPORT_ROW_MAX,
    compact_json_bytes,
    export_measurements,
    first_exceeded_export_ceiling,
    run_public_query_input,
)
from baseball_rag.query.adapters import run_query_input


def test_public_natural_language_defaults_to_25_without_changing_local_default() -> None:
    public = run_public_query_input(question="40-40")
    local = run_query_input(question="40-40")

    assert public["recipe"]["output"] == {
        "kind": "interactive_page",
        "size": 25,
        "offset": 0,
    }
    assert public["plan"]["output"] == public["recipe"]["output"]
    assert len(public["rows"]) <= 25
    assert local["recipe"]["output"] == {
        "kind": "interactive_page",
        "size": 100,
        "offset": 0,
    }


def test_ohtani_natural_and_structured_public_paths_have_semantic_parity() -> None:
    question = "how many home runs did ohtani hit in the year he had the most wins as a pitcher"
    structured_recipe = {
        "source": "Batting",
        "grain": "player-season",
        "selections": ["player.name", "season", "batting.HR", "pitching.W"],
        "predicate": {
            "kind": "compare",
            "value": "player.name",
            "operator": "equals",
            "literal": "Shohei Ohtani",
        },
        "ranking": {
            "value": "pitching.W",
            "direction": "highest",
            "count": 1,
            "tie_policy": "include_ties",
            "within": [],
        },
    }

    natural = run_public_query_input(question=question)
    structured = run_public_query_input(recipe=structured_recipe)

    stable_fields = (
        "kind",
        "recipe",
        "plan",
        "rows",
        "evidence",
        "verification",
        "returned_row_count",
        "total_matched_count",
        "pagination",
    )
    assert {field: natural[field] for field in stable_fields} == {
        field: structured[field] for field in stable_fields
    }
    assert natural["rows"] == [
        {
            "player.name": "Shohei Ohtani",
            "season": 2022,
            "batting.HR": 34,
            "pitching.W": 15,
        }
    ]
    assert natural["evidence"]["bound_values"] == ["Shohei Ohtani"] * 4
    assert '"__match_player.name_2"' in natural["evidence"]["parameterized_sql"]
    assert natural["verification"]["status"] == "verified"


def test_public_follow_up_uses_only_previous_recipe_context_and_keeps_25_row_envelope() -> None:
    first = run_public_query_input(question="how many RBIs did Shohei Ohtani have in 2022")

    follow_up = run_public_query_input(
        question="what about his home runs in 2022?",
        previous_recipe=first["recipe"],
    )

    assert follow_up["recipe"]["selections"] == ["player.name", "season", "batting.HR"]
    assert follow_up["recipe"]["predicate"]["predicates"][0]["literal"] == "Shohei Ohtani"
    assert follow_up["recipe"]["output"] == {
        "kind": "interactive_page",
        "size": 25,
        "offset": 0,
    }
    assert first["rows"] == [{"player.name": "Shohei Ohtani", "season": 2022, "batting.RBI": 95}]
    assert follow_up["rows"] == [{"player.name": "Shohei Ohtani", "season": 2022, "batting.HR": 34}]
    assert follow_up["evidence"]["bound_values"] == [
        "Shohei Ohtani",
        "Shohei Ohtani",
        "Shohei Ohtani",
        "Shohei Ohtani",
        2022,
    ]
    assert follow_up["verification"]["status"] == "verified"


def test_public_structured_recipe_without_output_uses_the_public_default() -> None:
    result = run_public_query_input(
        recipe={
            "source": "Batting",
            "grain": "raw_rows",
            "selections": ["Batting.playerID"],
        }
    )

    assert result["recipe"]["output"] == {
        "kind": "interactive_page",
        "size": 25,
        "offset": 0,
    }
    assert result["returned_row_count"] == 25


def test_public_clarification_choices_keep_the_public_25_row_default() -> None:
    clarification = run_public_query_input(question="who had the most strikeouts in 2024")

    assert clarification["kind"] == "needs_clarification"
    assert {choice["recipe"]["output"]["size"] for choice in clarification["choices"]} == {25}


@pytest.mark.parametrize(
    ("size", "offset"),
    [
        (0, 0),
        (24, 0),
        (26, 0),
        (101, 0),
        (-25, 0),
        (25.0, 0),
        ("25", 0),
        (25, -1),
        (25, 1.5),
        (True, 0),
        (25, False),
    ],
)
def test_public_interactive_pages_reject_unsupported_sizes_and_offsets(
    size: object,
    offset: object,
) -> None:
    local_recipe = run_query_input(question="40-40")["recipe"]
    local_recipe["output"] = {
        "kind": "interactive_page",
        "size": size,
        "offset": offset,
    }

    with pytest.raises(ValueError, match="Public interactive"):
        run_public_query_input(recipe=local_recipe)


@pytest.mark.parametrize("size", [25, 50, 100])
def test_public_interactive_pages_report_returned_total_and_pagination(size: int) -> None:
    result = run_public_query_input(
        recipe={
            "source": "Batting",
            "grain": "raw_rows",
            "selections": ["Batting.playerID"],
            "output": {"kind": "interactive_page", "size": size, "offset": 0},
        }
    )

    assert result["kind"] == "rows"
    assert result["returned_row_count"] == size
    assert result["total_matched_count"] > 100
    assert result["pagination"] == {
        "size": size,
        "offset": 0,
        "has_more": True,
    }
    assert len(result["rows"]) == size


def test_exhausted_public_page_stays_rows_while_zero_matches_is_no_data() -> None:
    recipe = {
        "source": "Batting",
        "grain": "raw_rows",
        "selections": ["Batting.playerID"],
        "output": {"kind": "interactive_page", "size": 25, "offset": 200_000},
    }
    exhausted = run_public_query_input(recipe=recipe)
    recipe["predicate"] = {
        "kind": "compare",
        "value": "Batting.playerID",
        "operator": "equals",
        "literal": "not-a-real-player",
    }
    no_data = run_public_query_input(recipe=recipe)

    assert exhausted["kind"] == "rows"
    assert exhausted["rows"] == []
    assert exhausted["returned_row_count"] == 0
    assert exhausted["total_matched_count"] > 0
    assert exhausted["pagination"] == {
        "size": 25,
        "offset": 200_000,
        "has_more": False,
    }
    assert no_data["kind"] == "no_data"
    assert no_data["returned_row_count"] == 0
    assert no_data["total_matched_count"] == 0
    assert no_data["pagination"]["has_more"] is False


def test_export_measurement_uses_utf8_content_and_complete_compact_response_bytes() -> None:
    payload = {
        "kind": "exported",
        "recipe": {"output": {"kind": "export", "format": "json"}},
        "plan": {"version": "query-plan-v1"},
        "rows": [{"name": "José ⚾"}],
        "evidence": {"matched_row_count": 1},
        "verification": {"status": "verified"},
        "export": {"format": "json", "content": '[{"name":"José ⚾"}]'},
    }

    measurements = export_measurements(payload)

    assert measurements == {
        "total_matched_count": 1,
        "content_bytes": len(payload["export"]["content"].encode("utf-8")),
        "response_bytes": len(compact_json_bytes(payload)),
    }
    assert measurements["content_bytes"] > len(payload["export"]["content"])


def test_export_row_ceiling_allows_exact_value_and_refuses_the_next_row() -> None:
    assert (
        first_exceeded_export_ceiling(
            total_matched_count=EXPORT_ROW_MAX,
            content_bytes=0,
            response_bytes=0,
        )
        is None
    )
    assert first_exceeded_export_ceiling(
        total_matched_count=EXPORT_ROW_MAX + 1,
        content_bytes=EXPORT_CONTENT_MAX_BYTES + 1,
        response_bytes=EXPORT_RESPONSE_MAX_BYTES + 1,
    ) == {
        "name": "matched_rows",
        "maximum": EXPORT_ROW_MAX,
        "observed": EXPORT_ROW_MAX + 1,
    }


def test_export_content_ceiling_counts_utf8_bytes_and_allows_exact_value() -> None:
    assert (
        first_exceeded_export_ceiling(
            total_matched_count=EXPORT_ROW_MAX,
            content_bytes=EXPORT_CONTENT_MAX_BYTES,
            response_bytes=0,
        )
        is None
    )
    assert first_exceeded_export_ceiling(
        total_matched_count=EXPORT_ROW_MAX,
        content_bytes=EXPORT_CONTENT_MAX_BYTES + len("⚾".encode("utf-8")),
        response_bytes=0,
    ) == {
        "name": "downloadable_bytes",
        "maximum": EXPORT_CONTENT_MAX_BYTES,
        "observed": EXPORT_CONTENT_MAX_BYTES + 3,
    }


def test_export_complete_response_ceiling_allows_exact_value_and_refuses_next_byte() -> None:
    assert (
        first_exceeded_export_ceiling(
            total_matched_count=EXPORT_ROW_MAX,
            content_bytes=EXPORT_CONTENT_MAX_BYTES,
            response_bytes=EXPORT_RESPONSE_MAX_BYTES,
        )
        is None
    )
    assert first_exceeded_export_ceiling(
        total_matched_count=EXPORT_ROW_MAX,
        content_bytes=EXPORT_CONTENT_MAX_BYTES,
        response_bytes=EXPORT_RESPONSE_MAX_BYTES + 1,
    ) == {
        "name": "complete_response_bytes",
        "maximum": EXPORT_RESPONSE_MAX_BYTES,
        "observed": EXPORT_RESPONSE_MAX_BYTES + 1,
    }


@pytest.mark.parametrize("output_format", ["csv", "json"])
def test_public_export_returns_complete_supported_content(output_format: str) -> None:
    recipe = run_query_input(question="who had the most RBIs in 1962")["recipe"]
    recipe["output"] = {"kind": "export", "format": output_format}

    exported = run_public_query_input(recipe=recipe)

    assert exported["kind"] == "exported"
    assert exported["evidence"]["matched_row_count"] == 1
    assert len(exported["rows"]) == 1
    assert "Tommy Davis" in exported["export"]["content"]
    assert exported["export"]["format"] == output_format


def test_public_export_content_byte_boundary_is_enforced_on_the_real_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe = run_query_input(question="who had the most RBIs in 1962")["recipe"]
    recipe["output"] = {"kind": "export", "format": "json"}
    local_export = run_query_input(recipe=recipe)
    measured = export_measurements(local_export)
    monkeypatch.setattr(public_results, "EXPORT_CONTENT_MAX_BYTES", measured["content_bytes"])

    exact = run_public_query_input(recipe=recipe)
    monkeypatch.setattr(
        public_results,
        "EXPORT_CONTENT_MAX_BYTES",
        measured["content_bytes"] - 1,
    )
    beyond = run_public_query_input(recipe=recipe)

    assert exact["kind"] == "exported"
    assert beyond["ceiling"] == {
        "name": "downloadable_bytes",
        "maximum": measured["content_bytes"] - 1,
        "observed": measured["content_bytes"],
    }
    assert "rows" not in beyond and "export" not in beyond


def test_public_export_response_byte_boundary_is_enforced_on_the_real_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recipe = run_query_input(question="who had the most RBIs in 1962")["recipe"]
    recipe["output"] = {"kind": "export", "format": "csv"}
    local_export = run_query_input(recipe=recipe)
    measured = export_measurements(local_export)
    monkeypatch.setattr(public_results, "EXPORT_RESPONSE_MAX_BYTES", measured["response_bytes"])

    exact = run_public_query_input(recipe=recipe)
    monkeypatch.setattr(
        public_results,
        "EXPORT_RESPONSE_MAX_BYTES",
        measured["response_bytes"] - 1,
    )
    beyond = run_public_query_input(recipe=recipe)

    assert exact["kind"] == "exported"
    assert beyond["ceiling"] == {
        "name": "complete_response_bytes",
        "maximum": measured["response_bytes"] - 1,
        "observed": measured["response_bytes"],
    }
    assert "rows" not in beyond and "export" not in beyond


def test_public_export_refuses_complete_team_reference_result_without_partial_material() -> None:
    recipe = {
        "source": "TeamReference",
        "grain": "raw_rows",
        "selections": [
            "TeamReference.yearID",
            "TeamReference.teamID",
            "TeamReference.name",
        ],
        "output": {"kind": "export", "format": "json"},
    }

    refusal = run_public_query_input(recipe=recipe)

    assert refusal == {
        "kind": "export_too_large",
        "error": "export_too_large",
        "total_matched_count": 3_613,
        "ceiling": {
            "name": "matched_rows",
            "maximum": EXPORT_ROW_MAX,
            "observed": 3_613,
        },
        "detail": "The complete export exceeds the public matched rows ceiling.",
        "guidance": "Add filters to narrow the result, then export again.",
    }
    assert "rows" not in refusal
    assert "export" not in refusal
