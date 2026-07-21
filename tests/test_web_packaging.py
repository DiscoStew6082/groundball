"""Release artifact contract for the unified Ground Ball web application."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_python_distribution_has_no_obsolete_gradio_runtime() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lockfile = (ROOT / "uv.lock").read_text(encoding="utf-8")

    dependencies = pyproject["project"]["dependencies"]
    assert not any(dependency.lower().startswith("gradio") for dependency in dependencies)
    assert '\nname = "gradio"\n' not in lockfile


def test_ci_builds_the_svelte_application_used_by_the_python_package() -> None:
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    vite_config = (ROOT / "web" / "vite.config.js").read_text(encoding="utf-8")

    assert "actions/setup-node@v6" in ci
    assert "npm ci" in ci
    assert "npm test" in ci
    assert "npm run build" in ci
    assert "'/api': 'http://127.0.0.1:7861'" in vite_config


def test_web_package_exposes_explicit_fallback_sync_and_check_commands() -> None:
    package = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))

    assert package["engines"]["node"] == ">=22.12.0"
    assert package["scripts"]["build"] == "vite build"
    assert package["scripts"]["package:sync"] == "node scripts/package-dist.mjs sync"
    assert package["scripts"]["package:check"] == "node scripts/package-dist.mjs check"


def test_web_configuration_keeps_warning_free_defaults_and_removes_obsolete_sources() -> None:
    vite_config = (ROOT / "web" / "vite.config.js").read_text(encoding="utf-8")
    vitest_config = (ROOT / "web" / "vitest.config.js").read_text(encoding="utf-8")
    svelte_config = (ROOT / "web" / "svelte.config.js").read_text(encoding="utf-8")

    assert "plugins: [svelte()]" in vite_config
    assert "\n  resolve:" not in vite_config
    assert "conditions:" not in vite_config
    for configuration in (vite_config, vitest_config, svelte_config):
        assert "configFile" not in configuration
        assert "alias:" not in configuration
        assert "node_modules/svelte" not in configuration
        assert "svelte/src/" not in configuration
    assert "conditions: ['browser']" in vitest_config
    assert svelte_config == (
        "// This explicit defaults contract prevents vite-plugin-svelte's missing-config warning.\n"
        "export default {};\n"
    )
    assert not (ROOT / "web" / "src" / "lib" / "downloads.js").exists()
    assert not (ROOT / "web" / "src" / "prototypes" / "query-recipe").exists()


def test_packaged_browser_bundle_uses_only_the_new_query_composition_root() -> None:
    bundled_assets = list((ROOT / "src" / "baseball_rag" / "web_dist" / "assets").glob("*.js"))

    assert len(bundled_assets) == 1
    bundle = bundled_assets[0].read_text(encoding="utf-8")
    assert "/api/query-runs" in bundle
    assert "/api/query-catalog" in bundle
    assert 'fetch("/api/query")' not in bundle
