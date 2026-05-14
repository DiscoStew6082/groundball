"""Tests for shared stat vocabulary."""

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


def test_registry_exposes_formula_notes_for_freeform_prompts():
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
