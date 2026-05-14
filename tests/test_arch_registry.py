"""Phase 1.2: Component registry singleton and queries."""

from baseball_rag.arch import (
    Layer,
    get_components_by_layer,
    get_registry,
)


class TestRegistrySingleton:
    """Phase 1.2: get_registry() returns the same instance every time (singleton)."""

    def test_singleton_returns_same_instance(self) -> None:
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2


class TestRegistryTracksComponents:
    """Phase 1.2: Registry tracks all architecture components."""

    def test_all_returns_components(self) -> None:
        reg = get_registry()
        all_comps = reg.all()
        assert len(all_comps) >= 8

    def test_known_component_ids_present(self) -> None:
        reg = get_registry()
        ids = {c.id for c in reg.all()}
        expected = {
            "cli",
            "api-server",
            "query-router",
            "claim-verifier",
            "duckdb",
            "corpus-grounding",
            "llm",
            "prompt",
        }
        assert expected.issubset(ids)

    def test_get_by_id(self) -> None:
        reg = get_registry()
        comp = reg.get("query-router")
        assert comp is not None
        assert comp.id == "query-router"
        assert comp.layer == Layer.ROUTING

    def test_get_unknown_id_returns_none(self) -> None:
        reg = get_registry()
        assert reg.get("does-not-exist") is None


class TestRegistryByLayerIntegration:
    """Phase 1.3: get_components_by_layer() helper for the public API."""

    def test_routing_layer_only(self) -> None:
        routing = get_components_by_layer(Layer.ROUTING)
        assert len(routing) >= 1
        assert all(c.layer == Layer.ROUTING for c in routing)

    def test_each_required_layer_has_at_least_one_component(self) -> None:
        for layer in [Layer.API, Layer.ROUTING, Layer.RETRIEVAL, Layer.DATA, Layer.GENERATION]:
            comps = get_components_by_layer(layer)
            assert len(comps) >= 1, f"Layer {layer.name} has no components"

    def test_all_five_layers_represented(self) -> None:
        reg = get_registry()
        layers_with_components = set(c.layer for c in reg.all())
        expected = {Layer.API, Layer.ROUTING, Layer.RETRIEVAL, Layer.DATA, Layer.GENERATION}
        assert layers_with_components == expected
