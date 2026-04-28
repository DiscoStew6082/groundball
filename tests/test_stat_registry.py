"""Tests for shared stat vocabulary."""

from baseball_rag.db.stat_registry import (
    find_stat_in_text,
    get_stat,
    normalize_stat,
    stat_aliases,
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
