"""System tests use real TCP + Streamable HTTP + official MCP client, never direct tool calls."""

import json
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from cryptography.fernet import Fernet
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings


@pytest.fixture
def server(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = Settings(
        _env_file=None,
        db_path=str(tmp_path / "wire.db"),
        encryption_key=Fernet.generate_key().decode(),
        api_key="a" * 32,
        owner_key="o" * 32,
    )
    app = create_app(config, provider=FixtureProvider())
    app.state.service.store.put("oauth:tokens", {"write": True})
    srv = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Test server failed to start")
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}", app
    srv.should_exit = True
    thread.join(timeout=10)
    sock.close()


async def call(session, name, arguments):
    result = await session.call_tool(name, arguments)
    assert not result.isError, result
    return json.loads(result.content[0].text)


async def test_fr1_to_fr5_through_mcp_with_owner_confirmation(server):
    url, app = server
    async with (
        httpx.AsyncClient(
            headers={"Authorization": "Bearer " + "a" * 32}, trust_env=False
        ) as http_client,
        streamable_http_client(url + "/mcp/", http_client=http_client) as (read, write, _),
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            assert not any("approve" in x or "create" in x or "resume" in x for x in tools)
            assert (await call(session, "similar_videos", {"video": "aaaaaaaaaaa"}))["results"]
            assert (await call(session, "similar_channels", {"channel": "@pythonlab"}))["results"]
            assert (await call(session, "recommendations", {}))["recommendations"]
            assert (await call(session, "engagement_analysis", {}))["sample_count"] > 0
            d = await call(
                session,
                "propose_playlist",
                {"topic": "Python", "total_seconds": 1800, "max_seconds": 900, "language": "en"},
            )
            assert d["status"] == "pending" and app.state.service.provider.created == []
            async with httpx.AsyncClient(trust_env=False) as client:
                result = await client.post(
                    url + "/owner/drafts/" + d["id"] + "/approve",
                    headers={"Authorization": "Bearer " + "o" * 32},
                    json={"confirmation": "CREATE"},
                )
            assert result.status_code == 200 and result.json()["status"] == "complete"
            assert (await call(session, "playlist_status", {"draft_id": d["id"]}))[
                "status"
            ] == "complete"
            assert (await session.read_resource("ytintel://quota")).contents
            assert (await session.list_resources()).resources
            assert (await session.list_prompts()).prompts


async def test_workflow_and_negative_errors_over_mcp(server):
    url, app = server
    async with (
        httpx.AsyncClient(
            headers={"Authorization": "Bearer " + "a" * 32}, trust_env=False
        ) as http_client,
        streamable_http_client(url + "/mcp/", http_client=http_client) as (read, write, _),
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bad = await call(
                session, "similar_videos", {"video": "https://evil.test/?v=aaaaaaaaaaa"}
            )
            assert bad["error"]["code"] == "invalid_input"
            missing = await call(session, "similar_videos", {"video": "zzzzzzzzzzz"})
            assert missing["error"]["code"] == "not_found"
            result = await call(
                session,
                "video_to_playlist",
                {
                    "video": "aaaaaaaaaaa",
                    "topic": "Python",
                    "total_seconds": 1800,
                    "max_seconds": 900,
                },
            )
            assert result["summary"]["basis"] == "metadata_only"
            assert result["draft"]["status"] == "pending"
            assert app.state.service.provider.created == []
            natural = await call(
                session,
                "playlist_from_request",
                {
                    "request": "Build a 2 hour playlist on Python, no video over 20 minutes, language en"
                },
            )
            assert natural["constraints"]["total_seconds"] == 7200
            assert (
                await call(
                    session,
                    "propose_playlist",
                    {"topic": "Python", "total_seconds": -1, "max_seconds": 100},
                )
            )["error"]["code"] == "invalid_input"
