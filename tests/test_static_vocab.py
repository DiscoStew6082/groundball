"""Tests for static corpus vocabulary helpers."""

from baseball_rag.corpus.static_vocab import stat_definition_doc_ids_for_query


def test_stat_definition_doc_ids_for_query_deduplicates_aliases():
    assert stat_definition_doc_ids_for_query("what is OPS or on-base plus slugging") == ["OPS"]


def test_stat_definition_doc_ids_for_query_uses_token_boundaries():
    assert stat_definition_doc_ids_for_query("what is through baseball history") == []
    assert stat_definition_doc_ids_for_query("rabbit maranville biography") == []


def test_stat_definition_doc_ids_for_query_supports_plural_abbreviations():
    assert stat_definition_doc_ids_for_query("what are HRs and RBIs") == ["HR", "RBI"]
    assert stat_definition_doc_ids_for_query("explain BBs, SBs, POs, and WHIPs") == [
        "BB",
        "SB",
        "PO",
        "WHIP",
    ]
