"""MCP startup and callable tools refuse unsafe work before upstream calls."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from test_mlb_api import get_tool, patch_mcp_tool

import main
import mlb_api


@pytest.fixture
def tools():
    server = MagicMock()
    patch_mcp_tool(server)
    mlb_api.setup_mlb_tools(server)
    return server


@pytest.mark.parametrize(
    "name,source",
    [
        ("get_statcast_pitcher", "statcast_pitcher"),
        ("get_statcast_batter", "statcast_batter"),
        ("get_statcast_team", "statcast"),
    ],
)
def test_statcast_refuses_long_dates_before_upstream(tools, name, source):
    params = {"player_id": 123} if name != "get_statcast_team" else {"team": "Yankees", "fields": []}
    with patch(f"mlb_api.{source}") as upstream, patch("mlb_api.get_team_abbreviation_from_name", return_value="NYY"):
        result = get_tool(tools, name)(start_date="2022-01-01", end_date="2023-01-01", **params)
    assert "error" in result
    upstream.assert_not_called()


def test_mcp_http_startup_refuses_non_loopback():
    with patch("main.uvicorn.run") as run:
        with pytest.raises(SystemExit):
            main.main(["--http", "--host", "0.0.0.0"])
    run.assert_not_called()


def test_mcp_http_defaults_to_loopback():
    with patch("main.uvicorn.run") as run:
        main.main(["--http"])
    assert run.call_args.kwargs["host"] == "127.0.0.1"


def test_statcast_refuses_oversized_frame_before_conversion(tools):
    data = pd.DataFrame({"pitcher": range(20_001)})
    with patch("mlb_api.statcast_pitcher", return_value=data), patch.object(data, "astype") as convert:
        result = get_tool(tools, "get_statcast_pitcher")(123, "2022-04-01", "2022-04-07")
    assert "error" in result
    convert.assert_not_called()


def test_statcast_concurrency_refuses_extra_upstream_work(tools):
    entered = Event()
    release = Event()

    def fetch(*_):
        entered.set()
        assert release.wait(5)
        return pd.DataFrame({"pitcher": [123]})

    call = get_tool(tools, "get_statcast_pitcher")
    with patch("mlb_api.statcast_pitcher", side_effect=fetch) as upstream, ThreadPoolExecutor(2) as executor:
        first = executor.submit(call, 123, "2022-04-01", "2022-04-07")
        assert entered.wait(5)
        try:
            second = executor.submit(call, 123, "2022-04-01", "2022-04-07").result(timeout=2)
        finally:
            release.set()
        assert "statcast_data" in first.result(timeout=2)
    assert "error" in second
    assert upstream.call_count == 1


def test_mcp_http_rejects_oversized_body_before_transport_decode():
    import asyncio

    with patch("main.uvicorn.run") as run:
        main.main(["--http"])
    app = run.call_args.args[0]
    consumed = []
    sent = []

    async def receive():
        consumed.append(True)
        if len(consumed) > 1:
            raise AssertionError("must stop receiving after the budget is exceeded")
        return {"type": "http.request", "body": b"x" * 65_537, "more_body": True}

    async def send(message):
        sent.append(message)

    asyncio.run(
        app(
            {"type": "http", "method": "POST", "path": "/mcp", "headers": [(b"host", b"127.0.0.1:8002")]}, receive, send
        )
    )
    assert sent[0]["status"] == 413
    assert len(consumed) == 1


@pytest.mark.parametrize("name", ["get_multiple_mlb_player_stats", "get_mlb_sabermetrics"])
def test_mcp_player_fanout_refused_before_upstream(tools, name):
    with patch("mlb_api.get_multiple_player_stats") as multiple, patch("mlb_api.get_sabermetrics_for_players") as saber:
        params = {"player_ids": ",".join(str(i) for i in range(41)), "season": 2025}
        if name == "get_multiple_mlb_player_stats":
            params.update(group="hitting", type="season")
        result = get_tool(tools, name)(**params)
    assert "error" in result
    multiple.assert_not_called()
    saber.assert_not_called()


def test_mcp_tool_rate_budget_refuses_the_next_upstream_call(tools):
    with patch("mlb_api.mlb.get_people_id", return_value=[123]) as upstream:
        results = [get_tool(tools, "get_mlb_search_players")("Name") for _ in range(61)]
    assert results[59] == {"player_ids": [123]}
    assert "error" in results[60]
    assert upstream.call_count == 60


def test_statcast_response_byte_budget_refuses_large_cell(tools):
    data = pd.DataFrame({"pitcher": ["x" * (1_024 * 1_024)]})
    with patch("mlb_api.statcast_pitcher", return_value=data):
        result = get_tool(tools, "get_statcast_pitcher")(123, "2022-04-01", "2022-04-07")
    assert "error" in result and "byte budget" in result["error"]


@pytest.mark.parametrize(
    "host,origin,status",
    [
        ("127.0.0.1:8002", None, 200),
        ("[::1]:8002", None, 200),
        ("localhost:8002", "http://localhost:8002", 200),
        ("attacker.example:8002", None, 403),
        ("attacker.example:8002", "http://" + "attacker.example:8002", 403),
        ("127.0.0.1:8002", "http://" + "attacker.example:8002", 403),
        ("127.0.0.1:8002", "null", 403),
    ],
)
def test_real_mcp_http_initialize_restricts_host_and_origin(host, origin, status):
    from starlette.testclient import TestClient

    with patch("main.uvicorn.run") as run:
        main.main(["--http"])
    app = run.call_args.args[0]
    headers = {"Host": host, "Accept": "application/json, text/event-stream"}
    if origin is not None:
        headers["Origin"] = origin
    with TestClient(app, base_url="http://127.0.0.1:8002", follow_redirects=False) as client:
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "security-test", "version": "1"},
                },
            },
        )
    assert response.status_code == status
    if status == 200:
        assert "protocolVersion" in response.text
