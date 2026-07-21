"""Tests for the FastAPI/Svelte application launcher."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from baseball_rag import web_app


def test_parse_ttl_seconds() -> None:
    assert web_app._parse_ttl_seconds(None) is None
    assert web_app._parse_ttl_seconds("") is None
    assert web_app._parse_ttl_seconds("0") is None
    assert web_app._parse_ttl_seconds("45") == 45.0
    assert web_app._parse_ttl_seconds("2.5") == 2.5


@pytest.mark.parametrize("value", ["soon", "-1", "inf", "nan"])
def test_parse_ttl_seconds_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        web_app._parse_ttl_seconds(value)


def test_launch_app_runs_uvicorn_with_requested_binding(monkeypatch) -> None:
    configs = []
    servers = []

    class FakeConfig:
        def __init__(self, app, **kwargs):
            configs.append((app, kwargs))

    class FakeServer:
        def __init__(self, config):
            self.config = config
            self.should_exit = False
            servers.append(self)

        def run(self):
            return None

    monkeypatch.setattr(web_app.uvicorn, "Config", FakeConfig)
    monkeypatch.setattr(web_app.uvicorn, "Server", FakeServer)

    web_app._launch_app(server_name="127.0.0.1", server_port=7861, ttl_seconds=None)

    assert configs == [
        (
            "baseball_rag.api.server:app",
            {"host": "127.0.0.1", "port": 7861, "log_level": "info"},
        )
    ]
    assert len(servers) == 1


def test_launch_app_ttl_requests_graceful_uvicorn_exit(monkeypatch) -> None:
    timers = []
    servers = []

    class FakeTimer:
        def __init__(self, interval, function):
            self.interval = interval
            self.function = function
            self.daemon = False
            timers.append(self)

        def start(self):
            self.function()

        def cancel(self):
            return None

    class FakeServer:
        def __init__(self, _config):
            self.should_exit = False
            servers.append(self)

        def run(self):
            assert self.should_exit is True

    monkeypatch.setattr(web_app.threading, "Timer", FakeTimer)
    monkeypatch.setattr(web_app.uvicorn, "Config", lambda *args, **kwargs: object())
    monkeypatch.setattr(web_app.uvicorn, "Server", FakeServer)

    web_app._launch_app(server_name="0.0.0.0", server_port=7860, ttl_seconds=30)

    assert timers[0].interval == 30
    assert timers[0].daemon is True
    assert servers[0].should_exit is True


def test_dev_main_uses_local_port_7861(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(web_app, "_launch_app", lambda **kwargs: calls.append(kwargs))

    web_app.dev_main([])

    assert calls == [{"server_name": "127.0.0.1", "server_port": 7861, "ttl_seconds": None}]


def test_main_uses_public_server_defaults(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(web_app, "_launch_app", lambda **kwargs: calls.append(kwargs))

    web_app.main([])

    assert calls == [{"server_name": "0.0.0.0", "server_port": 7860, "ttl_seconds": None}]


def test_project_exposes_only_clean_groundball_scripts_without_gradio_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert "gradio" not in pyproject["project"]["dependencies"]
    assert pyproject["project"]["scripts"]["groundball-ui"] == "baseball_rag.web_app:dev_main"
    assert pyproject["project"]["scripts"] == {
        "groundball": "baseball_rag.cli:main",
        "groundball-ui": "baseball_rag.web_app:dev_main",
    }
