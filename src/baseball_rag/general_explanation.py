"""General explanation policy for local definitions and open LLM answers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from baseball_rag.outcomes import llm_unavailable_outcome
from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.routing import GeneralExplanationCase


@dataclass(frozen=True)
class GeneralExplanationPolicy:
    """Answer routed general explanations behind one policy interface."""

    make_request: Callable[..., Any] | None = None
    stat_definitions_dir: Path | None = None

    def answer(
        self,
        decision: GeneralExplanationCase,
    ) -> StructuredAnswer:
        """Return a structured explanation without exposing the backing path."""
        question = decision.raw_question
        local_definition = self._answer_local_stat_definition(question)
        if local_definition is not None:
            return local_definition
        return self._answer_open_explanation(question, intent=decision.intent)

    def _answer_local_stat_definition(self, question: str) -> StructuredAnswer | None:
        from baseball_rag.corpus import STAT_DEFS_DIR
        from baseball_rag.corpus.static_vocab import stat_definition_doc_ids_for_query

        doc_ids = stat_definition_doc_ids_for_query(question)
        if not doc_ids:
            return None
        doc_id = doc_ids[0]
        stat_definitions_dir = self.stat_definitions_dir or STAT_DEFS_DIR
        path = stat_definitions_dir / f"{doc_id}.md"
        if not path.exists():
            return None

        text = _markdown_body(path.read_text(encoding="utf-8")).strip()
        first_paragraph = text.split("\n\n", 1)[0].strip()
        prefix = f"{doc_id} means {doc_id}."
        if doc_id == "RBI":
            prefix = "RBI means run batted in."
        answer_text = f"{prefix} {first_paragraph}"
        return StructuredAnswer(
            answer=answer_text,
            intent="general_explanation",
            sources=[
                SourceRecord(
                    type="stat_definition",
                    label=f"Local stat definition: {doc_id}",
                    detail=f"baseball_rag/corpus/stat_definitions/{doc_id}.md",
                    rows=[{"doc_id": doc_id}],
                )
            ],
        )

    def _answer_open_explanation(self, question: str, *, intent: str) -> StructuredAnswer:
        from baseball_rag.generation.prompt import build_open_prompt

        try:
            if self.make_request is None:
                from baseball_rag.generation.llm import make_request

                request = make_request
            else:
                request = self.make_request
            response = request(build_open_prompt(question), max_tokens=700)
        except (ConnectionError, TimeoutError) as exc:
            return _llm_unavailable(intent, exc)
        except Exception as exc:
            from baseball_rag.generation.llm import LLMError

            if isinstance(exc, LLMError):
                return _llm_unavailable(intent, exc)
            raise
        return StructuredAnswer(answer=response.content, intent=intent)


def _llm_unavailable(intent: str, exc: Exception) -> StructuredAnswer:
    return llm_unavailable_outcome(
        answer=(
            "LM Studio was unavailable, so no open explanation was generated. "
            "General explanation questions require the local LLM."
        ),
        intent=intent,
        warnings=[str(exc)],
    )


def _markdown_body(text: str) -> str:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text
