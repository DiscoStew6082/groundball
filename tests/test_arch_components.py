"""Phase 1: Architecture Diagram Component Registry tests."""

from baseball_rag.arch import (
    DiagramComponent,
    Layer,
    TestStatus,
    get_registry,
)
from baseball_rag.arch.components import get_source_snippet

# ---------------------------------------------------------------------------
# Phase 1.1 — DiagramComponent dataclass
# ---------------------------------------------------------------------------


class TestDiagramComponentDataclass:
    def test_component_has_all_required_fields(self):
        comp = DiagramComponent(
            id="query-router",
            label="Query Router",
            description="Routes queries to stat or RAG pipeline.",
            layer=Layer.ROUTING,
            file_path="src/baseball_rag/routing/query_router.py",
            test_status=None,
        )
        assert comp.id == "query-router"
        assert comp.label == "Query Router"
        assert comp.layer is Layer.ROUTING

    def test_layer_enum_has_five_layers(self):
        names = {layer.name for layer in Layer}
        assert names == {"API", "ROUTING", "RETRIEVAL", "DATA", "GENERATION"}
        values = {layer.value for layer in Layer}
        assert values == {"api", "routing", "retrieval", "data", "generation"}

    def test_components_compare_by_id_equality(self):
        a = DiagramComponent(
            id="duckdb",
            label="DuckDB",
            description="OLAP engine.",
            layer=Layer.DATA,
            file_path="src/baseball_rag/db/duckdb_schema.py",
        )
        b = DiagramComponent(
            id="duckdb",
            label="DuckDB (renamed)",
            description="Different desc.",
            layer=Layer.GENERATION,  # different layer
            file_path="other.py",
        )
        assert a == b
        # Different ids are not equal
        c = DiagramComponent(
            id="llm",
            label="LLM",
            description="Language model.",
            layer=Layer.GENERATION,
            file_path="src/baseball_rag/generation/llm.py",
        )
        assert a != c

    def test_hash_by_id(self):
        """Components with the same id hash identically (needed for dict keys)."""
        a = DiagramComponent(id="x", label="A", description="D", layer=Layer.API, file_path="a.py")
        b = DiagramComponent(id="x", label="B", description="D", layer=Layer.DATA, file_path="b.py")
        assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# Phase 1.2 — Component Registry singleton
# ---------------------------------------------------------------------------


class TestComponentRegistrySingleton:
    def test_get_registry_returns_same_instance_every_time(self):
        reg1 = get_registry()
        reg2 = get_registry()
        assert reg1 is reg2

    def test_registry_tracks_all_architecture_components(self):
        reg = get_registry()
        component_ids = {c.id for c in reg.all()}
        expected = {
            "cli",
            "api-server",
            "query-router",
            "claim-verifier",
            "duckdb",
            "llm",
            "prompt",
        }
        assert expected.issubset(component_ids)
        assert "corpus-grounding" not in component_ids

    def test_components_cover_required_modules(self):
        reg = get_registry()
        ids = {c.id for c in reg.all()}
        required = ["cli", "query-router", "claim-verifier", "duckdb", "llm"]
        assert all(r in ids for r in required)

    def test_query_router_description_names_current_four_routes(self):
        """Registry copy reflects the current four-route request architecture."""
        reg = get_registry()
        router = reg.get("query-router")

        assert router is not None
        assert "stat_query" in router.description
        assert "player_biography" in router.description
        assert "freeform_query" in router.description
        assert "general_explanation" in router.description


# ---------------------------------------------------------------------------
# Phase 1.3 — Registry by layer
# ---------------------------------------------------------------------------


class TestRegistryByLayer:
    def test_get_components_by_layer_returns_only_that_layer(self):
        reg = get_registry()
        routing = reg.by_layer(Layer.ROUTING)
        assert all(c.layer == Layer.ROUTING for c in routing)

    def test_each_layer_returns_at_least_one_component(self):
        reg = get_registry()
        for layer in Layer:
            components = reg.by_layer(layer)
            assert len(components) >= 1, f"Layer {layer.value} has no components"

    def test_all_five_layers_are_represented_in_registry(self):
        reg = get_registry()
        represented = {c.layer for c in reg.all()}
        assert represented == set(Layer)


# ---------------------------------------------------------------------------
# Phase 1.4 — Component file path resolution
# ---------------------------------------------------------------------------


class TestComponentFilePathResolution:
    def test_get_source_snippet_reads_first_n_lines(self):
        # Uses the string-based API (component_id, n)
        snippet = get_source_snippet("cli", n=5)
        assert snippet is not None
        lines = [ln for ln in snippet.splitlines() if ln.strip()]
        assert len(lines) <= 5

    def test_get_source_snippet_returns_none_for_missing_file(self):
        result = get_source_snippet("nonexistent-component-xyz")
        assert result is None

    def test_get_source_snippet_is_string(self):
        result = get_source_snippet("cli", n=3)
        assert isinstance(result, str)

    def test_n_parameter_respected(self):
        snippet_3 = get_source_snippet("query-router", n=3)
        snippet_10 = get_source_snippet("query-router", n=10)
        assert snippet_3 is not None and snippet_10 is not None
        # 3-line version should have at most 3 lines (may have fewer if file is shorter)
        assert len(snippet_3.splitlines()) <= 3


# ---------------------------------------------------------------------------
# Phase 1.5 — TestStatus enum and component display with status indicator
# ---------------------------------------------------------------------------


class TestTestStatusFromLatestRun:
    def test_status_emoji_pass(self):
        assert TestStatus.PASS.emoji() == "✅"

    def test_status_emoji_fail(self):
        assert TestStatus.FAIL.emoji() == "❌"

    def test_status_emoji_unknown(self):
        assert TestStatus.UNKNOWN.emoji() == "⚪"

    def test_registry_can_store_test_status_per_component(self):
        reg = get_registry()
        # Set pass status on query-router
        reg.set_test_status("query-router", TestStatus.PASS)
        comp = reg.get("query-router")
        assert comp is not None
        assert comp.test_status == TestStatus.PASS

    def test_component_display_includes_status_indicator(self):
        """A component with a FAIL status shows the fail indicator."""
        comp = DiagramComponent(
            id="claim-verifier",
            label="Biography Claim Verifier",
            description="Verifies extracted stat claims.",
            layer=Layer.RETRIEVAL,
            file_path="src/baseball_rag/db/player_stat_claims.py",
            test_status=TestStatus.FAIL,
        )
        assert "❌" in comp.status_indicator()

    def test_component_with_no_status_shows_neutral_marker(self):
        """A component with no test_status set shows a neutral placeholder."""
        comp = DiagramComponent(
            id="llm",
            label="LLM",
            description="Language model.",
            layer=Layer.GENERATION,
            file_path="src/baseball_rag/generation/llm.py",
            test_status=None,
        )
        indicator = comp.status_indicator()
        # Should be the neutral ⚪ when no status is set
        assert indicator == "⚪"

    def test_set_test_status_updates_existing_component(self):
        reg = get_registry()
        # Initially unknown (None)
        comp_before = reg.get("duckdb")
        assert comp_before is not None

        reg.set_test_status("duckdb", TestStatus.PASS)

        comp_after = reg.get("duckdb")
        assert comp_after is not None
        assert comp_after.test_status == TestStatus.PASS
        assert comp_after.id == "duckdb"  # id preserved

    def test_set_test_status_unknown_then_pass_transitions_correctly(self):
        """Simulate a component going from unknown → pass after a successful test run."""
        reg = get_registry()
        reg.set_test_status("llm", TestStatus.UNKNOWN)
        assert reg.get("llm").test_status == TestStatus.UNKNOWN

        # Simulate running tests and passing
        reg.set_test_status("llm", TestStatus.PASS)
        assert reg.get("llm").test_status == TestStatus.PASS
