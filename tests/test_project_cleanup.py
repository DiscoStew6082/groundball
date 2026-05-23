"""Repository cleanup policies for retired and optional surfaces."""

import re
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


def test_player_biography_answerer_requires_routed_case() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")
    player_biography = (ROOT / "src" / "baseball_rag" / "player_biography.py").read_text(
        encoding="utf-8"
    )

    assert 'getattr(decision, "player_name"' not in player_biography
    assert "def answer(self, question: str, decision: Any)" not in player_biography
    assert "def _answer_player_biography(question: str, decision: Any)" not in service


def test_request_dispatch_no_longer_normalizes_legacy_route_results() -> None:
    request_dispatch = (ROOT / "src" / "baseball_rag" / "request_dispatch.py").read_text(
        encoding="utf-8"
    )

    assert "RouteResult" not in request_dispatch
    assert "_dispatch_legacy_route_result" not in request_dispatch
    assert "_validated_legacy_intent" not in request_dispatch


def test_request_dispatch_handlers_require_routed_cases() -> None:
    request_dispatch = (ROOT / "src" / "baseball_rag" / "request_dispatch.py").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")

    assert "Callable[..., StructuredAnswer]" not in request_dispatch
    assert "Callable[[Any], StructuredAnswer]" not in request_dispatch
    assert "Callable[[str, Any], StructuredAnswer]" not in request_dispatch
    assert "route_question: Callable[[str], Any]" not in request_dispatch
    assert "def _answer_general(question: str, decision: Any)" not in service


def test_request_dispatch_no_longer_has_noop_initialize_hook() -> None:
    request_dispatch = (ROOT / "src" / "baseball_rag" / "request_dispatch.py").read_text(
        encoding="utf-8"
    )
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")

    assert "initialize:" not in request_dispatch
    assert "self.initialize()" not in request_dispatch
    assert "initialize=lambda: None" not in service


def test_general_explanation_no_longer_uses_fallback_question_shape() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")
    general_explanation = (ROOT / "src" / "baseball_rag" / "general_explanation.py").read_text(
        encoding="utf-8"
    )

    assert "fallback_question" not in service
    assert "fallback_question" not in general_explanation


def test_grounded_database_question_no_longer_uses_year_route_shape() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")

    assert 'getattr(decision, "year"' not in service
    assert 'getattr(decision, "time_period"' not in service
    assert 'getattr(decision, "raw_question"' not in service
    assert 'getattr(decision, "intent"' not in service


def test_conversation_no_longer_exposes_private_transcript_wrappers() -> None:
    conversation = (ROOT / "src" / "baseball_rag" / "conversation.py").read_text(encoding="utf-8")

    assert "def _row_from_recent_turn(" not in conversation
    assert "def _active_player_from_recent_turn(" not in conversation
    assert "def _answer_payload(" not in conversation
    assert "def _turn_question(" not in conversation
    assert "def _player_name_from_row(" not in conversation


def test_retired_retrieval_failure_outcomes_are_removed() -> None:
    outcomes = (ROOT / "src" / "baseball_rag" / "outcomes.py").read_text(encoding="utf-8")
    provenance = (ROOT / "src" / "baseball_rag" / "provenance.py").read_text(encoding="utf-8")

    assert "def missing_corpus_outcome(" not in outcomes
    assert "def retrieval_failed_outcome(" not in outcomes
    assert '"missing_corpus"' not in provenance
    assert '"retrieval_failed"' not in provenance


def test_low_confidence_review_queue_surface_is_removed() -> None:
    provenance = (ROOT / "src" / "baseball_rag" / "provenance.py").read_text(encoding="utf-8")
    review_queue = (ROOT / "src" / "baseball_rag" / "review_queue.py").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api_docs = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")

    assert "low_confidence" not in provenance
    assert "low_confidence" not in review_queue
    assert "low_confidence_threshold" not in review_queue
    assert "low-confidence" not in readme
    assert "low-confidence" not in api_docs


def test_conversation_followups_use_current_row_name_shapes_only() -> None:
    conversation = (ROOT / "src" / "baseball_rag" / "conversation.py").read_text(encoding="utf-8")
    transcript = (ROOT / "src" / "baseball_rag" / "conversation_transcript.py").read_text(
        encoding="utf-8"
    )

    assert '"player_name"' not in conversation
    assert '"full_name"' not in conversation
    assert '"player_name"' not in transcript
    assert '"full_name"' not in transcript


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


def test_freeform_compatibility_facade_is_removed() -> None:
    freeform_intent = (ROOT / "src" / "baseball_rag" / "db" / "freeform_intent.py").read_text(
        encoding="utf-8"
    )

    assert not (ROOT / "src" / "baseball_rag" / "db" / "freeform.py").exists()
    assert "def _extract_json_blocks(" not in freeform_intent
    assert "Backward-compatible wrapper" not in freeform_intent


def test_service_uses_freeform_runtime_directly() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")

    assert "baseball_rag.db.freeform import" not in service
    assert "baseball_rag.db.freeform_runtime import" in service


def test_freeform_tests_use_runtime_modules_directly() -> None:
    freeform_tests = (ROOT / "tests" / "test_freeform.py").read_text(encoding="utf-8")

    assert "baseball_rag.db.freeform import" not in freeform_tests
    assert not re.search(r"^\s*from baseball_rag\.db import freeform\b", freeform_tests, re.M)
    assert not re.search(r"^\s*import baseball_rag\.db\.freeform\b", freeform_tests, re.M)


def test_batting_player_stat_compatibility_adapter_is_removed() -> None:
    queries = (ROOT / "src" / "baseball_rag" / "db" / "queries.py").read_text(encoding="utf-8")
    db_init = (ROOT / "src" / "baseball_rag" / "db" / "__init__.py").read_text(encoding="utf-8")
    package_init = (ROOT / "src" / "baseball_rag" / "__init__.py").read_text(encoding="utf-8")

    assert "def get_player_stat(" not in queries
    assert "get_player_stat" not in db_init
    assert "get_player_stat" not in package_init


def test_stat_leaders_compatibility_adapter_is_removed() -> None:
    queries = (ROOT / "src" / "baseball_rag" / "db" / "queries.py").read_text(encoding="utf-8")
    db_init = (ROOT / "src" / "baseball_rag" / "db" / "__init__.py").read_text(encoding="utf-8")
    package_init = (ROOT / "src" / "baseball_rag" / "__init__.py").read_text(encoding="utf-8")

    assert "def get_stat_leaders(" not in queries
    assert not re.search(r"^\s*get_stat_leaders,?$", db_init, re.M)
    assert not re.search(r"^\s*get_stat_leaders,?$", package_init, re.M)


def test_stat_leaders_range_compatibility_adapter_is_removed() -> None:
    queries = (ROOT / "src" / "baseball_rag" / "db" / "queries.py").read_text(encoding="utf-8")
    db_init = (ROOT / "src" / "baseball_rag" / "db" / "__init__.py").read_text(encoding="utf-8")

    assert "def get_stat_leaders_range(" not in queries
    assert "get_stat_leaders_range" not in db_init


def test_career_stat_leaders_compatibility_adapter_is_removed() -> None:
    queries = (ROOT / "src" / "baseball_rag" / "db" / "queries.py").read_text(encoding="utf-8")
    db_init = (ROOT / "src" / "baseball_rag" / "db" / "__init__.py").read_text(encoding="utf-8")
    package_init = (ROOT / "src" / "baseball_rag" / "__init__.py").read_text(encoding="utf-8")

    assert "def get_career_stat_leaders(" not in queries
    assert "get_career_stat_leaders" not in db_init
    assert "get_career_stat_leaders" not in package_init


def test_fielding_leaders_compatibility_adapter_is_removed() -> None:
    queries = (ROOT / "src" / "baseball_rag" / "db" / "queries.py").read_text(encoding="utf-8")
    db_init = (ROOT / "src" / "baseball_rag" / "db" / "__init__.py").read_text(encoding="utf-8")
    package_init = (ROOT / "src" / "baseball_rag" / "__init__.py").read_text(encoding="utf-8")

    assert "def get_fielding_leaders(" not in queries
    assert "get_fielding_leaders" not in db_init
    assert "get_fielding_leaders" not in package_init


def test_execute_stat_query_compatibility_adapter_is_removed() -> None:
    queries = (ROOT / "src" / "baseball_rag" / "db" / "queries.py").read_text(encoding="utf-8")
    db_init = (ROOT / "src" / "baseball_rag" / "db" / "__init__.py").read_text(encoding="utf-8")

    assert "def execute_stat_query(" not in queries
    assert "execute_stat_query" not in db_init


def test_llm_prompt_string_compatibility_is_removed() -> None:
    llm = (ROOT / "src" / "baseball_rag" / "generation" / "llm.py").read_text(encoding="utf-8")

    assert "str | tuple" not in llm
    assert "backward compat" not in llm


def test_architecture_latest_run_session_map_alias_is_removed() -> None:
    diagram = (ROOT / "src" / "baseball_rag" / "arch" / "diagram.py").read_text(encoding="utf-8")
    read_model = (ROOT / "src" / "baseball_rag" / "arch" / "read_model.py").read_text(
        encoding="utf-8"
    )

    assert "latest_runs_by_session" not in diagram
    assert "def latest_by_session(" not in read_model


def test_duckdb_schema_no_longer_exports_team_map_alias() -> None:
    duckdb_schema = (ROOT / "src" / "baseball_rag" / "db" / "duckdb_schema.py").read_text(
        encoding="utf-8"
    )
    queries = (ROOT / "src" / "baseball_rag" / "db" / "queries.py").read_text(encoding="utf-8")
    player_bios = (ROOT / "src" / "baseball_rag" / "corpus" / "player_bios.py").read_text(
        encoding="utf-8"
    )

    assert not re.search(r"^TEAM_MAP\s*=", duckdb_schema, re.M)
    assert "import TEAM_MAP" not in queries
    assert "import TEAM_MAP" not in player_bios


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


def test_public_docs_use_grounded_database_question_naming() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api_docs = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")

    assert "Freeform SQL" not in readme
    assert "Freeform query" not in api_docs
    assert "Freeform database answers" not in corpus_docs
    assert "grounded database question" in readme.lower()
    assert "grounded database question" in api_docs.lower()
    assert "grounded database question" in corpus_docs.lower()


def test_routing_ownership_uses_grounded_database_question_naming() -> None:
    query_router = (ROOT / "src" / "baseball_rag" / "routing" / "query_router.py").read_text(
        encoding="utf-8"
    )
    grounded_ownership = (
        ROOT / "src" / "baseball_rag" / "routing" / "grounded_database_ownership.py"
    ).read_text(encoding="utf-8")
    freeform_runtime = (ROOT / "src" / "baseball_rag" / "db" / "freeform_runtime.py").read_text(
        encoding="utf-8"
    )
    freeform_templates = (ROOT / "src" / "baseball_rag" / "db" / "freeform_templates.py").read_text(
        encoding="utf-8"
    )

    assert not (ROOT / "src" / "baseball_rag" / "routing" / "freeform_ownership.py").exists()
    assert "freeform_ownership" not in query_router
    assert "deterministic_freeform_owns" not in query_router
    assert "deterministic freeform" not in grounded_ownership.lower()
    assert "should_route_deterministic_freeform" not in grounded_ownership
    assert "def should_route_deterministic_freeform(" not in freeform_runtime
    assert "def should_route_deterministic_freeform(" not in freeform_templates


def test_retired_corpus_manifest_lifecycle_is_removed() -> None:
    corpus_main = (ROOT / "src" / "baseball_rag" / "corpus" / "__main__.py").read_text(
        encoding="utf-8"
    )
    diagnostics = (ROOT / "src" / "baseball_rag" / "corpus" / "diagnostics.py").read_text(
        encoding="utf-8"
    )
    lifecycle = (ROOT / "src" / "baseball_rag" / "corpus" / "lifecycle.py").read_text(
        encoding="utf-8"
    )
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    development_docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    architecture_docs = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert "corpus_manifest.json" not in diagnostics
    assert "persist-dir" not in corpus_main
    assert "manifest_section_count" not in lifecycle
    assert "write_corpus_manifest" not in lifecycle
    assert "new_manifest" not in lifecycle
    assert "finalize_manifest_counts" not in lifecycle
    assert "manifest_documents" not in lifecycle
    assert "old ignored manifest" not in corpus_docs
    assert "old ignored manifest" not in development_docs
    assert "old ignored manifest" not in architecture_docs


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
