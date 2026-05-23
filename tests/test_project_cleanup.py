"""Repository cleanup policies for retired and optional surfaces."""

import ast
import io
import re
import tokenize
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEGACY_DATABASE_LABEL = "free" + "form"


def test_cleanup_policy_source_avoids_literal_legacy_database_label() -> None:
    cleanup_source = (ROOT / "tests" / "test_project_cleanup.py").read_text(encoding="utf-8")

    assert LEGACY_DATABASE_LABEL not in cleanup_source.lower()


def _dependency_name(requirement: str) -> str:
    head = requirement.split(";", 1)[0].strip()
    return head.split("[", 1)[0].split("<", 1)[0].split(">", 1)[0].split("=", 1)[0].strip()


def _python_docstrings_and_comments(source: str) -> list[str]:
    module = ast.parse(source)
    docstrings = [
        docstring
        for node in ast.walk(module)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        if (docstring := ast.get_docstring(node)) is not None
    ]
    comments = [
        token.string
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type == tokenize.COMMENT
    ]
    return docstrings + comments


def _python_definition_names(source: str) -> list[str]:
    module = ast.parse(source)
    return [
        node.name
        for node in ast.walk(module)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _yaml_values_for_keys(value: object, keys: set[str]) -> list[str]:
    if isinstance(value, dict):
        values: list[str] = []
        for key, item in value.items():
            if key in keys and isinstance(item, str):
                values.append(item)
            values.extend(_yaml_values_for_keys(item, keys))
        return values
    if isinstance(value, list):
        return [item for entry in value for item in _yaml_values_for_keys(entry, keys)]
    return []


def _python_imports_module(source: str, module_name: str) -> bool:
    parsed = ast.parse(source)
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            if any(alias.name == module_name for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                return True
            if node.module == module_name.rsplit(".", 1)[0]:
                imported_name = module_name.rsplit(".", 1)[1]
                if any(alias.name == imported_name for alias in node.names):
                    return True
    return False


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
    player_biography = (ROOT / "src" / "baseball_rag" / "player_biography.py").read_text(
        encoding="utf-8"
    )

    assert "_request_biography_json" not in service
    assert "_parse_biography_json" not in service
    assert "_extract_supplied_stat_claims" not in service
    assert "build_biography_json_repair_prompt =" not in player_biography
    assert "is_biography_json_contract =" not in player_biography
    assert "loads_json_object =" not in player_biography
    assert "parse_biography_json =" not in player_biography
    assert "request_biography_json =" not in player_biography


def test_service_imports_llm_client_directly() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")

    assert "except ImportError" not in service
    assert "make_request = None" not in service


def test_service_no_longer_exposes_general_explanation_patch_wrappers() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")

    assert "def _answer_local_stat_definition(" not in service
    assert "def _markdown_body(" not in service


def test_player_biography_answerer_requires_routed_case() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")
    player_biography = (ROOT / "src" / "baseball_rag" / "player_biography.py").read_text(
        encoding="utf-8"
    )

    assert 'getattr(decision, "player_name"' not in player_biography
    assert "def answer(self, question: str, decision: Any)" not in player_biography
    assert "def _answer_player_biography(question: str, decision: Any)" not in service


def test_player_biography_uses_consensus_verifier_directly() -> None:
    player_biography = (ROOT / "src" / "baseball_rag" / "player_biography.py").read_text(
        encoding="utf-8"
    )

    assert "except ImportError" not in player_biography
    assert "_db_verify_player_stat_claims_consensus" not in player_biography
    assert "return verify_player_stat_claims(player_id, claims, conn=conn)" not in player_biography


def test_biography_stat_claim_payload_uses_current_text_field_only() -> None:
    player_stat_claims = (ROOT / "src" / "baseball_rag" / "db" / "player_stat_claims.py").read_text(
        encoding="utf-8"
    )

    assert 'payload.get("context")' not in player_stat_claims


def test_biography_contract_requires_explicit_stat_claims_array() -> None:
    biography_contract = (ROOT / "src" / "baseball_rag" / "biography_contract.py").read_text(
        encoding="utf-8"
    )

    assert 'data.get("stat_claims", [])' not in biography_contract
    assert "raw_claims is None" not in biography_contract


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


def test_stat_query_no_data_warnings_do_not_reference_fallback_leaderboards() -> None:
    stat_query = (ROOT / "src" / "baseball_rag" / "stat_query.py").read_text(encoding="utf-8")

    assert "fallback leaderboard" not in stat_query


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
    assert '"nameFirst"' not in conversation
    assert '"nameLast"' not in conversation
    assert '"player_name"' not in transcript
    assert '"full_name"' not in transcript
    assert '"nameFirst"' not in transcript
    assert '"nameLast"' not in transcript


def test_conversation_turn_requires_structured_answer_payloads() -> None:
    conversation = (ROOT / "src" / "baseball_rag" / "conversation.py").read_text(encoding="utf-8")
    presentation = (ROOT / "src" / "baseball_rag" / "ui" / "presentation.py").read_text(
        encoding="utf-8"
    )

    assert "StructuredAnswer | dict" not in conversation
    assert "else dict(answer)" not in conversation
    assert "{**self.payload" not in presentation


def test_conversation_transcript_accepts_serialized_answer_payloads_only() -> None:
    transcript = (ROOT / "src" / "baseball_rag" / "conversation_transcript.py").read_text(
        encoding="utf-8"
    )

    assert "StructuredAnswer" not in transcript
    assert "def _answer_payload(" not in transcript


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


def test_legacy_database_compatibility_facade_is_removed() -> None:
    grounded_database_intent = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_intent.py"
    ).read_text(encoding="utf-8")
    legacy_module = LEGACY_DATABASE_LABEL

    assert not (ROOT / "src" / "baseball_rag" / "db" / f"{legacy_module}.py").exists()
    assert "def _extract_json_blocks(" not in grounded_database_intent
    assert "Backward-compatible wrapper" not in grounded_database_intent


def test_service_uses_grounded_database_runtime_directly() -> None:
    service = (ROOT / "src" / "baseball_rag" / "service.py").read_text(encoding="utf-8")
    legacy_import = f"baseball_rag.db.{LEGACY_DATABASE_LABEL} import"

    assert legacy_import not in service
    assert "baseball_rag.db.grounded_database_runtime import" in service


def test_grounded_database_tests_use_runtime_modules_directly() -> None:
    old_test_file = ROOT / "tests" / f"test_{LEGACY_DATABASE_LABEL}.py"
    grounded_database_tests = (ROOT / "tests" / "test_grounded_database.py").read_text(
        encoding="utf-8"
    )
    legacy_import = f"baseball_rag.db.{LEGACY_DATABASE_LABEL} import"
    legacy_module_pattern = re.escape(LEGACY_DATABASE_LABEL)

    assert not old_test_file.exists()
    assert legacy_import not in grounded_database_tests
    assert not re.search(
        rf"^\s*from baseball_rag\.db import {legacy_module_pattern}\b",
        grounded_database_tests,
        re.M,
    )
    assert not re.search(
        rf"^\s*import baseball_rag\.db\.{legacy_module_pattern}\b",
        grounded_database_tests,
        re.M,
    )


def test_grounded_database_types_module_replaces_legacy_types_module() -> None:
    old_module = "free" + "form_types"
    new_module = "grounded_database_types"
    search_roots = [ROOT / "src", ROOT / "tests", ROOT / "evals"]

    assert not (ROOT / "src" / "baseball_rag" / "db" / f"{old_module}.py").exists()
    assert (ROOT / "src" / "baseball_rag" / "db" / f"{new_module}.py").exists()
    for path in (
        path
        for root in search_roots
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    ):
        text = path.read_text(encoding="utf-8")
        assert not _python_imports_module(text, f"baseball_rag.db.{old_module}")


def test_grounded_database_assembler_module_replaces_legacy_module() -> None:
    old_module = "free" + "form_assembler"
    new_module = "grounded_database_assembler"
    search_roots = [ROOT / "src", ROOT / "tests", ROOT / "evals"]

    assert not (ROOT / "src" / "baseball_rag" / "db" / f"{old_module}.py").exists()
    assert (ROOT / "src" / "baseball_rag" / "db" / f"{new_module}.py").exists()
    for path in (
        path
        for root in search_roots
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    ):
        text = path.read_text(encoding="utf-8")
        assert not _python_imports_module(text, f"baseball_rag.db.{old_module}")


def test_grounded_database_intent_module_replaces_legacy_module() -> None:
    old_module = "free" + "form_intent"
    new_module = "grounded_database_intent"
    search_roots = [ROOT / "src", ROOT / "tests", ROOT / "evals"]

    assert not (ROOT / "src" / "baseball_rag" / "db" / f"{old_module}.py").exists()
    assert (ROOT / "src" / "baseball_rag" / "db" / f"{new_module}.py").exists()
    for path in (
        path
        for root in search_roots
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    ):
        text = path.read_text(encoding="utf-8")
        assert not _python_imports_module(text, f"baseball_rag.db.{old_module}")


def test_grounded_database_schema_module_replaces_legacy_module() -> None:
    old_module = "free" + "form_schema"
    new_module = "grounded_database_schema"
    search_roots = [ROOT / "src", ROOT / "tests", ROOT / "evals"]

    assert not (ROOT / "src" / "baseball_rag" / "db" / f"{old_module}.py").exists()
    assert (ROOT / "src" / "baseball_rag" / "db" / f"{new_module}.py").exists()
    for path in (
        path
        for root in search_roots
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    ):
        text = path.read_text(encoding="utf-8")
        assert not _python_imports_module(text, f"baseball_rag.db.{old_module}")


def test_grounded_database_templates_module_replaces_legacy_module() -> None:
    old_module = "free" + "form_templates"
    new_module = "grounded_database_templates"
    search_roots = [ROOT / "src", ROOT / "tests", ROOT / "evals"]

    assert not (ROOT / "src" / "baseball_rag" / "db" / f"{old_module}.py").exists()
    assert (ROOT / "src" / "baseball_rag" / "db" / f"{new_module}.py").exists()
    for path in (
        path
        for root in search_roots
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    ):
        text = path.read_text(encoding="utf-8")
        assert not _python_imports_module(text, f"baseball_rag.db.{old_module}")


def test_grounded_database_runtime_module_replaces_legacy_module() -> None:
    old_module = "free" + "form_runtime"
    new_module = "grounded_database_runtime"
    search_roots = [ROOT / "src", ROOT / "tests", ROOT / "evals"]

    assert not (ROOT / "src" / "baseball_rag" / "db" / f"{old_module}.py").exists()
    assert (ROOT / "src" / "baseball_rag" / "db" / f"{new_module}.py").exists()
    for path in (
        path
        for root in search_roots
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    ):
        text = path.read_text(encoding="utf-8")
        assert not _python_imports_module(text, f"baseball_rag.db.{old_module}")
        assert f"baseball_rag.db.{old_module}" not in text


def test_grounded_database_result_types_use_current_label() -> None:
    grounded_database_types = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_types.py"
    ).read_text(encoding="utf-8")
    legacy_title = LEGACY_DATABASE_LABEL.title()
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (ROOT / "src", ROOT / "tests", ROOT / "evals")
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    )

    assert f"{legacy_title}Result" not in combined
    assert f"Planned{legacy_title}Query" not in combined
    assert "GroundedDatabaseResult" in grounded_database_types
    assert "GroundedDatabaseQueryPlan" in grounded_database_types


def test_grounded_database_query_spec_has_no_legacy_intent_alias() -> None:
    grounded_database_types = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_types.py"
    ).read_text(encoding="utf-8")
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (ROOT / "src", ROOT / "tests", ROOT / "evals")
        for path in root.rglob("*.py")
        if path.name != "test_project_cleanup.py"
    )

    assert "QueryIntent" not in combined
    assert "class QuerySpec" in grounded_database_types


def test_grounded_database_intent_no_longer_exposes_sql_string_helper() -> None:
    grounded_database_intent = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_intent.py"
    ).read_text(encoding="utf-8")
    grounded_database_tests = (ROOT / "tests" / "test_grounded_database.py").read_text(
        encoding="utf-8"
    )

    assert "def _generate_sql(" not in grounded_database_intent
    assert "_generate_sql" not in grounded_database_tests


def test_grounded_database_intent_requires_explicit_stat_tables_after_retry() -> None:
    grounded_database_intent = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_intent.py"
    ).read_text(encoding="utf-8")

    assert "_recover_roster_intent" not in grounded_database_intent
    assert "Recover from LLM roster intents" not in grounded_database_intent


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
    llm_tests = (ROOT / "tests" / "test_llm.py").read_text(encoding="utf-8")

    assert "str | tuple" not in llm
    assert "backward compat" not in llm
    assert "_content_to_text" not in llm
    assert "reasoning_content" not in llm
    assert "reasoning_content" not in llm_tests


def test_llm_streaming_compatibility_api_is_removed() -> None:
    llm = (ROOT / "src" / "baseball_rag" / "generation" / "llm.py").read_text(encoding="utf-8")
    generation_init = (ROOT / "src" / "baseball_rag" / "generation" / "__init__.py").read_text(
        encoding="utf-8"
    )
    llm_tests = (ROOT / "tests" / "test_llm.py").read_text(encoding="utf-8")

    stream_api = "make_request_" + "stream"
    assert stream_api not in llm
    assert stream_api not in generation_init
    assert stream_api not in llm_tests


def test_retrieved_document_generation_surface_is_removed() -> None:
    generation_init = (ROOT / "src" / "baseball_rag" / "generation" / "__init__.py").read_text(
        encoding="utf-8"
    )
    prompt = (ROOT / "src" / "baseball_rag" / "generation" / "prompt.py").read_text(
        encoding="utf-8"
    )

    assert not (ROOT / "src" / "baseball_rag" / "generation" / "answer.py").exists()
    assert "from baseball_rag.generation.answer import answer" not in generation_init
    assert '"answer"' not in generation_init
    assert "build_grounded_prompt" not in prompt
    assert "build_stat_query_prompt" not in prompt
    assert "build_explanation_prompt" not in prompt
    assert "build_player_bio_prompt" not in prompt
    assert "PromptBundle" not in prompt


def test_open_prose_prompt_is_not_described_as_retrieval_fallback() -> None:
    combined = "\n".join(
        item
        for path in (
            ROOT / "src" / "baseball_rag" / "generation" / "prompt.py",
            ROOT / "tests" / "test_generation.py",
        )
        for item in _python_docstrings_and_comments(path.read_text(encoding="utf-8"))
    )

    assert "corpus returned no relevant documents" not in combined
    assert "no relevant docs are retrieved" not in combined
    assert "retrieved context" not in combined.lower()


def test_cli_no_year_leaderboard_tests_use_current_career_leader_language() -> None:
    cli_tests = (ROOT / "tests" / "test_cli_player_query.py").read_text(encoding="utf-8")
    names_and_prose = "\n".join(
        (
            *_python_definition_names(cli_tests),
            *_python_docstrings_and_comments(cli_tests),
        )
    )

    assert "Bug 2b" not in names_and_prose
    assert "latest-year" not in names_and_prose
    assert "MOST RECENT available data" not in names_and_prose
    assert "latest_year_should_be_determined_from_db" not in names_and_prose


def test_static_vocab_no_longer_indexes_hof_biographies() -> None:
    static_vocab = (ROOT / "src" / "baseball_rag" / "corpus" / "static_vocab.py").read_text(
        encoding="utf-8"
    )

    assert "HOF_DOC_IDS" not in static_vocab
    assert "static_doc_ids_for_query" not in static_vocab


def test_static_vocab_keeps_only_stat_definition_doc_id_lookup() -> None:
    static_vocab = (ROOT / "src" / "baseball_rag" / "corpus" / "static_vocab.py").read_text(
        encoding="utf-8"
    )

    assert "def query_mentions_stat_definition(" not in static_vocab
    assert "def query_asks_for_explanation(" not in static_vocab
    assert "EXPLANATION_TERMS" not in static_vocab


def test_stat_definition_vocab_no_longer_lives_in_retired_retrieval_package() -> None:
    general_explanation = (ROOT / "src" / "baseball_rag" / "general_explanation.py").read_text(
        encoding="utf-8"
    )
    static_vocab_tests = (ROOT / "tests" / "test_static_vocab.py").read_text(encoding="utf-8")

    assert not (ROOT / "src" / "baseball_rag" / "retrieval" / "__init__.py").exists()
    assert not (ROOT / "src" / "baseball_rag" / "retrieval" / "static_vocab.py").exists()
    assert (ROOT / "src" / "baseball_rag" / "corpus" / "static_vocab.py").exists()
    assert "baseball_rag.retrieval" not in general_explanation
    assert "baseball_rag.retrieval" not in static_vocab_tests


def test_hof_biography_corpus_is_removed() -> None:
    corpus_init = (ROOT / "src" / "baseball_rag" / "corpus" / "__init__.py").read_text(
        encoding="utf-8"
    )
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "hof").exists()
    assert "HOF_DIR" not in corpus_init
    assert "get_hof_bios" not in corpus_init
    assert "Hall of Fame" not in corpus_docs
    assert "Other checked-in corpus material" not in readme


def test_stat_definition_open_llm_path_is_not_described_as_fallback() -> None:
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    coverage_docs = (ROOT / "docs" / "guardrail-coverage.md").read_text(encoding="utf-8")
    eval_manifest = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text(encoding="utf-8"))
    old_phrase = "open LLM " + "fallback"
    eval_notes = "\n".join(_yaml_values_for_keys(eval_manifest, {"notes"}))

    assert old_phrase not in corpus_docs
    assert old_phrase not in coverage_docs
    assert old_phrase not in eval_notes


def test_duckdb_markdown_player_bio_builder_is_removed() -> None:
    player_bios = (ROOT / "src" / "baseball_rag" / "corpus" / "player_bios.py").read_text(
        encoding="utf-8"
    )

    assert "def build_player_bio(" not in player_bios
    assert "generated_player_profile_frontmatter" not in player_bios


def test_player_bio_name_resolution_has_no_string_id_wrapper() -> None:
    player_bios = (ROOT / "src" / "baseball_rag" / "corpus" / "player_bios.py").read_text(
        encoding="utf-8"
    )

    assert "def get_player_id_by_name(" not in player_bios


def test_generated_player_profile_lifecycle_helpers_are_removed() -> None:
    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "lifecycle.py").exists()


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
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    architecture_docs = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")

    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "__main__.py").exists()
    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "ingest.py").exists()
    assert "Retired Ingest Command" not in corpus_docs
    assert "retired ingest command" not in architecture_docs.lower()


def test_public_docs_use_grounded_database_question_naming() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    api_docs = (ROOT / "docs" / "api.md").read_text(encoding="utf-8")
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    eval_report = (ROOT / "docs" / "eval-report.md").read_text(encoding="utf-8")
    eval_manifest = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text(encoding="utf-8"))
    legacy_title = LEGACY_DATABASE_LABEL.title()
    eval_questions = "\n".join(str(case["question"]) for case in eval_manifest["questions"])

    assert f"{legacy_title} SQL" not in readme
    assert f"{legacy_title} query" not in api_docs
    assert f"{legacy_title} database answers" not in corpus_docs
    assert "grounded database fallback" not in readme
    assert "missing indexes" not in api_docs
    assert "indexed player biography" not in eval_report
    assert "indexed player biography" not in eval_questions
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
    grounded_database_runtime = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_runtime.py"
    ).read_text(encoding="utf-8")
    grounded_database_templates = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_templates.py"
    ).read_text(encoding="utf-8")
    legacy_label = LEGACY_DATABASE_LABEL
    legacy_route_function = f"should_route_deterministic_{legacy_label}"

    assert not (ROOT / "src" / "baseball_rag" / "routing" / f"{legacy_label}_ownership.py").exists()
    assert f"{legacy_label}_ownership" not in query_router
    assert f"deterministic_{legacy_label}_owns" not in query_router
    assert f"deterministic {legacy_label}" not in grounded_ownership.lower()
    assert legacy_route_function not in grounded_ownership
    assert f"def {legacy_route_function}(" not in grounded_database_runtime
    assert f"def {legacy_route_function}(" not in grounded_database_templates


def test_grounded_database_runtime_docs_use_current_label() -> None:
    grounded_database_intent = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_intent.py"
    ).read_text(encoding="utf-8")
    grounded_database_assembler = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_assembler.py"
    ).read_text(encoding="utf-8")
    grounded_database_runtime = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_runtime.py"
    ).read_text(encoding="utf-8")
    grounded_database_templates = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_templates.py"
    ).read_text(encoding="utf-8")
    grounded_database_schema = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_schema.py"
    ).read_text(encoding="utf-8")
    grounded_database_types = (
        ROOT / "src" / "baseball_rag" / "db" / "grounded_database_types.py"
    ).read_text(encoding="utf-8")
    team_history = (ROOT / "src" / "baseball_rag" / "db" / "team_history.py").read_text(
        encoding="utf-8"
    )

    prose = "\n".join(
        item
        for source in (
            grounded_database_intent,
            grounded_database_assembler,
            grounded_database_runtime,
            grounded_database_templates,
            grounded_database_schema,
            grounded_database_types,
            team_history,
        )
        for item in _python_docstrings_and_comments(source)
    )
    assert LEGACY_DATABASE_LABEL not in prose.lower()


def test_grounded_database_test_names_and_prose_use_current_label() -> None:
    test_sources = [
        (ROOT / "tests" / "test_api.py").read_text(encoding="utf-8"),
        (ROOT / "tests" / "test_conversation.py").read_text(encoding="utf-8"),
        (ROOT / "tests" / "test_grounded_database.py").read_text(encoding="utf-8"),
        (ROOT / "tests" / "test_stat_registry.py").read_text(encoding="utf-8"),
    ]

    names_and_prose = "\n".join(
        item
        for source in test_sources
        for item in (
            *_python_definition_names(source),
            *_python_docstrings_and_comments(source),
        )
    )
    assert LEGACY_DATABASE_LABEL not in names_and_prose.lower()


def test_architecture_fixtures_use_grounded_database_source_labels() -> None:
    diagram_tests = (ROOT / "tests" / "test_diagram_ui.py").read_text(encoding="utf-8")
    old_label = "free" + "form"

    assert f'label="{old_label}"' not in diagram_tests
    assert 'label="grounded_database"' in diagram_tests


def test_active_eval_prose_uses_grounded_database_label() -> None:
    eval_manifest = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text(encoding="utf-8"))

    prose = "\n".join(_yaml_values_for_keys(eval_manifest, {"description", "notes"}))

    assert LEGACY_DATABASE_LABEL not in prose.lower()


def test_active_eval_ids_use_grounded_database_label() -> None:
    eval_manifest = yaml.safe_load((ROOT / "evals" / "questions.yaml").read_text(encoding="utf-8"))

    case_ids = [str(case["id"]) for case in eval_manifest["questions"]]

    assert all(LEGACY_DATABASE_LABEL not in case_id for case_id in case_ids)
    assert "grounded_database_triple_crown" in case_ids
    assert "row_count_grounded_database_limit" in case_ids


def test_retired_corpus_manifest_lifecycle_is_removed() -> None:
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    development_docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")
    architecture_docs = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "diagnostics.py").exists()
    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "lifecycle.py").exists()
    assert "persist-dir" not in readme
    assert "old ignored manifest" not in corpus_docs
    assert "old ignored manifest" not in development_docs
    assert "old ignored manifest" not in architecture_docs
    assert "old ignored manifest" not in readme


def test_corpus_diagnostics_cli_surface_is_removed() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    corpus_docs = (ROOT / "docs" / "corpus.md").read_text(encoding="utf-8")
    development_docs = (ROOT / "docs" / "development.md").read_text(encoding="utf-8")

    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "__main__.py").exists()
    assert not (ROOT / "src" / "baseball_rag" / "corpus" / "diagnostics.py").exists()
    assert not (ROOT / "tests" / "test_corpus_diagnostics.py").exists()
    assert "baseball_rag.corpus diagnostics" not in readme
    assert "baseball_rag.corpus diagnostics" not in corpus_docs
    assert "baseball_rag.corpus diagnostics" not in development_docs


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
