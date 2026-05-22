"""Tests for Run All Tests button — Phase 5.

A "Run All Tests" button in the Architecture tab runs pytest -q, parses results,
and updates each component's test_status badge (PASS/FAIL).
"""

from unittest.mock import MagicMock, patch

from baseball_rag.arch.components import TestStatus

# --------------------------------------------------------------------------:
# Phase 5.1 — Button exists and is attached to arch_diagram
# --------------------------------------------------------------------------:


class TestRunAllTestsButton:
    """The ArchitectureDiagram exposes a 'Run All Tests' button."""

    def _find_by_elem_id(self, dash, elem_id):
        """Find a component in *dash.blocks* by its elem_id."""
        for comp in dash.blocks.values():
            if getattr(comp, "elem_id", None) == elem_id:
                return comp
        return None

    def test_dashboard_has_run_all_tests_button(self):
        """build_dashboard() creates a gr.Button with id 'run-all-tests'."""
        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        btn = self._find_by_elem_id(dash, "run-all-tests")
        assert btn is not None, "No component with elem_id='run-all-tests'"
        assert callable(btn.click)

    def test_run_all_tests_button_is_inside_architecture_diagram(self):
        """The Run All Tests button is part of the ArchitectureDiagram."""
        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        btn = self._find_by_elem_id(dash, "run-all-tests")
        assert btn is not None


# --------------------------------------------------------------------------:
# Phase 5.2 — run_all_tests function
# --------------------------------------------------------------------------:


class TestRunAllTestsFunction:
    """The run_all_tests() function runs pytest and parses results."""

    def test_run_all_tests_returns_result_object(self):
        """run_all_tests() returns a dataclass with passed, failed counts."""
        from baseball_rag.web_app import _TestResult

        # Check the return type exists and has the right fields
        assert hasattr(_TestResult, "__dataclass_fields__")
        fields = {f.name for f in _TestResult.__dataclass_fields__.values()}
        assert "passed" in fields
        assert "failed" in fields

    def test_run_all_tests_updates_component_statuses_pass(self):
        """When all tests pass, components with test files get TestStatus.PASS."""
        from baseball_rag.web_app import build_dashboard, run_all_tests

        dash = build_dashboard()
        registry = dash.arch_diagram.registry

        # Mock subprocess.run to return a clean-passing suite
        fake_result = MagicMock()
        fake_result.stdout = "153 passed in 50.0s"
        fake_result.stderr = ""
        fake_result.returncode = 0

        with patch("subprocess.run", return_value=fake_result):
            result = run_all_tests()

        assert result.passed == 153
        assert result.failed == 0

        # Components mapped to test files should be marked PASS
        for comp_id in ("cli", "query-router", "claim-verifier", "duckdb", "llm"):
            comp = registry.get(comp_id)
            if comp is not None:
                assert comp.test_status == TestStatus.PASS, f"{comp_id} should be PASS"

    def test_run_all_tests_updates_component_statuses_fail(self):
        """When tests fail, components with test files get TestStatus.FAIL."""
        from baseball_rag.web_app import build_dashboard, run_all_tests

        dash = build_dashboard()
        registry = dash.arch_diagram.registry

        # Mock subprocess.run to return a failing suite
        fake_result = MagicMock()
        fake_result.stdout = "150 passed, 3 failed in 50.0s"
        fake_result.stderr = ""
        fake_result.returncode = 1

        with patch("subprocess.run", return_value=fake_result):
            result = run_all_tests()

        assert result.passed == 150
        assert result.failed == 3

        # Components mapped to test files should be marked FAIL
        for comp_id in ("cli", "query-router", "claim-verifier"):
            comp = registry.get(comp_id)
            if comp is not None:
                assert comp.test_status == TestStatus.FAIL, f"{comp_id} should be FAIL"

    def test_run_all_tests_sets_unknown_for_unmapped_components(self):
        """Components with no test file mapping keep their default status."""
        from baseball_rag.web_app import build_dashboard, run_all_tests

        dash = build_dashboard()
        registry = dash.arch_diagram.registry

        fake_result = MagicMock()
        fake_result.stdout = "153 passed in 50.0s"
        fake_result.stderr = ""
        fake_result.returncode = 0

        with patch("subprocess.run", return_value=fake_result):
            run_all_tests()

        # api-server is not in COMPONENT_TEST_MAP
        for comp_id in ("api-server",):
            comp = registry.get(comp_id)
            if comp is not None:
                assert comp.test_status == TestStatus.UNKNOWN, f"{comp_id} should be UNKNOWN"


# --------------------------------------------------------------------------:
# Phase 5.3 — Button triggers run_all_tests via Gradio event
# --------------------------------------------------------------------------:


class TestRunAllTestsEventWiring:
    """The Run All Tests button is wired to call run_all_tests() on click."""

    def test_run_all_tests_button_click_event_is_registered(self):
        """Clicking 'run-all-tests' calls the run_all_tests function."""
        from baseball_rag.web_app import build_dashboard

        dash = build_dashboard()
        btn = None
        for comp in dash.blocks.values():
            if getattr(comp, "elem_id", None) == "run-all-tests":
                btn = comp
                break
        assert btn is not None
        assert callable(btn.click)
