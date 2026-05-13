"""Tests for the query UI transaction lifecycle."""

from baseball_rag.provenance import SourceRecord, StructuredAnswer
from baseball_rag.request_execution import RequestExecution
from baseball_rag.ui.query_transaction import QueryTransaction


def test_transaction_clears_stale_outputs_then_completes_pending_query():
    """A submitted query clears current details before publishing the final answer."""
    calls = []
    prior_chat = [{"role": "assistant", "content": "old answer"}]
    prior_conversation = [{"question": "old query", "answer": {"sources": []}}]

    def execute(question, *, conversation):
        calls.append((question, conversation))
        return RequestExecution(
            answer=StructuredAnswer(
                answer=f"answered {question}",
                intent="stat_query",
                sources=[
                    SourceRecord(
                        type="duckdb",
                        label="RBI leaders",
                        columns=["name", "stat_value"],
                        rows=[{"name": "Davis, Tommy", "stat_value": 153}],
                    )
                ],
            ),
            trace=None,
        )

    transaction = QueryTransaction(
        execute=execute,
        default_question="who had the most RBIs in 1962",
    )

    pending = transaction.begin("who had the most RBIs in 1962", prior_chat, prior_conversation)

    assert pending.update.status == "pending"
    assert pending.update.answer_text == ""
    assert pending.update.rows == []
    assert pending.update.sources == []
    assert pending.update.sql == ""
    assert pending.update.chat_history == prior_chat
    assert pending.update.conversation == prior_conversation

    completed = transaction.complete(pending.pending)

    assert completed.status == "completed"
    assert calls == [("who had the most RBIs in 1962", prior_conversation)]
    assert completed.answer_text == "answered who had the most RBIs in 1962"
    assert completed.rows == {
        "headers": ["name", "stat_value"],
        "data": [["Davis, Tommy", 153]],
    }
    assert completed.chat_history[-2:] == [
        {"role": "user", "content": "who had the most RBIs in 1962"},
        {"role": "assistant", "content": "answered who had the most RBIs in 1962"},
    ]
    assert completed.visible_chat_history == completed.chat_history
    assert completed.visible_chat_history is not completed.chat_history
    assert completed.conversation[-1]["question"] == "who had the most RBIs in 1962"


def test_transaction_ignores_blank_message_and_restores_default_question():
    """Blank submissions do not execute and return a runnable textbox default."""
    calls = []
    prior_chat = [{"role": "assistant", "content": "old answer"}]
    prior_conversation = [{"question": "old query", "answer": {"sources": []}}]

    transaction = QueryTransaction(
        execute=lambda question, *, conversation: calls.append((question, conversation)),
        default_question="who had the most RBIs in 1962",
    )

    update = transaction.run("   ", prior_chat, prior_conversation)

    assert calls == []
    assert update.status == "idle"
    assert update.question == "who had the most RBIs in 1962"
    assert update.answer_text == ""
    assert update.rows == []
    assert update.sources == []
    assert update.sql == ""
    assert update.chat_history == prior_chat
    assert update.conversation == prior_conversation


def test_transaction_returns_visible_failure_without_stale_outputs():
    """A request failure becomes a failed visible state with cleared detail panels."""

    def execute(_question, *, conversation):
        raise TimeoutError("slow")

    transaction = QueryTransaction(
        execute=execute,
        default_question="who had the most RBIs in 1962",
    )

    update = transaction.run("what is OPS", [], [])

    assert update.status == "failed"
    assert "timed out" in update.answer_text.lower()
    assert update.rows == []
    assert update.sources == []
    assert update.sql == ""
    assert update.chat_history[-2:] == [
        {"role": "user", "content": "what is OPS"},
        {"role": "assistant", "content": f"{update.answer_text}\n\nWarning: slow"},
    ]


def test_transaction_returns_visible_failure_for_runtime_errors():
    """Runtime execution failures should not escape and strand UI controls."""

    def execute(_question, *, conversation):
        raise RuntimeError("query failed")

    transaction = QueryTransaction(
        execute=execute,
        default_question="who had the most RBIs in 1962",
    )

    update = transaction.run("who played for the Braves in 1936", [], [])

    assert update.status == "failed"
    assert "could not return an answer" in update.answer_text
    assert update.rows == []
    assert update.sources == []
    assert update.sql == ""
    assert update.chat_history[-1]["content"] == f"{update.answer_text}\n\nWarning: query failed"
