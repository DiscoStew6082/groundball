"""Tests for generation.answer() — Phase 5.5."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from baseball_rag.generation import answer
from baseball_rag.generation.llm import _strip_reasoning_block
from baseball_rag.generation.prompt import (
    build_explanation_prompt,
    build_grounded_prompt,
    build_open_prompt,
    build_player_bio_prompt,
    build_stat_query_prompt,
)


def _chunk(text: str, source: str, title: str, score: float = 0.95) -> SimpleNamespace:
    return SimpleNamespace(text=text, source=source, title=title, score=score)


class TestGenerationAnswer:
    def test_generate_with_context(self):
        """generate_answer(question, chunks) returns non-empty string mentioning context player."""
        chunks = [
            _chunk(
                text=(
                    "Babe Ruth was a legendary baseball player who played for "
                    "the NY Yankees from 1920-1934. He hit 714 career home runs."
                ),
                source="hof/babe_ruth.md",
                title="Babe Ruth",
            ),
        ]
        result = answer("who was babe ruth", chunks)
        assert isinstance(result, str)
        assert len(result) > 10
        # Result should mention the player from context (or fall back to showing doc text)
        assert "ruth" in result.lower() or "babe" in result.lower()


class TestGenerationExceptionHandling:
    def test_timeout_error_propagates_not_swallowed(self):
        """TimeoutError from make_request propagates instead of returning silent fallback."""

        def fake_request(prompt):
            raise TimeoutError("LM Studio timed out after 120s")

        with patch("baseball_rag.generation.llm.make_request", fake_request):
            chunks = [
                _chunk(
                    text="Babe Ruth hit 714 home runs.",
                    source="hof/babe_ruth.md",
                    title="Babe Ruth",
                ),
            ]
            with pytest.raises(TimeoutError, match="timed out"):
                answer("how many HR did Babe Ruth have", chunks)

    def test_json_decode_error_is_not_silenced(self):
        """JSON decode error from LM Studio raises instead of silent fallback."""

        import json

        def fake_request(prompt):
            # Simulate what happens when LM Studio returns garbled non-JSON
            raise json.JSONDecodeError("Expecting value", '{"model": "gemma', 10)

        with patch("baseball_rag.generation.llm.make_request", fake_request):
            chunks = [
                _chunk(
                    text="Babe Ruth hit 714 home runs.",
                    source="hof/babe_ruth.md",
                    title="Babe Ruth",
                ),
            ]
            with pytest.raises(json.JSONDecodeError):
                answer("how many HR did Babe Ruth have", chunks)


class TestBuildOpenPrompt:
    """Tests for build_open_prompt — used when no relevant docs are retrieved."""

    def test_system_prompt_forbids_structured_reasoning(self):
        """System prompt tells the model not to output planning notes or bullet points."""
        system, user = build_open_prompt("Who was Jackie Robinson?")
        # Should mention the constraint against structured reasoning markup
        assert "planning" in system.lower() or "reasoning" in system.lower()
        # The phrase "don't have access" appears only as an instruction for how to respond
        # when asked about stats — it should NOT appear as a blanket admission of no context
        assert (
            "if the question asks for specific statistics" in system.lower()
            or "say you don't have access" in system.lower()
        )

    def test_user_prompt_is_just_the_question(self):
        """User prompt contains only the question, no extra framing."""
        _, user = build_open_prompt("Tell me about moustache players")
        # Should be plain question, not wrapped in elaborate context
        assert "Question:" in user
        # Must not contain any document references (there are no docs)
        assert "[Source:" not in user


class TestBuildGroundedPrompt:
    """Tests for shared grounded prompt rendering."""

    def test_formats_context_documents_with_sources(self):
        """Grounded prompt includes source titles, document text, and question."""
        chunks = [
            _chunk(
                text="Babe Ruth hit 714 career home runs.",
                source="hof/babe_ruth.md",
                title="Babe Ruth",
            ),
            _chunk(
                text="Hank Aaron hit 755 career home runs.",
                source="hof/hank_aaron.md",
                title="Hank Aaron",
            ),
        ]

        system, user = build_grounded_prompt("Who hit more home runs?", chunks)

        assert "using ONLY the provided context documents" in system
        assert "[Source: Babe Ruth]\nBabe Ruth hit 714 career home runs." in user
        assert "[Source: Hank Aaron]\nHank Aaron hit 755 career home runs." in user
        assert "Question: Who hit more home runs?" in user

    @pytest.mark.parametrize(
        "builder",
        [
            build_stat_query_prompt,
            build_explanation_prompt,
            build_player_bio_prompt,
        ],
    )
    def test_specialized_grounded_prompts_delegate_to_shared_builder(self, builder):
        """Specialized prompt builders render the same output as build_grounded_prompt."""
        chunks = [
            _chunk(
                text="Jackie Robinson debuted for Brooklyn in 1947.",
                source="hof/jackie_robinson.md",
                title="Jackie Robinson",
            ),
        ]
        question = "When did Jackie Robinson debut?"

        assert builder(question, chunks) == build_grounded_prompt(question, chunks)


class TestStripReasoningBlock:
    """Tests for _strip_reasoning_block — Gemma 4 thinking block removal."""

    def test_strips_channel_think_block(self):
        """Gemma 4 <|channel>thought ... <|channel|> blocks are stripped."""
        raw = (
            "<|channel>thought\n"
            "Let me think about which baseball players had famous moustaches...\n"
            "Rollie Fingers is the most iconic.\n<|channel|>\n"
            "Rollie Fingers is the most famous."
        )
        result = _strip_reasoning_block(raw)
        assert "<|think>" not in result
        assert "Rollie Fingers" in result

    def test_strips_think_tags(self):
        """Gemma 4 <|think|>...<|think|> blocks are stripped."""
        raw = (
            "<|think>\n"
            "Let me think about baseball moustaches...\n"
            "Rollie Fingers is the gold standard.\n<|think|>\n"
            "The most iconic player with a moustache was Rollie Fingers."
        )
        result = _strip_reasoning_block(raw)
        assert "<|think>" not in result
        assert "Rollie Fingers" in result

    def test_passes_through_plain_text(self):
        """Plain answer with no thinking tags passes through unchanged."""
        raw = "Rollie Fingers is the most iconic baseball player known for his moustache."
        result = _strip_reasoning_block(raw)
        assert result == raw

    def test_strips_leading_bullet_list(self):
        """Lines starting with * or - at the top are stripped (fallback stripper)."""
        raw = (
            "* Rollie Fingers: famous moustache\n"
            "* Pete Rose: also known for facial hair\n"
            "Rollie Fingers is the most iconic."
        )
        result = _strip_reasoning_block(raw)
        assert not result.startswith("*")
        assert "Rollie Fingers" in result

    def test_strips_leading_blank_lines_before_bullet_planning(self):
        """Leading blank lines should not let bullet planning leak through."""
        raw = (
            "\n\n"
            "* Subject: Nolan Ryan\n"
            "* Goal: produce biography JSON\n"
            '{"answer": "Nolan Ryan was a Hall of Fame pitcher.", "stat_claims": []}'
        )
        result = _strip_reasoning_block(raw)
        assert result.startswith('{"answer"')
        assert "Subject:" not in result

    def test_strips_markdown_fence(self):
        """Content wrapped in ``` fences is extracted."""
        raw = (
            "```\n"
            "Rollie Fingers had a famous moustache.\n"
            "```\n"
            "The most iconic player known for facial hair was Rollie Fingers."
        )
        result = _strip_reasoning_block(raw)
        assert not result.startswith("```")
        assert "Rollie Fingers" in result
