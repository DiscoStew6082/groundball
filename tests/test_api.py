"""Tests for FastAPI server — Phases 7.1 and 7.2."""

from unittest.mock import patch

import pytest
import requests
from fastapi.testclient import TestClient

from baseball_rag.api.server import app
from baseball_rag.arch.components import TestStatus
from baseball_rag.arch.test_status import ArchitectureTestStatusResult
from baseball_rag.generation.llm import LLMResponse
from baseball_rag.provenance import StructuredAnswer

client = TestClient(app)
WEBSITE_CORS_ORIGINS = "https://discostew.dev,http://localhost:4321,http://127.0.0.1:4321"


@pytest.fixture(autouse=True)
def website_cors_origins(monkeypatch):
    monkeypatch.setenv("GROUNDBALL_CORS_ORIGINS", WEBSITE_CORS_ORIGINS)
    monkeypatch.delenv("GROUNDBALL_ORIGIN_PROXY_TOKEN", raising=False)


class TestApi:
    def test_capabilities_report_public_server_owned_features(self, monkeypatch):
        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")

        response = client.get("/api/capabilities")

        assert response.status_code == 200
        assert response.json() == {
            "name": "Ground Ball",
            "mode": "public",
            "query": True,
            "llm": False,
            "architecture": False,
            "developer_tools": False,
            "history": "browser_local",
        }

    def test_capabilities_report_local_server_owned_features(self, monkeypatch):
        monkeypatch.delenv("GROUNDBALL_PUBLIC_DEMO", raising=False)

        response = client.get("/api/capabilities")

        assert response.status_code == 200
        assert response.json() == {
            "name": "Ground Ball",
            "mode": "local",
            "query": True,
            "llm": True,
            "architecture": True,
            "developer_tools": True,
            "history": "browser_local",
        }

    def test_local_capabilities_can_disable_unavailable_container_tools(self, monkeypatch):
        monkeypatch.delenv("GROUNDBALL_PUBLIC_DEMO", raising=False)
        monkeypatch.setenv("GROUNDBALL_ARCHITECTURE_ENABLED", "0")
        monkeypatch.setenv("GROUNDBALL_DEVELOPER_TOOLS_ENABLED", "0")

        response = client.get("/api/capabilities")

        assert response.status_code == 200
        assert response.json()["architecture"] is False
        assert response.json()["developer_tools"] is False
        assert client.get("/api/architecture").status_code == 404
        assert client.post("/api/developer/tests").status_code == 404

    def test_public_api_query_is_self_contained_and_never_calls_network(self, monkeypatch):
        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")

        def deny_network(*_args, **_kwargs):
            raise AssertionError("public API query attempted outbound network access")

        monkeypatch.setattr(requests.sessions.Session, "request", deny_network)

        response = client.post(
            "/api/query",
            json={"question": "who had the most RBIs in 1962"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["intent"] == "stat_query"
        assert "Davis, Tommy: 153 RBI" in data["answer"]
        assert data["rows"]["headers"]
        assert data["rows"]["data"][0][0] == "Davis, Tommy"
        assert data["sources"][0]["type"] == "duckdb"
        assert data["sql"]
        assert data["unsupported"] is False
        assert data["metadata"]["public_demo"] is True
        assert data["conversation_turn"]["question"] == "who had the most RBIs in 1962"
        assert data["architecture_trace"] is None

    @pytest.mark.parametrize("path", ["/query", "/api/query"])
    def test_public_query_routes_reject_llm_flavored_mode(self, path, monkeypatch):
        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "true")

        response = client.post(
            path,
            json={"question": "who had the most RBIs in 1962", "answer_mode": "llm_flavored"},
        )

        assert response.status_code == 422
        assert "public demo supports only" in response.json()["detail"]

    @pytest.mark.parametrize("path", ["/query", "/api/query"])
    def test_public_query_routes_fail_closed_for_llm_questions(self, path, monkeypatch):
        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")

        def deny_network(*_args, **_kwargs):
            raise AssertionError("public query attempted outbound network access")

        monkeypatch.setattr(requests.sessions.Session, "request", deny_network)

        response = client.post(path, json={"question": "who was Babe Ruth"})

        assert response.status_code == 200
        data = response.json()
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "llm_unavailable"

    @pytest.mark.parametrize("public_demo", [False, True])
    @pytest.mark.parametrize(
        "payload",
        [
            {"question": "x" * 501},
            {
                "question": "who had the most RBIs in 1962",
                "conversation": [{"question": "q", "answer": "a"}] * 21,
            },
        ],
    )
    def test_query_request_bounds_are_enforced(self, public_demo, payload, monkeypatch):
        if public_demo:
            monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
        else:
            monkeypatch.delenv("GROUNDBALL_PUBLIC_DEMO", raising=False)

        response = client.post("/api/query", json=payload)

        assert response.status_code == 422

    def test_architecture_catalog_is_local_and_rendering_neutral(self, monkeypatch):
        monkeypatch.delenv("GROUNDBALL_PUBLIC_DEMO", raising=False)

        response = client.get("/api/architecture")

        assert response.status_code == 200
        components = response.json()["components"]
        web_app = next(component for component in components if component["id"] == "web-app")
        assert web_app == {
            "id": "web-app",
            "label": "Svelte Web App",
            "description": "Unified browser app for questions, evidence, and architecture traces.",
            "layer": "api",
            "test_status": None,
        }
        assert all("file_path" not in component for component in components)

        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
        assert client.get("/api/architecture").status_code == 404

    def test_architecture_component_detail_is_local_only(self, monkeypatch):
        monkeypatch.delenv("GROUNDBALL_PUBLIC_DEMO", raising=False)

        response = client.get("/api/architecture/query-router")

        assert response.status_code == 200
        data = response.json()
        assert data["component"]["id"] == "query-router"
        assert data["component"]["file_path"] == "src/baseball_rag/routing/query_router.py"
        assert "Query routing" in data["source_excerpt"]

        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
        public_response = client.get("/api/architecture/query-router")
        assert public_response.status_code == 404

    def test_developer_test_action_is_fixed_and_local_only(self, monkeypatch):
        result = ArchitectureTestStatusResult(
            passed=3,
            failed=0,
            component_statuses={"query-router": TestStatus.PASS},
        )
        monkeypatch.delenv("GROUNDBALL_PUBLIC_DEMO", raising=False)

        with patch(
            "baseball_rag.arch.test_status.collect_and_apply_test_status",
            return_value=result,
        ) as collect:
            response = client.post("/api/developer/tests")

        assert response.status_code == 200
        assert response.json()["component_statuses"] == {"query-router": "pass"}
        collect.assert_called_once()

        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")
        with patch("baseball_rag.arch.test_status.collect_and_apply_test_status") as collect_public:
            public_response = client.post("/api/developer/tests")
        assert public_response.status_code == 404
        collect_public.assert_not_called()

    @pytest.mark.parametrize(
        ("method", "path", "json"),
        [
            ("get", "/review-queue", None),
            ("patch", "/review-queue/review_123", {"status": "dismissed"}),
            ("patch", "/review-queue/review_123", {}),
            ("get", "/evals/report", None),
            ("post", "/evals/run", {"include_live": False}),
        ],
    )
    def test_public_mode_hides_existing_operator_routes(self, method, path, json, monkeypatch):
        monkeypatch.setenv("GROUNDBALL_PUBLIC_DEMO", "1")

        response = client.request(method, path, json=json)

        assert response.status_code == 404

    def test_web_shell_returns_clear_diagnostic_when_assets_are_missing(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("GROUNDBALL_WEB_DIST", str(tmp_path / "missing-dist"))

        response = client.get("/")

        assert response.status_code == 503
        assert response.json() == {
            "error": "groundball_web_assets_unavailable",
            "detail": "Build the Ground Ball web assets before starting the server.",
        }

    def test_web_shell_falls_back_to_assets_bundled_in_the_python_package(
        self, tmp_path, monkeypatch
    ):
        from baseball_rag.api import server

        repository_dist = tmp_path / "repository-dist"
        package_dist = tmp_path / "package-dist"
        package_dist.mkdir()
        (package_dist / "index.html").write_text("<h1>Packaged Ground Ball</h1>", encoding="utf-8")
        monkeypatch.delenv("GROUNDBALL_WEB_DIST", raising=False)
        monkeypatch.setattr(server, "_REPOSITORY_WEB_DIST", repository_dist)
        monkeypatch.setattr(server, "_PACKAGE_WEB_DIST", package_dist)

        response = client.get("/")

        assert response.status_code == 200
        assert response.text == "<h1>Packaged Ground Ball</h1>"

    def test_web_shell_serves_assets_and_spa_routes_without_shadowing_api(
        self, tmp_path, monkeypatch
    ):
        web_dist = tmp_path / "dist"
        assets = web_dist / "assets"
        assets.mkdir(parents=True)
        (web_dist / "index.html").write_text("<h1>Ground Ball</h1>", encoding="utf-8")
        (assets / "app.js").write_text("window.GROUND_BALL = true;", encoding="utf-8")
        monkeypatch.setenv("GROUNDBALL_WEB_DIST", str(web_dist))

        assert client.get("/").text == "<h1>Ground Ball</h1>"
        assert client.get("/architecture").text == "<h1>Ground Ball</h1>"
        assert client.get("/assets/app.js").text == "window.GROUND_BALL = true;"
        assert (
            client.get("/api/capabilities").headers["content-type"].startswith("application/json")
        )
        assert client.get("/api/not-a-route").status_code == 404

    def test_health_endpoint(self):
        """GET /health returns 200 with {"status": "ok"}."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_query_endpoint_requires_origin_proxy_token_when_configured(self, monkeypatch):
        """Direct tunnel callers need the server-side proxy token when configured."""
        monkeypatch.setenv("GROUNDBALL_ORIGIN_PROXY_TOKEN", "secret-token")

        response = client.post("/query", json={"question": "who had the most RBIs in 1962"})

        assert response.status_code == 403
        assert response.json() == {"error": "groundball_origin_proxy_token_required"}

    def test_query_endpoint_accepts_origin_proxy_token_when_configured(self, monkeypatch):
        """The Pages Function can still reach /query with the shared proxy token."""
        monkeypatch.setenv("GROUNDBALL_ORIGIN_PROXY_TOKEN", "secret-token")

        response = client.post(
            "/query",
            headers={"X-Groundball-Proxy-Token": "secret-token"},
            json={},
        )

        assert response.status_code == 422

    def test_query_endpoint_allows_blog_origin_preflight(self, website_cors_origins):
        """Browser clients from the public blog can POST questions to the API."""
        response = client.options(
            "/query",
            headers={
                "Origin": "https://discostew.dev",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://discostew.dev"
        assert response.headers["access-control-allow-credentials"] == "true"
        assert "POST" in response.headers["access-control-allow-methods"]
        assert "content-type" in response.headers["access-control-allow-headers"].lower()

    def test_query_endpoint_rejects_untrusted_cors_origin(self, website_cors_origins):
        """Only configured website origins receive browser CORS permission."""
        response = client.options(
            "/query",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    @pytest.mark.parametrize(
        ("path", "method"),
        [
            ("/review-queue", "GET"),
            ("/evals/run", "POST"),
        ],
    )
    def test_operator_endpoints_reject_blog_origin_preflight(
        self, path, method, website_cors_origins
    ):
        """Allowed website origins should not receive CORS access to operator APIs."""
        response = client.options(
            path,
            headers={
                "Origin": "https://discostew.dev",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "content-type",
            },
        )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_health_endpoint_does_not_add_blog_origin_cors_headers(self, website_cors_origins):
        """Non-query endpoints stay same-origin/server-only from browser JavaScript."""
        response = client.get("/health", headers={"Origin": "https://discostew.dev"})

        assert response.status_code == 200
        assert "access-control-allow-origin" not in response.headers

    def test_verification_health_endpoint_reports_operational_checks(self):
        """GET /health/verification reports deterministic runtime readiness."""
        response = client.get("/health/verification")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        checks = {check["name"]: check for check in data["checks"]}
        assert checks["data_manifest"]["status"] == "ok"
        assert checks["duckdb_core_tables"]["status"] == "ok"
        assert checks["guardrail_manifest"]["status"] == "ok"
        assert data["commands"]["focused"] == "uv run pytest tests/test_api.py -q"

    def test_verification_health_handles_package_only_runtime(self, monkeypatch, tmp_path):
        """The runtime health endpoint should not depend on repo-root eval imports."""
        from baseball_rag import verification_health

        monkeypatch.setattr(
            verification_health,
            "_guardrail_manifest_path",
            lambda: tmp_path / "missing-questions.yaml",
        )

        data = verification_health.operational_verification_health()

        checks = {check["name"]: check for check in data["checks"]}
        assert data["status"] == "ok"
        assert checks["guardrail_manifest"]["status"] == "ok"
        assert "package-only runtime" in checks["guardrail_manifest"]["detail"]

    def test_query_endpoint_returns_answer(self, caplog):
        """POST /query with JSON body returns {answer: str, sources: list}."""
        # Note: This calls the real answer path, so we check response structure.
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
        assert data["sources"][0]["data_manifest"]["source_authorities"] == [
            {
                "name": "Lahman",
                "role": "primary",
                "authority": "factual_stat_authority",
                "dataset": "NeuML/baseballdata",
                "upstream": "Lahman Baseball Database",
                "optional": False,
                "scopes": [
                    "structured_stat_answers",
                    "grounded_database_answers",
                    "player_identity",
                    "biography_stat_claim_primary_verification",
                ],
            }
        ]
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

    def test_query_endpoint_returns_cors_headers_for_blog_post_validation_errors(
        self, website_cors_origins
    ):
        response = client.post(
            "/query",
            headers={"Origin": "https://discostew.dev"},
            json={},
        )

        assert response.status_code == 422
        assert response.headers["access-control-allow-origin"] == "https://discostew.dev"
        assert response.headers["access-control-allow-credentials"] == "true"

    def test_query_endpoint_accepts_stats_only_answer_mode(self):
        response = client.post(
            "/query",
            json={
                "question": "who had the most RBIs in 1962",
                "answer_mode": "stats_only",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["answer_mode"] == "stats_only"
        assert "Davis, Tommy: 153 RBI" in data["answer"]

    def test_query_endpoint_accepts_llm_flavored_answer_mode(self, monkeypatch):
        def fake_llm(_prompt, **_kwargs):
            return LLMResponse(
                content="Tommy Davis led MLB with 153 RBI in 1962.",
                model="test-model",
                done=True,
            )

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

        response = client.post(
            "/query",
            json={
                "question": "who had the most RBIs in 1962",
                "answer_mode": "llm_flavored",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Tommy Davis led MLB with 153 RBI in 1962."
        assert data["metadata"]["answer_mode"] == "llm_flavored"
        assert data["metadata"]["route"] == "stat_query"
        assert data["metadata"]["unsupported"] is False
        assert data["metadata"]["sql_visible"] is True
        assert data["metadata"]["source_count"] == 1
        assert data["metadata"]["source_types"] == ["duckdb"]
        assert data["metadata"]["trace"]["route_type"] == "stat_query"
        assert data["metadata"]["sql"]["template_hash"].startswith("sha256:")
        assert data["metadata"]["sql"]["row_count"] >= 1
        assert data["metadata"]["dataset"]["name"] == "NeuML/baseballdata"
        assert data["metadata"]["eval"]["case_id"] == "stat_rbi_1962"
        assert data["sources"][0]["type"] == "duckdb"
        assert data["sources"][0]["rows"]
        assert data["sources"][0]["sql"]

    def test_query_endpoint_llm_flavored_preserves_rejected_prose_with_footnotes(self, monkeypatch):
        responses = iter(
            [
                "Frank Robinson led MLB with 153 RBI in 1962.",
                "Tommy Davis was a pitcher in 1962 with 153 RBI.",
            ]
        )

        def fake_llm(_prompt, **_kwargs):
            return LLMResponse(
                content=next(responses),
                model="test-model",
                done=True,
            )

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fake_llm)

        response = client.post(
            "/query",
            json={
                "question": "who had the most RBIs in 1962",
                "answer_mode": "llm_flavored",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "Frank Robinson led MLB with 153 RBI in 1962." in data["answer"]
        assert "Verification footnotes:" in data["answer"]
        assert (
            "Frank Robinson is verified with 136 RBI in this result, not 153 RBI." in data["answer"]
        )
        assert (
            "Frank Robinson is not the verified leader; Tommy Davis leads with 153 RBI."
            in data["answer"]
        )
        assert data["metadata"]["answer_mode"] == "llm_flavored"
        assert data["metadata"]["llm_narration"]["status"] == "verification_failed"
        assert data["warnings"] == []
        assert data["sources"][0]["type"] == "duckdb"

    def test_query_endpoint_llm_flavored_returns_verified_answer_when_llm_unavailable(
        self, monkeypatch
    ):
        def unavailable_llm(_prompt, **_kwargs):
            raise ConnectionError("socket closed")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", unavailable_llm)

        response = client.post(
            "/query",
            json={
                "question": "who had the most RBIs in 1962",
                "answer_mode": "llm_flavored",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "Davis, Tommy: 153 RBI" in data["answer"]
        assert "LLM unavailable" not in data["answer"]
        assert data["metadata"]["answer_mode"] == "llm_flavored"
        assert data["metadata"]["llm_narration"]["status"] == "unavailable"
        assert "Gemma prose is unavailable" in data["metadata"]["llm_narration"]["message"]
        assert data["warnings"] == []
        assert data["sources"][0]["type"] == "duckdb"
        assert data["sources"][0]["sql"]
        assert data["sources"][0]["rows"]

    def test_query_endpoint_rejects_unknown_answer_mode(self):
        response = client.post(
            "/query",
            json={
                "question": "who had the most RBIs in 1962",
                "answer_mode": "box_score_poetry",
            },
        )

        assert response.status_code == 422

    def test_query_endpoint_rejects_removed_retrieval_options(self):
        response = client.post(
            "/query",
            json={
                "question": "who had the most RBIs in 1962",
                "retrieval_only": True,
            },
        )

        assert response.status_code == 422

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

    def test_query_endpoint_preserves_ambiguous_grounded_database_unsupported_reason(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post("/query", json={"question": "who is in the 500 club"})

        assert response.status_code == 200
        data = response.json()
        assert data["intent"] == "grounded_database_question"
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "ambiguous"
        assert data["review_reason"] == "ambiguous"
        assert data["metadata"]["unsupported_reason"] == "ambiguous"
        assert data["review"]["queued"] is True
        assert data["review"]["reason"] == "ambiguous"

    @pytest.mark.parametrize(
        "question",
        [
            "who led the league in vibes in 1999",
            "career HR; drop table batting leaders",
            "which team should I bet on tonight",
            "is Aaron Judge injured today",
            "what is the Yankees score right now",
            "what is Shohei Ohtani's current salary",
            "who is the greatest baseball player ever",
            "who won the NBA finals in 2020",
            "show me Statcast barrel rate leaders",
            "who led Triple-A in home runs in 2021",
        ],
    )
    def test_query_endpoint_rejects_policy_unsupported_questions(
        self, question, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))

        response = client.post("/query", json={"question": question})

        assert response.status_code == 200
        data = response.json()
        assert data["unsupported"] is True
        assert data["unsupported_reason"] == "unsupported"
        assert data["review"]["queued"] is True
        assert data["review"]["reason"] == "unsupported"

    def test_query_endpoint_answers_struck_out_the_side_without_llm(self, monkeypatch):
        def fail_llm(*_args, **_kwargs):
            raise AssertionError("Retrosheet event-derived questions must not call the LLM")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

        cases = [
            (
                "how many times did Rollie Fingers strike out the side in his career",
                "Rollie Fingers struck out the side 40 times",
                40,
            ),
            (
                "how many times did Nolan Ryan strike out the side in his career",
                "Nolan Ryan struck out the side 324 times",
                324,
            ),
        ]

        for question, answer_text, expected_count in cases:
            response = client.post("/query", json={"question": question})

            assert response.status_code == 200
            data = response.json()
            assert data["intent"] == "grounded_database_question"
            assert data["unsupported"] is False
            assert data["unsupported_reason"] is None
            assert answer_text in data["answer"]
            assert data["sources"][0]["type"] == "duckdb"
            assert data["sources"][0]["label"] == "Deterministic template query"
            assert "retrosheet_pitcher_strikeout_side_events" in data["sources"][0]["sql"]
            assert data["sources"][0]["rows"][0]["career_strikeout_side_count"] == expected_count
            retrosheet_manifest = data["sources"][0]["data_manifest"]["secondary_manifests"][
                "retrosheet"
            ]
            assert retrosheet_manifest["available"] is True
            assert retrosheet_manifest["files"][0]["table"] == (
                "retrosheet_pitcher_strikeout_side_events"
            )
            assert data["metadata"]["unsupported"] is False
            assert data["metadata"]["source_types"] == ["duckdb"]
            assert data["review"] is None

    def test_strikeout_side_template_does_not_own_broad_list_questions(self):
        from baseball_rag.db.grounded_database_templates import match_template

        assert match_template("which pitchers have struck out the side in their career") is None

    def test_query_endpoint_answers_stolen_base_streak_without_llm(self, monkeypatch):
        def fail_llm(*_args, **_kwargs):
            raise AssertionError("Retrosheet game-log streak questions must not call the LLM")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

        response = client.post(
            "/query",
            json={"question": "what is the longest stolen base streak in MLB history"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["unsupported"] is False
        assert (
            "Bert Campaneris had the longest stolen-base streak: "
            "12 consecutive regular-season games"
        ) in data["answer"]
        assert data["sources"][0]["label"] == "Deterministic template query"
        assert "retrosheet_batting" in data["sources"][0]["sql"]
        assert data["sources"][0]["rows"][0]["name"] == "Bert Campaneris"
        assert data["sources"][0]["rows"][0]["stolen_base_streak_games"] == 12
        retrosheet_manifest = data["sources"][0]["data_manifest"]["secondary_manifests"][
            "retrosheet"
        ]
        assert retrosheet_manifest["available"] is True
        assert any(item["table"] == "retrosheet_batting" for item in retrosheet_manifest["files"])

    def test_query_endpoint_answers_strikeout_side_year_and_leaders_without_llm(self, monkeypatch):
        def fail_llm(*_args, **_kwargs):
            raise AssertionError("Retrosheet event-derived questions must not call the LLM")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

        year_response = client.post(
            "/query",
            json={"question": "how many times did Rollie Fingers strike out the side in 1972"},
        )
        assert year_response.status_code == 200
        year_data = year_response.json()
        assert year_data["unsupported"] is False
        assert "Rollie Fingers struck out the side 8 times in 1972" in year_data["answer"]
        assert year_data["sources"][0]["rows"][0]["strikeout_side_count"] == 8

        leaders_response = client.post(
            "/query",
            json={"question": "which pitchers struck out the side the most in their careers"},
        )
        assert leaders_response.status_code == 200
        leaders_data = leaders_response.json()
        assert leaders_data["unsupported"] is False
        assert "Nolan Ryan: 324" in leaders_data["answer"]
        assert "Randy Johnson: 320" in leaders_data["answer"]
        assert leaders_data["sources"][0]["rows"][0]["name"] == "Nolan Ryan"
        assert leaders_data["sources"][0]["rows"][0]["career_strikeout_side_count"] == 324

        count_like_response = client.post(
            "/query",
            json={
                "question": (
                    "how many times did Rollie Fingers strike out the side in a game in 1972"
                )
            },
        )
        assert count_like_response.status_code == 200
        count_like_data = count_like_response.json()
        assert count_like_data["unsupported"] is False
        assert "Rollie Fingers struck out the side 8 times in 1972" in count_like_data["answer"]

        how_often_response = client.post(
            "/query",
            json={"question": "how often did Rollie Fingers strike out the side in a game in 1972"},
        )
        assert how_often_response.status_code == 200
        how_often_data = how_often_response.json()
        assert how_often_data["unsupported"] is False
        assert "Rollie Fingers struck out the side 8 times in 1972" in how_often_data["answer"]

        opponent_response = client.post(
            "/query",
            json={
                "question": (
                    "how many times did Rollie Fingers strike out the side "
                    "against the White Sox in 1972"
                )
            },
        )
        assert opponent_response.status_code == 200
        opponent_data = opponent_response.json()
        assert opponent_data["unsupported"] is False
        assert (
            "Rollie Fingers struck out the side 3 times in 1972 against Chicago White Sox"
            in opponent_data["answer"]
        )
        assert opponent_data["sources"][0]["rows"][0]["opponent_team"] == "Chicago White Sox"

        team_code_response = client.post(
            "/query",
            json={
                "question": (
                    "how many times did Rollie Fingers strike out the side against CHA in 1972"
                )
            },
        )
        assert team_code_response.status_code == 200
        team_code_data = team_code_response.json()
        assert team_code_data["unsupported"] is False
        assert "Rollie Fingers struck out the side 3 times in 1972" in team_code_data["answer"]

    def test_query_endpoint_answers_strikeout_side_game_log_without_llm(self, monkeypatch):
        def fail_llm(*_args, **_kwargs):
            raise AssertionError("Retrosheet event-derived questions must not call the LLM")

        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

        response = client.post(
            "/query",
            json={"question": "show Rollie Fingers strikeout side games in 1972"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["unsupported"] is False
        assert "Rollie Fingers strikeout-side games in 1972" in data["answer"]
        assert "CAL197205160" in data["answer"]
        assert "OAK197208100" in data["answer"]
        assert data["sources"][0]["rows"][0]["game_id"] == "CAL197205160"
        assert data["sources"][0]["rows"][0]["inning"] == 6

        opponent_response = client.post(
            "/query",
            json={
                "question": "show Rollie Fingers strikeout side games against the White Sox in 1972"
            },
        )
        assert opponent_response.status_code == 200
        opponent_data = opponent_response.json()
        assert opponent_data["unsupported"] is False
        assert "against Chicago White Sox in 1972" in opponent_data["answer"]
        assert "CHA197206300" in opponent_data["answer"]
        assert len(opponent_data["sources"][0]["rows"]) == 3
        assert opponent_data["sources"][0]["rows"][0]["opponent_team"] == "Chicago White Sox"

        rare_team_response = client.post(
            "/query",
            json={
                "question": "show Satchel Paige strikeout side games against PIR in 1943",
            },
        )
        assert rare_team_response.status_code == 200
        rare_team_data = rare_team_response.json()
        assert rare_team_data["unsupported"] is False
        assert rare_team_data["sources"][0]["rows"][0]["pitcher_team"] == "BCG"

        career_response = client.post(
            "/query",
            json={"question": "show Nolan Ryan strikeout side games"},
        )
        assert career_response.status_code == 200
        career_data = career_response.json()
        assert career_data["unsupported"] is False
        assert "showing first 100 of 324" in career_data["answer"]

    def test_query_endpoint_rejects_unmodeled_retrosheet_event_queries(self, monkeypatch, tmp_path):
        def fail_llm(*_args, **_kwargs):
            raise AssertionError("unmodeled Retrosheet event queries must not call the LLM")

        monkeypatch.setenv("BASEBALL_RAG_REVIEW_QUEUE_PATH", str(tmp_path / "review.jsonl"))
        monkeypatch.setattr("baseball_rag.generation.llm.make_request", fail_llm)

        for question in (
            "how often did Rollie Fingers enter with runners on",
            "how often did Rollie Fingers inherit runners",
            "how often did Rollie Fingers come in with men on base",
            "how often did Rollie Fingers strike out the side in the postseason",
            "how many called strikeout-side innings did Rollie Fingers have",
            "show Rollie Fingers strikeout side games at Yankee Stadium in 1972",
        ):
            response = client.post("/query", json={"question": question})

            assert response.status_code == 200
            data = response.json()
            assert data["unsupported"] is True
            assert data["unsupported_reason"] == "unsupported"
            assert "Retrosheet event data is local" in data["answer"]

        ambiguous_opponent = client.post(
            "/query",
            json={"question": "show Rollie Fingers strikeout side games against Chicago in 1972"},
        )
        assert ambiguous_opponent.status_code == 200
        ambiguous_data = ambiguous_opponent.json()
        assert ambiguous_data["unsupported"] is True
        assert ambiguous_data["unsupported_reason"] == "unsupported"
        assert "recognized team nickname or Retrosheet team code" in ambiguous_data["answer"]

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
        assert data["summary"]["attempted"] == 26
        assert data["summary"]["recommendation"] in {"PASS", "WARN"}
        assert data["markdown"].startswith("# Groundball Eval Report")

    def test_evals_run_include_live_adds_llm_warning(self, monkeypatch):
        monkeypatch.setattr(
            "baseball_rag.api.server._run_eval_payload",
            lambda *, include_live: {
                "ok": True,
                "mode": "answer",
                "include_live": include_live,
                "minimum_pass_rate": 0.85,
                "summary": {"attempted": 0},
                "results": {"passed": [], "failed": [], "skipped": []},
                "failed": [],
                "skipped": [],
                "markdown": "# Groundball Eval Report\n",
                "warnings": [],
            },
        )

        response = client.post("/evals/run", json={"include_live": True})

        assert response.status_code == 200
        assert "LM Studio" in response.json()["warnings"][0]

    def test_evals_run_rejects_removed_retrieval_options(self, monkeypatch):
        monkeypatch.setattr(
            "baseball_rag.api.server._run_eval_payload",
            lambda *, include_live: (_ for _ in ()).throw(
                AssertionError("eval runner should not be called")
            ),
        )

        response = client.post("/evals/run", json={"retrieval_only": True})

        assert response.status_code == 422

    def test_evals_run_default_matches_ci_gate(self):
        response = client.post("/evals/run", json={})

        assert response.status_code == 200
        data = response.json()
        assert data["options"]["include_live"] is False
        assert data["summary"]["attempted"] == 26
        assert data["results"]["failed"] == []

    def test_guardrails_coverage_endpoint_is_manifest_only(self):
        response = client.get("/guardrails/coverage")

        assert response.status_code == 200
        data = response.json()
        assert data["summary"]["unsupported_guardrails"] >= 1
        assert data["categories"]["unsupported"]
        assert data["markdown"].startswith("# Groundball Guardrail Coverage")

    def test_guardrails_coverage_reports_unavailable_when_manifest_is_absent(
        self,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setattr(
            "baseball_rag.eval_manifest.default_questions_path",
            lambda: tmp_path / "missing-questions.yaml",
        )

        response = client.get("/guardrails/coverage")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["summary"]["unsupported_guardrails"] == 0
        assert data["categories"]["unsupported"] == []
        assert "missing-questions.yaml" in data["reason"]
