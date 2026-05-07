"""Tests for FastAPI server — Phases 7.1 and 7.2."""

from fastapi.testclient import TestClient

from baseball_rag.api.server import app

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
