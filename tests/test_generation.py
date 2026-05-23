"""Tests for generation prompt helpers."""

from baseball_rag.generation.llm import _strip_reasoning_block
from baseball_rag.generation.prompt import (
    build_open_prompt,
)


class TestBuildOpenPrompt:
    """Tests for build_open_prompt — used for ungrounded open prose."""

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
        """Lines starting with * or - at the top are stripped."""
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
