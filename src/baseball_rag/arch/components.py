"""Architecture diagram data model — components, layers, and the singleton registry."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# Layer
# ---------------------------------------------------------------------------


class Layer(Enum):
    """Vertical layer in the baseball-rag architecture stack."""

    API = "api"
    ROUTING = "routing"
    RETRIEVAL = "retrieval"
    DATA = "data"
    GENERATION = "generation"


# ---------------------------------------------------------------------------
# TestStatus
# ---------------------------------------------------------------------------


class TestStatus(Enum):
    """Test result status for a component, used as a visual indicator badge.

    Maps to emoji:
      - pass  → ✅
      - fail  → ❌
      - unknown → ⚪ (U+26AA)
    """

    __test__ = False  # tell pytest not to collect this as a test class

    PASS = "pass"
    FAIL = "fail"
    UNKNOWN = "unknown"

    def emoji(self) -> str:
        """Return an emoji symbol for this status."""
        return {
            TestStatus.PASS: "\u2705",
            TestStatus.FAIL: "\u274c",
            TestStatus.UNKNOWN: "\u26aa",
        }[self]


# Alias for backwards compatibility
ComponentTestStatus = TestStatus


# ---------------------------------------------------------------------------
# DiagramComponent
# ---------------------------------------------------------------------------


@dataclass(eq=False)
class DiagramComponent:
    """A single node in the architecture diagram."""

    id: str  # unique slug e.g. "query-router"
    label: str  # human-readable "Query Router"
    description: str  # one-liner
    layer: Layer  # which vertical layer this belongs to
    file_path: str  # relative path from repo root to the source file
    test_status: TestStatus | None = None

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DiagramComponent):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)

    def status_indicator(self) -> str:
        """Return the emoji indicator for this component's test status.

        Returns a neutral ⚪ when no status is set.
        """
        if self.test_status is None:
            return "\u26aa"  # ⚪
        return self.test_status.emoji()


# ---------------------------------------------------------------------------
# ComponentRegistry
# ---------------------------------------------------------------------------

# _repo_root is the repository root (parent of src/)
# __file__ = .../src/baseball_rag/arch/components.py → parents[0]=arch,
#   [1]=baseball_rag, [2]=src, [3]=project-root
_repo_root = str(Path(__file__).parents[3])


class ComponentRegistry:
    """In-memory store for all DiagramComponent instances (singleton)."""

    def __init__(self) -> None:
        self._components: dict[str, DiagramComponent] = {}
        self._register_defaults()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, component: DiagramComponent) -> None:
        self._components[component.id] = component

    def get(self, component_id: str) -> DiagramComponent | None:
        return self._components.get(component_id)

    def all(self) -> list[DiagramComponent]:
        return list(self._components.values())

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def by_layer(self, layer: Layer) -> list[DiagramComponent]:
        """Return all components that belong to *layer*, sorted by label."""
        return sorted(
            [c for c in self._components.values() if c.layer == layer],
            key=lambda c: c.label,
        )

    @property
    def layers(self) -> list[Layer]:
        """All layers that have at least one registered component, in enum order."""
        seen: set[Layer] = {c.layer for c in self._components.values()}
        return [ly for ly in Layer if ly in seen]

    # ------------------------------------------------------------------
    # Test status management
    # ------------------------------------------------------------------

    def set_test_status(self, component_id: str, status: TestStatus) -> None:
        """Update the test status for a registered component."""
        comp = self._components.get(component_id)
        if comp is not None:
            self._components[component_id] = DiagramComponent(
                id=comp.id,
                label=comp.label,
                description=comp.description,
                layer=comp.layer,
                file_path=comp.file_path,
                test_status=status,
            )

    # ------------------------------------------------------------------
    # File reading
    # ------------------------------------------------------------------

    def get_source_snippet(self, component_id: str, n: int = 10) -> str | None:
        """Return the first n lines of the component's source file.

        Returns None if the file does not exist.
        """
        comp = self._components.get(component_id)
        if comp is None:
            return None
        full_path = os.path.join(_repo_root, comp.file_path)
        try:
            with open(full_path, encoding="utf-8") as fh:
                return "".join(fh.readlines()[:n])
        except OSError:
            return None

    # ------------------------------------------------------------------
    # Defaults — register the active runtime components
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        self.register(
            DiagramComponent(
                id="cli",
                label="CLI Entry Point",
                description=(
                    "Command-line interface that accepts natural-language baseball questions."
                ),
                layer=Layer.API,
                file_path="src/baseball_rag/cli.py",
            )
        )
        self.register(
            DiagramComponent(
                id="gradio",
                label="Gradio UI",
                description="Browser dashboard where a user submits questions and views results.",
                layer=Layer.API,
                file_path="src/baseball_rag/web_app.py",
            )
        )
        self.register(
            DiagramComponent(
                id="api-server",
                label="API Server",
                description=(
                    "FastAPI server exposing a /query POST endpoint for programmatic access."
                ),
                layer=Layer.API,
                file_path="src/baseball_rag/api/server.py",
            )
        )
        self.register(
            DiagramComponent(
                id="query-router",
                label="Query Router",
                description=(
                    "LLM-assisted intent classifier that routes to stat_query, "
                    "player_biography, grounded_database_question, or general_explanation paths."
                ),
                layer=Layer.ROUTING,
                file_path="src/baseball_rag/routing/query_router.py",
            )
        )
        self.register(
            DiagramComponent(
                id="claim-verifier",
                label="Biography Claim Verifier",
                description="DuckDB-backed verifier for extracted biography stat claims.",
                layer=Layer.RETRIEVAL,
                file_path="src/baseball_rag/db/player_stat_claims.py",
            )
        )
        self.register(
            DiagramComponent(
                id="duckdb",
                label="DuckDB Schema & Queries",
                description=(
                    "In-memory DuckDB with CSV tables for batting, pitching, fielding, people, "
                    "and a teams lookup map."
                ),
                layer=Layer.DATA,
                file_path="src/baseball_rag/db/duckdb_schema.py",
            )
        )
        self.register(
            DiagramComponent(
                id="llm",
                label="LLM (Gemma via LM Studio)",
                description=(
                    "Local Gemma-4-26b model called via LM Studio's "
                    "OpenAI-compatible /chat/completions API."
                ),
                layer=Layer.GENERATION,
                file_path="src/baseball_rag/generation/llm.py",
            )
        )
        self.register(
            DiagramComponent(
                id="prompt",
                label="Prompt Templates",
                description=(
                    "Hand-crafted prompt bundles (system + user) "
                    "for stat queries and general explanations."
                ),
                layer=Layer.GENERATION,
                file_path="src/baseball_rag/generation/prompt.py",
            )
        )


# Module-level singleton instance
_registry: ComponentRegistry | None = None


def get_registry() -> ComponentRegistry:
    """Return the global _Registry singleton (created on first call)."""
    global _registry
    if _registry is None:
        _registry = ComponentRegistry()
    return _registry


@lru_cache(maxsize=1)
def get_components_by_layer(layer: Layer) -> list[DiagramComponent]:
    """Return all registered components that belong to *layer*."""
    return get_registry().by_layer(layer)


def get_source_snippet(component_id: str, n: int = 10) -> str | None:
    """Return the first n lines of a component's source file, or None if not found."""
    return get_registry().get_source_snippet(component_id, n)
