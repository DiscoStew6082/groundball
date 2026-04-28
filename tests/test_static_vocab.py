"""Tests for static corpus vocabulary helpers."""

from baseball_rag.retrieval.static_vocab import (
    query_asks_for_explanation,
    query_mentions_stat_definition,
    stat_definition_doc_ids_for_query,
    static_doc_ids_for_query,
)


def test_stat_definition_doc_ids_for_query_deduplicates_aliases():
    assert stat_definition_doc_ids_for_query("what is OPS or on-base plus slugging") == ["OPS"]


def test_static_doc_ids_for_query_includes_hof_bios_and_stat_definitions():
    assert static_doc_ids_for_query("compare Babe Ruth and home runs") == ["HR", "Babe_Ruth"]


def test_query_mentions_stat_definition():
    assert query_mentions_stat_definition("explain WHIP")
    assert not query_mentions_stat_definition("who was Babe Ruth")


def test_query_asks_for_explanation():
    assert query_asks_for_explanation("what does RBI mean")
    assert not query_asks_for_explanation("career RBI leaders")
