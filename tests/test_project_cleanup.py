"""Repository cleanup policies for retired and optional surfaces."""

import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _dependency_name(requirement: str) -> str:
    head = requirement.split(";", 1)[0].strip()
    return head.split("[", 1)[0].split("<", 1)[0].split(">", 1)[0].split("=", 1)[0].strip()


def test_default_package_excludes_optional_mlb_api_mcp_surface() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    mypy_config = (ROOT / "mypy.ini").read_text(encoding="utf-8")

    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/baseball_rag"
    ]
    assert "COPY src/ ./src/" not in dockerfile
    assert "COPY src/baseball_rag/ ./src/baseball_rag/" in dockerfile
    assert "mypy-mlb_api_mcp" not in mypy_config
    assert not (ROOT / "src" / "baseball_rag" / "mcp.py").exists()

    dependency_names = {_dependency_name(dep) for dep in pyproject["project"]["dependencies"]}
    assert "fastmcp" not in dependency_names
    assert "python-mlb-statsapi" not in dependency_names
    assert "pybaseball" not in dependency_names


def test_ci_runs_all_non_llm_tests_without_chroma_dependency() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "chromadb" not in ci
    assert '-m "not llm"' in ci
    assert "unit and not llm" not in ci
    assert "chroma" not in gitignore.lower()


def test_no_noop_duckdb_init_compatibility_shim() -> None:
    duckdb_schema = (ROOT / "src" / "baseball_rag" / "db" / "duckdb_schema.py").read_text(
        encoding="utf-8"
    )
    db_init = (ROOT / "src" / "baseball_rag" / "db" / "__init__.py").read_text(encoding="utf-8")
    package_init = (ROOT / "src" / "baseball_rag" / "__init__.py").read_text(encoding="utf-8")

    assert "def init_db(" not in duckdb_schema
    assert "init_db" not in db_init
    assert "init_db" not in package_init


def test_service_no_longer_exposes_biography_contract_patch_aliases() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")

    assert "_request_biography_json" not in service
    assert "_parse_biography_json" not in service
    assert "_extract_supplied_stat_claims" not in service


def test_request_dispatch_no_longer_normalizes_legacy_route_results() -> None:
    request_dispatch = (ROOT / "src" / "baseball_rag" / "request_dispatch.py").read_text(
        encoding="utf-8"
    )

    assert "RouteResult" not in request_dispatch
    assert "_dispatch_legacy_route_result" not in request_dispatch
    assert "_validated_legacy_intent" not in request_dispatch


def test_routing_no_longer_exports_legacy_route_result() -> None:
    routing_init = (ROOT / "src" / "baseball_rag" / "routing" / "__init__.py").read_text(
        encoding="utf-8"
    )
    query_router = (ROOT / "src" / "baseball_rag" / "routing" / "query_router.py").read_text(
        encoding="utf-8"
    )

    assert "RouteResult" not in routing_init
    assert "class RouteResult" not in query_router
    assert "def _extract_json_blocks(" not in query_router
    assert "Backward-compatible wrapper" not in query_router
    assert "def year(" not in query_router


def test_freeform_no_longer_exports_json_block_compatibility_wrapper() -> None:
    freeform = (ROOT / "src" / "baseball_rag" / "db" / "freeform.py").read_text(encoding="utf-8")
    freeform_intent = (ROOT / "src" / "baseball_rag" / "db" / "freeform_intent.py").read_text(
        encoding="utf-8"
    )

    assert "def _extract_json_blocks(" not in freeform_intent
    assert "_extract_json_blocks" not in freeform
    assert "Backward-compatible wrapper" not in freeform_intent


def test_arch_components_no_longer_exports_component_test_status_alias() -> None:
    components = (ROOT / "src" / "baseball_rag" / "arch" / "components.py").read_text(
        encoding="utf-8"
    )
    arch_init = (ROOT / "src" / "baseball_rag" / "arch" / "__init__.py").read_text(encoding="utf-8")

    assert "ComponentTestStatus" not in components
    assert "ComponentTestStatus" not in arch_init


def test_retired_corpus_ingest_entrypoint_is_removed() -> None:
    corpus_main = (ROOT / "src" / "baseball_rag" / "corpus" / "__main__.py").read_text(
        encoding="utf-8"
    )
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    architecture_docs = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "ingest.py").exists()
    assert "ingest_main" not in corpus_main
    assert "Retired Ingest Command" not in corpus_docs
    assert "retired ingest command" not in architecture_docs.lower()


def test_stale_space_deploy_surface_is_not_active() -> None:
    assert not (ROOT / ".github" / "workflows" / "deploy.yml").exists()
    assert not (ROOT / "space-app").exists()


def test_stale_architecture_handoff_docs_are_archived() -> None:
    active_docs = {
        "architecture-all-six-deepening-handoff-plan.md",
        "architecture-deepening-handoff.md",
        "architecture-deepening-plan.md",
        "architecture-explorer-plan.md",
        "architecture-worker-handoff-plan.md",
    }

    for filename in active_docs:
        assert not (ROOT / "docs" / filename).exists()
        assert (ROOT / "docs" / "archive" / "architecture" / filename).exists()


def test_docs_match_current_eval_and_corpus_runtime() -> None:
    demo = (ROOT / "docs" / "demo-governance.md").read_text(encoding="utf-8")
    corpus = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    development = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")

    assert "evals: 25 passed, 0 failed, 43 skipped" in demo
    assert "evals: 20 passed, 0 failed, 48 skipped" not in demo
    assert "local stat-definition Markdown" in corpus
    assert "stat-definition Markdown remains" in development
    assert "runtime grounding for supported stat-definition explanations" in development
    assert (
        'General explanations such as "what is OPS?" are answered by the LLM directly' not in corpus
    )
