"""Tests for LLM client — mocked since LM Studio may not be running."""

from unittest.mock import MagicMock, patch

import pytest

from baseball_rag.generation.llm import make_request, make_request_stream


class TestLLMClient:
    def test_generate_returns_text(self):
        """make_request returns an LLMResponse with non-empty content."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Mickey Mantle had 123 RBI in 1962."}}],
            "model": "gemma-4-26b",
        }

        with patch("requests.post", return_value=mock_resp):
            result = make_request("who had most RBIs in 1962")

        assert isinstance(result.content, str)
        assert len(result.content) > 0
        assert result.model == "gemma-4-26b"

    def test_connection_error_raises(self):
        """ConnectionError is raised when LM Studio is not running."""
        import requests

        with patch("requests.post", side_effect=requests.ConnectionError("connection refused")):
            with pytest.raises(ConnectionError, match="Could not connect"):
                make_request("test query")

    def test_timeout_uses_short_default_and_raises_timeout_error(self):
        """LM Studio stalls should fail quickly enough for web requests to recover."""
        import requests

        with patch("requests.post", side_effect=requests.Timeout("read timed out")) as mock_post:
            with pytest.raises(TimeoutError, match="timed out"):
                make_request("test query")

        assert mock_post.call_args.kwargs["timeout"] == 20.0

    def test_timeout_can_be_overridden_by_env(self, monkeypatch):
        """Local deployments can tune the LM Studio timeout."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Answer."}}],
            "model": "gemma-4-26b",
        }
        monkeypatch.setenv("LMSTUDIO_TIMEOUT_SECONDS", "3.5")

        with patch("requests.post", return_value=mock_resp) as mock_post:
            make_request("test query")

        assert mock_post.call_args.kwargs["timeout"] == 3.5

    def test_tuple_prompt_sends_system_and_user(self):
        """A (system, user) tuple is sent as separate message roles."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Answer."}}],
            "model": "gemma-4-26b",
        }

        with patch("requests.post", return_value=mock_resp) as mock_post:
            result = make_request(("You are a historian.", "Who was Babe Ruth?"))

        call_kwargs = mock_post.call_args[1]
        messages = call_kwargs["json"]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are a historian."
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "Who was Babe Ruth?"
        assert result.content == "Answer."

    def test_stream_yields_chunks(self):
        """make_request_stream yields tokens as they arrive."""
        lines = [
            'data: {"choices":[{"delta":{"content":"Mickey"}}]}',
            'data: {"choices":[{"delta":{"content":" Mantle"}}]}',
            "data: [DONE]",
        ]
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(lines)

        with patch("requests.post", return_value=mock_resp):
            tokens = list(make_request_stream("who had most RBIs"))

        assert "Mickey" in tokens
        # Note: token may include leading space from SSE delta
        assert any("Mantle" in t for t in tokens)

    def test_stream_with_tuple_prompt(self):
        """make_request_stream also supports (system, user) tuple prompts."""
        lines = ['data: {"choices":[{"delta":{"content":"Answer."}}]}', "data: [DONE]"]
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.iter_lines.return_value = iter(lines)

        with patch("requests.post", return_value=mock_resp) as mock_post:
            tokens = list(make_request_stream(("You are a historian.", "Who was Babe Ruth?")))

        call_kwargs = mock_post.call_args[1]
        messages = call_kwargs["json"]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "".join(tokens) == "Answer."
