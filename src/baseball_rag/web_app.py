"""Launcher for the unified FastAPI and Svelte Ground Ball application."""

from __future__ import annotations

import argparse
import math
import os
import threading

import uvicorn

_TTL_ENV_VAR = "GROUNDBALL_WEB_APP_TTL_SECONDS"
_LEGACY_TTL_ENV_VAR = "BASEBALL_RAG_WEB_APP_TTL_SECONDS"
_DEFAULT_SERVER_NAME = "0.0.0.0"
_DEFAULT_SERVER_PORT = 7860
_DEV_SERVER_NAME = "127.0.0.1"
_DEV_SERVER_PORT = 7861


def _parse_ttl_seconds(raw: str | None) -> float | None:
    """Parse an optional process lifetime; empty or zero means no deadline."""
    if raw is None or raw.strip() == "":
        return None
    try:
        ttl_seconds = float(raw)
    except ValueError as exc:
        raise ValueError("server TTL must be a number of seconds") from exc
    if not math.isfinite(ttl_seconds):
        raise ValueError("server TTL must be finite")
    if ttl_seconds < 0:
        raise ValueError("server TTL must be non-negative")
    return ttl_seconds or None


def _configured_ttl(default_ttl_seconds: str | None) -> str | None:
    return os.environ.get(
        _TTL_ENV_VAR,
        os.environ.get(_LEGACY_TTL_ENV_VAR, default_ttl_seconds),
    )


def _launch_app(
    *,
    server_name: str,
    server_port: int,
    ttl_seconds: float | None,
) -> None:
    """Run the same-origin FastAPI API and built Svelte application."""
    config = uvicorn.Config(
        "baseball_rag.api.server:app",
        host=server_name,
        port=server_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    timer: threading.Timer | None = None
    if ttl_seconds is not None:
        timer = threading.Timer(ttl_seconds, lambda: setattr(server, "should_exit", True))
        timer.daemon = True
        timer.start()
    try:
        server.run()
    finally:
        if timer is not None:
            timer.cancel()


def _main_with_defaults(
    argv: list[str] | None,
    *,
    default_server_name: str,
    default_server_port: int,
    default_ttl_seconds: str | None,
) -> None:
    parser = argparse.ArgumentParser(description="Launch the Ground Ball web application.")
    parser.add_argument("--server-name", default=default_server_name)
    parser.add_argument("--server-port", default=default_server_port, type=int)
    parser.add_argument(
        "--ttl-seconds",
        default=None,
        help=(
            "Optional process time to live in seconds. "
            f"May also be set with {_TTL_ENV_VAR}; {_LEGACY_TTL_ENV_VAR} remains an alias."
        ),
    )
    args = parser.parse_args(argv)
    raw_ttl = (
        args.ttl_seconds if args.ttl_seconds is not None else _configured_ttl(default_ttl_seconds)
    )
    try:
        ttl_seconds = _parse_ttl_seconds(raw_ttl)
    except ValueError as exc:
        parser.error(str(exc))
    _launch_app(
        server_name=args.server_name,
        server_port=args.server_port,
        ttl_seconds=ttl_seconds,
    )


def main(argv: list[str] | None = None) -> None:
    _main_with_defaults(
        argv,
        default_server_name=_DEFAULT_SERVER_NAME,
        default_server_port=_DEFAULT_SERVER_PORT,
        default_ttl_seconds=None,
    )


def dev_main(argv: list[str] | None = None) -> None:
    _main_with_defaults(
        argv,
        default_server_name=_DEV_SERVER_NAME,
        default_server_port=_DEV_SERVER_PORT,
        default_ttl_seconds=None,
    )


if __name__ == "__main__":
    main()
