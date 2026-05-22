"""Public answer() API — Generation layer entry point."""

from typing import Any

from baseball_rag.generation.prompt import build_explanation_prompt


def answer(question: str, chunks: list[Any]) -> str:
    """Generate an answer to a question given explicit context chunks."""
    prompt = build_explanation_prompt(question, chunks)
    try:
        from baseball_rag.generation.llm import make_request

        response = make_request(prompt)
        return response.content
    except ConnectionError:
        lines = ["(LM Studio not running - showing relevant documents instead):\n"]
        for chunk in chunks[:3]:
            lines.append(f"[{chunk.title}]\n{chunk.text}\n")
        return "\n".join(lines)
