"""Tests for FastAPI server — Phases 7.1 and 7.2."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from baseball_rag.api.server import app
from baseball_rag.provenance import StructuredAnswer

client = TestClient(app)


class TestApi:
    def test_health_endpoint(self):
        """GET /health returns 200 with {"status": "ok"}."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_query_endpoint_returns_answer(self, caplog):
        """POST /query with JSON body returns {answer: str, sources: list}."""
        # Note: This will call the real cli.answer(). If ChromaDB isn't indexed,
        # it returns a fallback message — that's fine.
        caplog.set_level("INFO", logger="baseball_rag.api.server")

        response = client.post("/query", json={"question": "who had the most RBIs in 1962"})
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data
        assert isinstance(data["answer"], str)
        assert data["intent"] == "stat_query"
        assert "sources" in data
        assert isinstance(data["sources"], list)
        assert data["sources"]
        assert data["sources"][0]["type"] == "duckdb"
        assert data["sources"][0]["data_manifest"]["dataset"]["name"] == "NeuML/baseballdata"
        assert "warnings" in data
        assert data["unsupported"] is False
        assert data["unsupported_reason"] is None
        assert data["review_reason"] is None
        assert data["sources"][0]["sql"]
        assert data["metadata"]["route"] == "stat_query"
        assert data["metadata"]["unsupported"] is False
        assert data["metadata"]["latency_ms"] >= 0
        assert data["metadata"]["sql_visible"] is True
        assert data["metadata"]["source_count"] == 1
        assert data["metadata"]["source_types"] == ["duckdb"]
        assert data["metadata"]["trace"]["route_type"] == "stat_query"
        assert data["metadata"]["trace"]["stages"]
        assert data["metadata"]["trace"]["stages"][0]["component_id"] == "api"
        assert data["metadata"]["query_id"].startswith("q_")
        assert data["metadata"]["timestamp"]
        assert data["metadata"]["unsupported_reason"] is None
        assert data["metadata"]["sql"]["template_hash"].startswith("sha256:")
        assert data["metadata"]["sql"]["row_count"] >= 1
        assert data["metadata"]["model"]["prompt_version"] == "grounded-answer-v1"
        assert data["metadata"]["dataset"]["name"] == "NeuML/baseballdata"
        assert data["metadata"]["eval"]["case_id"] == "stat_rbi_1962"
        assert data["review"] is None

        audit_records = [record for record in caplog.records if record.message == "query_audit"]
        assert len(audit_records) == 1
        audit = audit_records[0].audit
        assert audit["route"] == "stat_query"
        assert audit["unsupported"] is False
        assert audit["sql_visible"] is True
        assert audit["latency_ms"] >= 0
        assert audit["query_id"] == data["metadata"]["query_id"]

    def test_query_endpoint_accepts_conversation_context(self):
        """API callers can continue a grounded conversation across turns."""
        prior_turns = [
            {
                "question": "career home run leaders",
                "answer": {
                    "answer": "All-time career HR leaders",
                    "intent": "stat_query",
                    "sources": [
                        {
                            "type": "duckdb",
                            "label": "Career HR leaders",
                            "rows": [{"name": "Bonds, Barry"}, {"name": "Aaron, Hank"}],
                        }
                    ],
                },
            }
        ]

        class FakeExecution:
            answer = StructuredAnswer(answer="Hank Aaron bio", intent="player_biography")

        with patch("baseball_rag.request_execution.execute_request") as execute:
            execute.return_value = FakeExecution()

            response = client.post(
                "/query",
                json={
                    "question": "tell me about the second player",
                    "conversation": prior_turns,
                },
            )

        assert response.status_code == 200
        execute.assert_called_once()
        assert execute.call_args.kwargs["conversation"] == prior_turns
        assert response.json()["answer"] == "Hank Aaron bio"

    def test_query_endpoint_surfaces_review_item_for_unsupported_answer(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post(
            "/query",
            json={"question": "how many HRs did Totally Fakeplayer have in 2022"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "no_data"
        assert data["review_reason"] is None
        assert data["review"]["queued"] is True
        assert data["review"]["reason"] == "unsupported"
        assert data["review"]["item_id"].startswith("review_")

        queue_response = client.get("/review-queue")
        assert queue_response.status_code == 200
        queue = queue_response.json()
        assert queue["count"] == 1
        assert queue["items"][0]["id"] == data["review"]["item_id"]

    def test_query_endpoint_preserves_ambiguous_freeform_unsupported_reason(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post("/query", json={"question": "who is in the 500 club"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "freeform_query"
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "ambiguous"
        assert data["review_reason"] == "ambiguous"
        assert data["metadata"]["unsupported_reason"] == "ambiguous"
        assert data["review"]["queued"] is True
        assert data["review"]["reason"] == "ambiguous"

    def test_query_endpoint_rejects_reversed_stat_year_range(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post(
            "/query",
            json={"question": "who had most RBIs between 1980-1970"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "ambiguous"
        assert data["review"]["reason"] == "ambiguous"
        assert "1980-1970" in data["answer"]

    def test_query_endpoint_rejects_years_outside_structured_coverage(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post(
            "/query",
            json={"question": "who had the most HRs in 2026"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "no_data"
        assert data["review"]["reason"] == "unsupported"
        assert "1871-2025" in data["answer"]

    def test_query_endpoint_rejects_bare_current_century_decade(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post("/query", json={"question": "most HRs in the 20s"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "ambiguous"
        assert data["review"]["reason"] == "ambiguous"
        assert "20s" in data["answer"]

    def test_query_endpoint_allows_explicit_historical_decade(self):
        response = client.post("/query", json={"question": "most HRs in the 1920s"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is False
        assert "Top HR leaders (1920-1929):" in data["answer"]
        assert "Ruth, Babe: 467 HR" in data["answer"]

    def test_query_endpoint_resolves_relative_last_year_from_configured_clock(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))
        monkeypatch.setenv("BASEBALL_RAG_CURRENT_YEAR", "2025")

        response = client.post(
            "/query",
            json={"question": "how many HRs did Aaron Judge have last year"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is False
        assert data["review"] is None
        assert "Judge, Aaron" in data["answer"]
        assert "(2024): 58 HR" in data["answer"]

    def test_query_endpoint_preserves_pitching_rate_stat_provenance(self):
        response = client.post("/query", json={"question": "lowest ERA in 1968"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is False
        source = data["sources"][0]
        assert source["type"] == "duckdb"
        assert source["rows"][0]["name"] == "Gibson, Bob"
        assert "FROM pitching pi" in source["sql"]
        assert "SUM(pi.IPouts) >= 300" in source["sql"]
        assert "ORDER BY stat_value ASC" in source["sql"]

    def test_query_endpoint_rejects_ambiguous_last_name_player_stat(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post(
            "/query",
            json={"question": "how many home runs did Williams have in 1941"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "ambiguous"
        assert data["review_reason"] == "ambiguous"
        assert data["review"]["reason"] == "ambiguous"

    def test_query_endpoint_handles_accented_suffix_player_stat(self):
        response = client.post(
            "/query",
            json={"question": "how many HRs did Ronald Acuña Jr. have in 2023"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is False
        assert "Acuña, Ronald" in data["answer"]
        assert "(2023): 41 HR" in data["answer"]

    def test_query_endpoint_handles_possessive_player_stat_with_leading_words(self):
        response = client.post("/query", json={"question": "what is Aaron Judge's HR in 2024"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "stat_query"
        assert data["unsupported"] is False
        assert "Judge, Aaron" in data["answer"]
        assert "(2024): 58 HR" in data["answer"]

    def test_review_queue_endpoint_resolves_item(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))
        response = client.post(
            "/query",
            json={"question": "how many HRs did Totally Fakeplayer have in 2022"},
        )
        item_id = response.json()["review"]["item_id"]

        patch_response = client.patch(
            f"/review-queue/{item_id}",
            json={"status": "resolved", "note": "expected unsupported guardrail"},
        )

        assert patch_response.status_code == 200
        assert patch_response.json()["item"]["status"] == "resolved"
        assert client.get("/review-queue").json()["items"] == []
        all_items = client.get("/review-queue", params={"status": "all"}).json()["items"]
        assert all_items[0]["resolution_note"] == "expected unsupported guardrail"

    def test_review_queue_endpoint_returns_404_for_missing_item(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.patch("/review-queue/review_missing", json={"status": "resolved"})

        assert response.status_code == 404

    def test_sources_endpoint_returns_manifest(self):
        response = client.get("/sources")
        assert response.status_code == 200
        data = response.json()
        assert data["dataset"]["name"] == "NeuML/baseballdata"
        assert data["files"]
        assert data["files"][0]["sha256"]

    def test_evals_report_endpoint_returns_deterministic_report(self):
        response = client.get("/evals/report")

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["include_live"] is False
        assert data["summary"]["attempted"] == 20
        assert data["summary"]["recommendation"] in {"PASS", "WARN"}
        assert data["markdown"].startswith("# Baseball RAG Eval Report")

    def test_evals_run_rejects_live_options_without_opt_in(self):
        response = client.post("/evals/run", json={"retrieval_only": True})

        assert response.status_code == 400
        assert "include_live=true" in response.json()["detail"]

    def test_evals_run_default_matches_ci_gate(self):
        response = client.post("/evals/run", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["options"]["include_live"] is False
        assert data["summary"]["attempted"] == 20
        assert data["results"]["failed"] == []

    def test_guardrails_coverage_endpoint_is_manifest_only(self):
        response = client.get("/guardrails/coverage")

        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["unsupported_guardrails"] >= 1
        assert data["categories"]["unsupported"]
        assert data["markdown"].startswith("# Baseball RAG Guardrail Coverage")
