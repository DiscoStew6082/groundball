"""Prompt templates for RAG-grounded answer generation."""

from dataclasses import dataclass


@dataclass
class PromptBundle:
    system: str
    user: str

    def render(self) -> tuple[str, str]:
        """Return (system_prompt, user_prompt) tuple for separate message fields."""
        return self.system, self.user


_BASE_ANSWER_TEMPLATE = PromptBundle(
    system=(
        "You are a knowledgeable baseball historian. Answer the user's question "
        "using ONLY the provided context documents.\n"
        "Do not include planning notes, internal monologue, task lists, or any structured "
        "reasoning markup (no lines starting with *, -, or `) in your response. "
        "Answer directly and concisely.\n"
        "Cite each piece of information by referencing the source document title in brackets."
    ),
    user=("Use the following documents to answer:\n\n{context}\n\n---\n\nQuestion: {question}"),
)


def build_stat_query_prompt(question: str, context_docs: list) -> tuple[str, str]:
    """Render a stat query prompt with retrieved document context."""
    return build_grounded_prompt(question, context_docs)


def build_explanation_prompt(question: str, context_docs: list) -> tuple[str, str]:
    """Render a general explanation prompt with retrieved document context."""
    return build_grounded_prompt(question, context_docs)


def build_player_bio_prompt(question: str, context_docs: list) -> tuple[str, str]:
    """Render a player biography prompt with retrieved document context."""
    return build_grounded_prompt(question, context_docs)


def build_grounded_prompt(question: str, context_docs: list) -> tuple[str, str]:
    """Render a grounded answer prompt with retrieved document context."""
    ctx = "\n\n".join(f"[Source: {d.title}]\n{d.text}" for d in context_docs)
    return _BASE_ANSWER_TEMPLATE.render()[0], _BASE_ANSWER_TEMPLATE.user.format(
        context=ctx, question=question
    )


def build_open_prompt(question: str) -> tuple[str, str]:
    """Render a prompt with NO retrieved context — LLM answers from its own knowledge.

    Use when the corpus returned no relevant documents.
    The LLM should answer directly and honestly note if stats/data are involved.
    """
    return (
        "You are a knowledgeable baseball historian. Answer the question directly "
        "using your own knowledge.\n"
        "Do not include planning notes, internal monologue, or any structured reasoning markup "
        "(no lines starting with *, -, or bullet points) in your response.\n"
        "If the question asks for specific statistics or data from a database, "
        "say you don't have access to that information.",
        f"Question: {question}",
    )
