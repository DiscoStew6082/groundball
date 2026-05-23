"""Tests for static corpus vocabulary helpers."""

from baseball_rag.retrieval.static_vocab import stat_definition_doc_ids_for_query


def test_stat_definition_doc_ids_for_query_deduplicates_aliases():
    assert stat_definition_doc_ids_for_query("what is OPS or on-base plus slugging") == ["OPS"]
