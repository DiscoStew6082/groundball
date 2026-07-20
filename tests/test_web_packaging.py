"""Deployment artifact contract for the unified Ground Ball web application."""

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_vercel_image_builds_and_serves_the_svelte_fastapi_application():
    """The deployable image builds web assets and contains no Gradio runtime."""
    dockerfile = (ROOT / "Dockerfile.vercel").read_text(encoding="utf-8")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lockfile = (ROOT / "uv.lock").read_text(encoding="utf-8")

    assert "FROM node:22-alpine AS web-build" in dockerfile
    assert "COPY web/package.json web/package-lock.json ./" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "COPY web/ ./" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "COPY --from=web-build /web/dist /app/web/dist" in dockerfile
    assert "COPY release/bundle/ /app/release-bundle/" in dockerfile
    assert "GROUNDBALL_RELEASE_BUNDLE=/app/release-bundle" in dockerfile
    assert (
        "GROUNDBALL_RUNTIME_CONFIG=/app/release-config/protected-preview-runtime.json" in dockerfile
    )
    assert "ARG GROUNDBALL_SOURCE_COMMIT" not in dockerfile
    assert "GROUNDBALL_SOURCE_COMMIT=${GROUNDBALL_SOURCE_COMMIT}" not in dockerfile
    assert "baseball_rag.provider_runtime_cache" in dockerfile
    assert "baseball_rag.release_bundle check /app/release-bundle" not in dockerfile
    assert "--expected-source-commit" not in dockerfile
    assert "baseball_rag.release_runtime import release_readiness" not in dockerfile
    assert "PYTHONDONTWRITEBYTECODE=1" in dockerfile
    assert "groupadd --system --gid 10001 groundball" in dockerfile
    assert "useradd --system --uid 10001" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert dockerfile.index("baseball_rag.provider_runtime_cache") < dockerfile.index(
        "USER 10001:10001"
    )
    assert "chmod -R a-w /app/release-bundle /app/release-config" in dockerfile
    assert "baseball_rag.db.download" not in dockerfile
    assert "huggingface.co" not in dockerfile
    assert "rm -f /app/src/baseball_rag/db/download.py" in dockerfile
    assert "/app/src/baseball_rag/db/secondary_sources/retrosheet_events.py" in dockerfile
    assert "/app/src/baseball_rag/generation/llm.py" in dockerfile
    assert "rm -rf /app/src/baseball_rag/query/catalog" in dockerfile
    assert "baseball_rag.web_app" in dockerfile
    assert "${PORT:-80}" in dockerfile
    assert "GRADIO" not in dockerfile.upper()

    dependencies = pyproject["project"]["dependencies"]
    assert not any(dependency.lower().startswith("gradio") for dependency in dependencies)
    assert '\nname = "gradio"\n' not in lockfile

    for ignore_file in (".dockerignore", ".vercelignore"):
        ignored = (ROOT / ignore_file).read_text(encoding="utf-8").splitlines()
        assert "web/node_modules/" in ignored
        assert "web/dist/" in ignored
        assert "src/baseball_rag/web_dist/" in ignored
        assert "web/" not in ignored


def test_default_container_and_ci_use_the_same_svelte_application() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    vite_config = (ROOT / "web" / "vite.config.js").read_text(encoding="utf-8")

    assert "FROM node:22-alpine AS web-build" in dockerfile
    assert "RUN npm ci" in dockerfile
    assert "RUN npm run build" in dockerfile
    assert "COPY --from=web-build /web/dist /app/web/dist" in dockerfile
    assert "baseball_rag.web_app" in dockerfile
    assert "8001" not in dockerfile
    assert "GROUNDBALL_ARCHITECTURE_ENABLED=0" in dockerfile
    assert "GROUNDBALL_DEVELOPER_TOOLS_ENABLED=0" in dockerfile

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


def test_obsolete_web_configuration_and_sources_stay_absent() -> None:
    vite_config = (ROOT / "web" / "vite.config.js").read_text(encoding="utf-8")
    vitest_config = (ROOT / "web" / "vitest.config.js").read_text(encoding="utf-8")

    assert "plugins: [svelte()]" in vite_config
    assert "\n  resolve:" not in vite_config
    assert "conditions:" not in vite_config
    for configuration in (vite_config, vitest_config):
        assert "configFile" not in configuration
        assert "alias:" not in configuration
        assert "node_modules/svelte" not in configuration
        assert "svelte/src/" not in configuration
    assert "conditions: ['browser']" in vitest_config
    assert not (ROOT / "web" / "svelte.config.js").exists()
    assert not (ROOT / "web" / "src" / "lib" / "downloads.js").exists()
    assert not (ROOT / "web" / "src" / "prototypes" / "query-recipe").exists()


def test_packaged_browser_bundle_uses_only_the_new_query_composition_root() -> None:
    bundled_assets = list((ROOT / "src" / "baseball_rag" / "web_dist" / "assets").glob("*.js"))

    assert len(bundled_assets) == 1
    bundle = bundled_assets[0].read_text(encoding="utf-8")
    assert "/api/query-runs" in bundle
    assert "/api/query-catalog" in bundle
    assert 'fetch("/api/query")' not in bundle
