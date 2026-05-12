"""Tests for Gradio web app — Phase 4 dashboard integration."""

import pytest

from baseball_rag import web_app


class TestGradio:
    def test_demo_is_blocks(self):
        """gr.Blocks dashboard exists and has arch_diagram attached."""
        assert hasattr(web_app, "demo")
        from gradio import Blocks

        assert isinstance(web_app.demo, Blocks)
        assert hasattr(web_app.demo, "arch_diagram")

    def test_build_dashboard_returns_blocks(self):
        """build_dashboard() returns a gr.Blocks with an arch_diagram."""
        demo = web_app.build_dashboard()
        from gradio import Blocks

        assert isinstance(demo, Blocks)
        assert hasattr(demo, "arch_diagram")

    def test_respond_without_diagram(self):
        """respond() works without a diagram (passthrough to answer())."""
        result = web_app.respond("who had the most HRs in 1970", [], diagram=None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_parse_ttl_seconds(self):
        """Server TTL accepts positive seconds and treats zero/unset as disabled."""
        assert web_app._parse_ttl_seconds(None) is None
        assert web_app._parse_ttl_seconds("") is None
        assert web_app._parse_ttl_seconds("0") is None
        assert web_app._parse_ttl_seconds("45") == 45.0
        assert web_app._parse_ttl_seconds("2.5") == 2.5

    def test_parse_ttl_seconds_rejects_invalid_values(self):
        """Server TTL values must be numeric and non-negative."""
        with pytest.raises(ValueError, match="number"):
            web_app._parse_ttl_seconds("soon")
        with pytest.raises(ValueError, match="non-negative"):
            web_app._parse_ttl_seconds("-1")
        with pytest.raises(ValueError, match="finite"):
            web_app._parse_ttl_seconds("inf")
        with pytest.raises(ValueError, match="finite"):
            web_app._parse_ttl_seconds("nan")

    def test_schedule_server_ttl_closes_then_forces_exit(self, monkeypatch):
        """A positive TTL closes Gradio and has a hard-exit fallback."""
        timers = []
        close_calls = []
        exit_codes = []

        class FakeTimer:
            def __init__(self, interval, function):
                self.interval = interval
                self.function = function
                self.daemon = False
                self.started = False
                timers.append(self)

            def start(self):
                self.started = True

        monkeypatch.setattr(web_app.threading, "Timer", FakeTimer)

        timer = web_app._schedule_server_ttl(
            30,
            close_fn=lambda: close_calls.append("closed"),
            exit_fn=exit_codes.append,
            hard_exit_grace_seconds=5,
        )

        assert timer is timers[0]
        assert timer.interval == 30
        assert timer.daemon is True
        assert timer.started is True

        timer.function()
        assert close_calls == ["closed"]
        assert len(timers) == 2
        assert timers[1].interval == 5
        assert timers[1].daemon is True
        assert timers[1].started is True

        timers[1].function()
        assert exit_codes == [0]

    def test_schedule_server_ttl_arms_fallback_before_close(self, monkeypatch):
        """The hard-exit fallback is armed even if graceful close raises."""
        timers = []
        exit_codes = []

        class FakeTimer:
            def __init__(self, interval, function):
                self.interval = interval
                self.function = function
                self.daemon = False
                self.started = False
                timers.append(self)

            def start(self):
                self.started = True

        monkeypatch.setattr(web_app.threading, "Timer", FakeTimer)

        def failing_close():
            raise RuntimeError("close failed")

        web_app._schedule_server_ttl(
            30,
            close_fn=failing_close,
            exit_fn=exit_codes.append,
            hard_exit_grace_seconds=5,
        )

        with pytest.raises(RuntimeError, match="close failed"):
            timers[0].function()

        assert len(timers) == 2
        assert timers[1].interval == 5
        assert timers[1].daemon is True
        assert timers[1].started is True

        timers[1].function()
        assert exit_codes == [0]

    def test_launch_dashboard_with_ttl_closes_and_blocks(self, monkeypatch):
        """TTL launch closes Gradio gracefully instead of hard-exiting."""
        launch_calls = []
        close_calls = []
        block_calls = []

        class FakeDemo:
            def launch(self, **kwargs):
                launch_calls.append(kwargs)

            def close(self, *, verbose=True):
                close_calls.append(verbose)

            def block_thread(self):
                block_calls.append(True)

        fake_demo = FakeDemo()
        monkeypatch.setattr(web_app, "demo", fake_demo)

        timers = []

        class FakeTimer:
            def __init__(self, interval, function):
                self.interval = interval
                self.function = function
                self.daemon = False
                timers.append(self)

            def start(self):
                self.function()

        monkeypatch.setattr(web_app.threading, "Timer", FakeTimer)

        web_app._launch_dashboard(
            server_name="127.0.0.1",
            server_port=7862,
            ttl_seconds=5,
            exit_fn=lambda code: None,
        )

        assert launch_calls == [
            {
                "server_name": "127.0.0.1",
                "server_port": 7862,
                "prevent_thread_lock": True,
            }
        ]
        assert timers[0].daemon is True
        assert close_calls == [False]
        assert block_calls == [True]

    def test_main_reads_ttl_from_env(self, monkeypatch):
        """The module entrypoint passes env-configured TTL to launch."""
        calls = []

        monkeypatch.setenv("BASEBALL_RAG_WEB_APP_TTL_SECONDS", "90")
        monkeypatch.setattr(web_app, "_launch_dashboard", lambda **kwargs: calls.append(kwargs))

        web_app.main([])

        assert calls == [
            {
                "server_name": "0.0.0.0",
                "server_port": 7860,
                "ttl_seconds": 90.0,
            }
        ]

    def test_main_cli_ttl_overrides_env(self, monkeypatch):
        """The CLI TTL flag wins over the environment variable."""
        calls = []

        monkeypatch.setenv("BASEBALL_RAG_WEB_APP_TTL_SECONDS", "90")
        monkeypatch.setattr(web_app, "_launch_dashboard", lambda **kwargs: calls.append(kwargs))

        web_app.main(["--ttl-seconds", "0"])

        assert calls[0]["ttl_seconds"] is None

    def test_dev_main_uses_short_local_defaults(self, monkeypatch):
        """The short UI command starts local server defaults and waits for user exit."""
        calls = []

        monkeypatch.setattr(web_app, "_launch_dashboard", lambda **kwargs: calls.append(kwargs))

        web_app.dev_main([])

        assert calls == [
            {
                "server_name": "127.0.0.1",
                "server_port": 7861,
                "ttl_seconds": None,
            }
        ]

    def test_dev_main_env_ttl_overrides_short_default(self, monkeypatch):
        """The short UI command still honors env-configured TTL values."""
        calls = []

        monkeypatch.setenv("BASEBALL_RAG_WEB_APP_TTL_SECONDS", "300")
        monkeypatch.setattr(web_app, "_launch_dashboard", lambda **kwargs: calls.append(kwargs))

        web_app.dev_main([])

        assert calls[0]["ttl_seconds"] == 300.0

    def test_project_exposes_short_ui_script(self):
        """pyproject exposes a memorable command for local browser QA."""
        import tomllib
        from pathlib import Path

        pyproject = tomllib.loads(Path("pyproject.toml").read_text())

        assert pyproject["project"]["scripts"]["baseball-rag-ui"] == (
            "baseball_rag.web_app:dev_main"
        )

    def test_main_rejects_invalid_env_ttl_before_launch(self, monkeypatch):
        """Invalid environment TTL values fail before launching Gradio."""
        calls = []

        monkeypatch.setenv("BASEBALL_RAG_WEB_APP_TTL_SECONDS", "inf")
        monkeypatch.setattr(web_app, "_launch_dashboard", lambda **kwargs: calls.append(kwargs))

        with pytest.raises(SystemExit):
            web_app.main([])

        assert calls == []

    def test_main_rejects_invalid_cli_ttl_before_launch(self, monkeypatch):
        """Invalid CLI TTL values fail before launching Gradio."""
        calls = []

        monkeypatch.setattr(web_app, "_launch_dashboard", lambda **kwargs: calls.append(kwargs))

        with pytest.raises(SystemExit):
            web_app.main(["--ttl-seconds", "nan"])

        assert calls == []
