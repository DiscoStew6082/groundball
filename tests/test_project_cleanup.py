from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_primary_query_runtime_has_no_legacy_authority_or_fallback() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / "src/baseball_rag").rglob("*.py")
    )
    forbidden = (
        "StatQueryPlan",
        "StatQueryResult",
        "QuerySpec",
        "AssembledSQL",
        "GroundedDatabaseQueryPlan",
        "GroundedDatabaseResult",
        "plan_grounded_database_query",
        "execute_public_demo_request",
        "answer_public_demo",
        "deterministic_grounded_database_owns",
    )

    assert all(term not in source for term in forbidden)


def test_old_primary_query_modules_are_deleted() -> None:
    removed = (
        "src/baseball_rag/stat_query.py",
        "src/baseball_rag/service.py",
        "src/baseball_rag/request_dispatch.py",
        "src/baseball_rag/request_execution.py",
        "src/baseball_rag/request_lifecycle.py",
        "src/baseball_rag/query_scope.py",
        "src/baseball_rag/db/queries.py",
        "src/baseball_rag/db/stat_registry.py",
        "src/baseball_rag/db/team_history.py",
        "src/baseball_rag/db/grounded_database_assembler.py",
        "src/baseball_rag/db/grounded_database_intent.py",
        "src/baseball_rag/db/grounded_database_planner.py",
        "src/baseball_rag/db/grounded_database_runtime.py",
        "src/baseball_rag/db/grounded_database_schema.py",
        "src/baseball_rag/db/grounded_database_templates.py",
        "src/baseball_rag/db/grounded_database_types.py",
    )

    assert all(not (REPO_ROOT / path).exists() for path in removed)


def test_only_clean_query_and_retrosheet_http_routes_remain() -> None:
    server = (REPO_ROOT / "src/baseball_rag/api/server.py").read_text(encoding="utf-8")

    assert '@router.post("/api/query-runs")' in server
    assert '@router.get("/api/query-catalog")' in server
    assert '@router.get("/api/query-coverage")' in server
    assert '@router.post("/api/retrosheet/queries")' in server
    assert '@router.post("/query")' not in server
    assert '@router.post("/api/query")' not in server
