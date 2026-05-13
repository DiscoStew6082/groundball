"""LLM integration — calls local Gemma via LM Studio."""

import os
import re
from dataclasses import dataclass
from typing import Iterator, cast

import requests

from baseball_rag.arch.tracing import traced


class LLMError(Exception):
    """Base class for local LM integration failures."""


class LLMUnavailableError(LLMError, ConnectionError):
    """Raised when the configured LM server cannot be reached."""


class LLMTimeoutError(LLMError, TimeoutError):
    """Raised when the configured LM server does not answer in time."""


class LLMOutputError(LLMError, ValueError):
    """Raised when the LM returns an unusable output payload."""


class LLMEmptyOutputError(LLMOutputError):
    """Raised when the LM succeeds but provides no final answer text."""


class LLMMalformedResponseError(LLMOutputError):
    """Raised when the LM response is not OpenAI-chat-compatible."""


class LLMRoutingOutputError(LLMOutputError):
    """Raised when routing output cannot be parsed into the route schema."""


@dataclass
class LLMResponse:
    content: str
    model: str
    done: bool


DEFAULT_BASE_URL = "http://localhost:1234/v1"
DEFAULT_MODEL = "google/gemma-4-26b-a4b"
DEFAULT_TIMEOUT_SECONDS = 20.0


def _resolve_config(base_url: str | None, model: str | None) -> tuple[str, str]:
    """Resolve base_url and model, falling back to environment or defaults."""
    resolved_url = cast(str, base_url or os.environ.get("LMSTUDIO_BASE_URL", DEFAULT_BASE_URL))
    resolved_model = cast(str, model or os.environ.get("LMSTUDIO_MODEL", DEFAULT_MODEL))
    return resolved_url, resolved_model


def _build_payload(
    model: str,
    messages: list[dict],
    max_tokens: int,
    temperature: float,
    stream: bool = False,
) -> dict:
    """Build the common request payload for both streaming and non-streaming."""
    return {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": stream,
    }


def _resolve_timeout(timeout: float | None) -> float:
    if timeout is not None:
        return timeout
    raw_timeout = os.environ.get("LMSTUDIO_TIMEOUT_SECONDS")
    if raw_timeout:
        try:
            return float(raw_timeout)
        except ValueError:
            return DEFAULT_TIMEOUT_SECONDS
    return DEFAULT_TIMEOUT_SECONDS


def _post(base_url: str, payload: dict, timeout: float | None = None) -> requests.Response:
    """POST to the chat completions endpoint with a friendly error message."""
    resolved_timeout = _resolve_timeout(timeout)
    try:
        resp = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            timeout=resolved_timeout,
        )
        resp.raise_for_status()
        return resp
    except requests.Timeout as exc:
        raise LLMTimeoutError(
            f"LM Studio timed out after {resolved_timeout:g}s at {base_url}."
        ) from exc
    except requests.ConnectionError as exc:
        raise LLMUnavailableError(
            f"Could not connect to LM Studio at {base_url}. "
            "Is the server running? (Start LM Studio → Server tab → Start server)"
        ) from exc


def _strip_reasoning_block(text: str) -> str:
    """Strip Gemma 4's internal planning/scaffolding block and markdown fences.

    Gemma 4 produces thinking content in one of these formats depending on the backend:
      - <|channel>thought\\n...\\n<|channel|>   (vLLM / LM Studio default)
      - <|think|>...<|think|>                 (Ollama / some configs)

    This strips both so the caller gets clean content.
    """
    original = text

    # Remove surrounding markdown code fences first (e.g. ```sql ... ```)
    fence_match = re.match(r"^```[\w]*\s*\n?(.*?)\n?```$", text.strip(), re.DOTALL)
    if fence_match:
        return _strip_reasoning_block(fence_match.group(1).strip())

    # Strip <|channel>thought\n...\n<|channel|> blocks (vLLM / LM Studio)
    channel_match = re.search(
        r"<\|channel\>thought\s*\n.*?\n<\|channel\|>",
        text,
        re.DOTALL,
    )
    if channel_match:
        text = text.replace(channel_match.group(0), "").strip()

    # Strip <|think|>...<|think|> blocks (Ollama / other backends)
    think_match = re.search(
        r"<\|think\>\s*\n?.*?\n?<\|think\|>",
        text,
        re.DOTALL,
    )
    if think_match:
        text = text.replace(think_match.group(0), "").strip()

    # Strip leading reasoning block: lines starting with list markers
    # (fallback for any remaining structured prefix)
    lines = text.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith("*") or stripped.startswith("-") or stripped.startswith("`")):
            return "\n".join(lines[i:])
    return original


def _content_to_text(value: object) -> str:
    """Normalize OpenAI-compatible message content variants into text."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_content_to_text(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "reasoning_content"):
            text = _content_to_text(value.get(key))
            if text:
                return text
    return ""


def _message_content(choice: dict) -> str:
    content = _content_to_text(choice.get("content"))
    if content:
        return content
    return _content_to_text(choice.get("reasoning_content"))


@traced(component_id="llm", label="Generate Answer")
def make_request(
    prompt: str | tuple[str, str],
    base_url: str | None = None,
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> LLMResponse:
    """Send a chat-style prompt to LM Studio and return the response.

    Args:
        prompt: Either a plain string (backward compat — treated as user message only)
            or a (system_prompt, user_prompt) tuple for proper system+user structure.
        base_url: LM Studio server URL. Defaults to localhost:1234.
        model: Model name to specify in request.
        max_tokens: Max new tokens to generate.
        temperature: Sampling temperature (lower = more deterministic).

    Returns:
        LLMResponse with the generated text.

    Raises:
        ConnectionError: If LM Studio is not running at the given URL.
    """
    base_url, model = _resolve_config(base_url, model)

    if isinstance(prompt, tuple):
        system_prompt, user_prompt = prompt
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    else:
        messages = [{"role": "user", "content": prompt}]

    payload = _build_payload(model, messages, max_tokens, temperature)
    resp = _post(base_url, payload)

    try:
        data = resp.json()
        choice = data["choices"][0]["message"]
        if not isinstance(choice, dict):
            raise TypeError("message must be an object")
    except ValueError as exc:
        raise LLMMalformedResponseError("LM Studio returned malformed response JSON.") from exc
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMMalformedResponseError(
            "LM Studio returned a malformed chat completion response."
        ) from exc
    raw = _message_content(choice)
    content = _strip_reasoning_block(raw)
    if not content.strip():
        raise LLMEmptyOutputError("LM Studio returned an empty response.")

    return LLMResponse(content=content, model=data.get("model", model), done=True)


def make_request_stream(
    prompt: str | tuple[str, str],
    base_url: str | None = None,
    model: str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.3,
) -> Iterator[str]:
    """Streaming version — yields content tokens as they arrive."""
    base_url, model = _resolve_config(base_url, model)

    if isinstance(prompt, tuple):
        system_prompt, user_prompt = prompt
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
    else:
        messages = [{"role": "user", "content": prompt}]

    payload = _build_payload(model, messages, max_tokens, temperature, stream=True)
    resp = _post(base_url, payload)

    for line in resp.iter_lines(decode_unicode=True):
        if not line or line == "data: [DONE]":
            break
        if line.startswith("data: "):
            import json as _json

            chunk = _json.loads(line[6:])
            delta = chunk.get("choices", [{}])[0].get("delta", {})
            token = _content_to_text(delta.get("content")) + _content_to_text(
                delta.get("reasoning_content")
            )
            if token:
                yield token
