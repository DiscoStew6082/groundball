"""Tests for shared stat vocabulary."""

import re

from baseball_rag.db.biography_stat_vocabulary import (
    biography_claim_stat_aliases,
    biography_claim_stat_definitions,
    biography_claim_stat_regex_source,
    normalize_biography_claim_stat,
    retrosheet_adapter_stats,
    retrosheet_stat_column_candidates,
    supported_biography_claim_stats,
)
from baseball_rag.db.stat_registry import (
    StatSqlAdapter,
    find_stat_in_text,
    get_stat,
    infer_stat_table,
    normalize_stat,
    stat_aliases,
    stat_formula_notes,
    supported_stats,
)


def test_normalize_stat_maps_common_model_spellings():
    assert normalize_stat("home runs") == "HR"
    assert normalize_stat("runs batted in") == "RBI"
    assert normalize_stat("on-base plus slugging") == "OPS"


def test_find_stat_in_text_prefers_longer_phrases():
    assert find_stat_in_text("career home run leaders") == "HR"
    assert find_stat_in_text("what is OPS") == "OPS"
    assert find_stat_in_text("runs batted in leaders") == "RBI"


def test_exported_aliases_include_router_terms():
    aliases = stat_aliases()

    assert aliases["putouts"] == "PO"
    assert aliases["stolen bases"] == "SB"
    assert aliases["whip"] == "WHIP"


def test_ops_and_whip_are_sql_addressable():
    assert "OPS" in supported_stats()
    assert "WHIP" in supported_stats()
    assert get_stat("OPS").table == "batting"
    assert get_stat("WHIP").table == "pitching"


def test_registry_renders_ops_aggregate_for_retrosheet_columns():
    adapter = StatSqlAdapter(
        table="batting",
        columns={
            "H": '"b_h"',
            "BB": '"b_w"',
            "HBP": '"b_hbp"',
            "AB": '"b_ab"',
            "SF": '"b_sf"',
            "2B": '"b_d"',
            "3B": '"b_t"',
            "HR": '"b_hr"',
        },
    )

    expression = get_stat("OPS").aggregate_expression("rb", adapter=adapter)

    assert 'SUM(COALESCE(rb."b_h", 0)' in expression
    assert 'COALESCE(rb."b_w", 0)' in expression
    assert 'COALESCE(rb."b_d", 0)' in expression
    assert 'COALESCE(rb."b_t", 0)' in expression
    assert '4 * COALESCE(rb."b_hr", 0)' in expression
    assert "rb.H" not in expression


def test_registry_renders_avg_expression_for_retrosheet_columns():
    adapter = StatSqlAdapter(table="batting", columns={"H": '"b_h"', "AB": '"b_ab"'})

    expression = get_stat("AVG").expression("rb", adapter=adapter)

    assert expression == 'CAST(rb."b_h" AS DOUBLE) / NULLIF(rb."b_ab", 0)'


def test_registry_can_cast_string_backed_retrosheet_columns():
    adapter = StatSqlAdapter(
        table="batting",
        columns={"HR": '"b_hr"', "AB": '"b_ab"'},
        numeric_columns=True,
    )

    assert (
        get_stat("HR").aggregate_expression("rb", adapter=adapter)
        == 'SUM(TRY_CAST(rb."b_hr" AS DOUBLE))'
    )
    assert (
        get_stat("AVG").aggregate_sample_clause("rb", adapter=adapter)
        == 'SUM(TRY_CAST(rb."b_ab" AS DOUBLE)) >= 100'
    )


def test_registry_renders_sample_guards_for_retrosheet_columns():
    batting_adapter = StatSqlAdapter(table="batting", columns={"AB": '"b_ab"'})
    pitching_adapter = StatSqlAdapter(table="pitching", columns={"IPOUTS": '"p_ipouts"'})

    assert get_stat("AVG").sample_clause("rb", adapter=batting_adapter) == 'rb."b_ab" >= 100'
    assert get_stat("ERA").sample_clause("rp", adapter=pitching_adapter) == 'rp."p_ipouts" >= 300'
    assert (
        get_stat("AVG").aggregate_sample_clause("rb", adapter=batting_adapter)
        == 'SUM(rb."b_ab") >= 100'
    )
    assert (
        get_stat("WHIP").aggregate_sample_clause("rp", adapter=pitching_adapter)
        == 'SUM(rp."p_ipouts") >= 300'
    )


def test_registry_exposes_formula_notes_for_grounded_database_prompts():
    notes = stat_formula_notes()

    assert "batting: AVG =" in notes
    assert "batting: OPS =" in notes
    assert "minimum sample: AB >= 100" in notes
    assert "pitching: ERA" in notes
    assert "lower values rank better" in notes


def test_registry_infers_contextual_pitching_strikeouts():
    assert infer_stat_table("SO", text="struck out 200 batters as a pitcher") == "pitching"
    assert infer_stat_table("strikeouts", text="89 batting strikeouts") == "batting"
    assert infer_stat_table("SO", text="89 strikeouts") is None


def test_stat_mention_vocabulary_exposes_context_specific_views():
    from baseball_rag.stat_mentions import (
        for_biography_claims,
        for_narration_verification,
        for_routing,
        for_stat_definition_lookup,
    )

    routing = for_routing()
    biography_claims = for_biography_claims()
    narration = for_narration_verification()
    stat_definitions = for_stat_definition_lookup()

    assert routing.find_stat("who had the most RBIs in 1962") == "RBI"
    assert "walks" not in routing.aliases
    assert biography_claims.aliases["strikeouts"] == "SO"
    assert narration.aliases["walks"] == "BB"
    assert "walks" not in stat_definitions.aliases
    assert stat_definitions.find_stat("what is OPS") == "OPS"


def test_stat_mention_vocabulary_represents_contextual_strikeouts():
    from baseball_rag.stat_mentions import for_biography_claims

    vocabulary = for_biography_claims()

    assert vocabulary.infer_table("SO", text="struck out 200 batters as a pitcher") == "pitching"
    assert vocabulary.infer_table("strikeouts", text="89 batting strikeouts") == "batting"
    assert vocabulary.infer_table("SO", text="89 strikeouts") is None


def test_biography_claim_vocabulary_is_explicit_subset_of_sql_registry():
    claim_stats = supported_biography_claim_stats()

    assert claim_stats == ["AVG", "ERA", "H", "HR", "OPS", "PO", "RBI", "SB", "SO", "W", "WHIP"]
    assert set(claim_stats) < set(supported_stats())
    assert {"2B", "3B", "AB", "BB", "G", "GS", "L", "R", "SV"}.isdisjoint(claim_stats)

    aliases = biography_claim_stat_aliases()
    assert aliases["home runs"] == "HR"
    assert aliases["batting average"] == "AVG"
    assert aliases["putouts"] == "PO"


def test_biography_claim_vocabulary_builds_supplied_claim_regex_source():
    pattern = re.compile(rf"(?P<stat>{biography_claim_stat_regex_source()})\b", re.IGNORECASE)

    assert pattern.search("2,086 runs batted in").group("stat") == "runs batted in"
    assert pattern.search(".342 batting average").group("stat") == "batting average"
    assert pattern.search("302 putouts").group("stat") == "putouts"


def test_biography_claim_vocabulary_normalizes_every_supported_alias():
    for alias, canonical in biography_claim_stat_aliases().items():
        assert normalize_biography_claim_stat(alias) == canonical
        assert biography_claim_stat_definitions(alias)

    assert normalize_biography_claim_stat("home run") == "HR"
    assert normalize_biography_claim_stat("stolen base") == "SB"
    assert normalize_biography_claim_stat("hit") == "H"


def test_biography_claim_vocabulary_exposes_contextual_defs_and_retrosheet_columns():
    definitions = biography_claim_stat_definitions(
        "SO",
        text="struck out 200 batters as a pitcher",
    )

    assert definitions[0].table == "pitching"
    assert definitions[0].canonical == "SO"
    assert [definition.table for definition in definitions] == ["pitching", "batting"]
    assert retrosheet_stat_column_candidates("pitching", "SO") == ("p_k", "SO")
    assert retrosheet_stat_column_candidates("batting", "OPS") == ()
    assert {"H", "BB", "HBP", "AB", "SF", "2B", "3B", "HR"} <= set(
        retrosheet_adapter_stats("batting")
    )
