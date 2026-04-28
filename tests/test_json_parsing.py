"""Tests for shared JSON response parsing helpers."""

from baseball_rag.generation.json_parsing import extract_json_blocks, strip_markdown_fence


def test_strip_markdown_fence_with_language_tag():
    raw = '```json\n{"intent": "stat_query"}\n```'

    assert strip_markdown_fence(raw) == '{"intent": "stat_query"}'


def test_strip_markdown_fence_leaves_plain_text_stripped():
    assert strip_markdown_fence("  plain text  ") == "plain text"


def test_extract_json_blocks_finds_balanced_objects():
    raw = 'prefix {"a": {"b": 1}} middle {"c": 2} suffix'

    assert [raw[start:end] for start, end in extract_json_blocks(raw)] == [
        '{"a": {"b": 1}}',
        '{"c": 2}',
    ]


def test_extract_json_blocks_ignores_braces_in_strings():
    raw = 'prefix {"message": "literal } brace", "ok": true} suffix'

    assert [raw[start:end] for start, end in extract_json_blocks(raw)] == [
        '{"message": "literal } brace", "ok": true}'
    ]
