"""Pytest configuration."""

from __future__ import annotations

import pytest


# ----------------------------------------------------------------------
# Auto-apply markers based on filename patterns — no per-test decoration needed.
# ----------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    """Register marker names so pytest knows about them."""
    config.addinivalue_line("markers", "unit: fast, mocked tests — no external services required")
    config.addinivalue_line("markers", "integration: requires live services (LM Studio, Gradio)")
    config.addinivalue_line("markers", "slow: long-running or heavy setup")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Auto-tag tests by filename so 'pytest -m unit' skips integration and slow suites."""
    integration = {
        "test_api",
        "test_cli_player_query",
        "test_dashboard",
        "test_diagram_ui",
        "test_generation",
        "test_gradio",
        "test_pipeline",
        "test_pipeline_tracing_integration",
        "test_router",
        "test_router_player_bio",
        "test_router_player_detection",
    }
    slow = {
        "test_corpus_content",
        "test_pipeline_tracing",
        "test_run_all_tests",
    }

    for item in items:
        name = item.path.stem
        if name in integration:
            item.add_marker(pytest.mark.integration)
        elif name in slow:
            item.add_marker(pytest.mark.slow)
        else:
            item.add_marker(pytest.mark.unit)
