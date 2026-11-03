"""URL-key access to /mcp for clients (e.g. Claude custom connectors) that cannot send headers.

The URL key is a dedicated credential: it opens /mcp only, never /api or /owner, and is
disabled unless YT_MCP_URL_KEY is configured.
"""

import json
import socket
import threading
import time
from contextlib import asynccontextmanager

import httpx
import pytest
import uvicorn
from cryptography.fernet import Fernet
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import ValidationError

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings

URL_KEY = "u" * 40
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def make_settings(tmp_path, **overrides):
    return Settings(
        _env_file=None,
        db_path=str(tmp_path / "k.db"),
        encryption_key=Fernet.generate_key().decode(),
        api_key="a" * 32,
        owner_key="o" * 32,
        **overrides,
    )


def make_app(tmp_path, **overrides):
    app = create_app(make_settings(tmp_path, **overrides), provider=FixtureProvider())
    app.state.service.store.put("oauth:tokens", {"write": True})
    return app


@asynccontextmanager
async def running(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
        ) as client:
            yield client


async def post(app, path, **kwargs):
    async with running(app) as client:
        return await client.post(path, headers=MCP_HEADERS, json=INIT, **kwargs)


async def get(app, path, **kwargs):
    async with running(app) as client:
        return await client.get(path, **kwargs)


# ---- configuration -------------------------------------------------------------------


def test_url_key_is_optional_and_disabled_by_default(tmp_path):
    assert make_settings(tmp_path).mcp_url_key == ""


@pytest.mark.parametrize("bad", ["short", "a" * 32, "o" * 32])
def test_url_key_must_be_long_and_distinct_from_other_keys(tmp_path, bad):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, mcp_url_key=bad)


def test_url_key_must_be_url_safe(tmp_path):
    with pytest.raises(ValidationError):
        make_settings(tmp_path, mcp_url_key="x" * 31 + "&")


# ---- access rules --------------------------------------------------------------------


async def test_valid_url_key_opens_mcp_without_any_header(tmp_path):
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    r = await post(app, "/mcp/", params={"key": URL_KEY})
    assert r.status_code == 200 and "result" in r.json()


async def test_wrong_url_key_is_rejected(tmp_path):
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    assert (await post(app, "/mcp/", params={"key": "w" * 40})).status_code == 401


async def test_missing_url_key_is_rejected(tmp_path):
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    assert (await post(app, "/mcp/")).status_code == 401


@pytest.mark.parametrize("supplied", ["", "anything"])
async def test_disabled_url_key_never_matches_empty_or_any_value(tmp_path, supplied):
    app = make_app(tmp_path)  # YT_MCP_URL_KEY unset => feature off
    assert (await post(app, "/mcp/", params={"key": supplied})).status_code == 401


async def test_api_and_owner_keys_do_not_work_in_the_url(tmp_path):
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    async with running(app) as client:
        for wrong in ("a" * 32, "o" * 32):
            r = await client.post("/mcp/", headers=MCP_HEADERS, json=INIT, params={"key": wrong})
            assert r.status_code == 401


async def test_url_key_does_not_open_rest_or_owner_routes(tmp_path):
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    async with running(app) as client:
        assert (await client.get("/api/quota", params={"key": URL_KEY})).status_code == 401
        r = await client.post("/owner/disconnect", params={"key": URL_KEY}, json={})
        assert r.status_code == 401


async def test_header_authentication_still_works(tmp_path):
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    async with running(app) as client:
        r = await client.post(
            "/mcp/", headers={**MCP_HEADERS, "Authorization": "Bearer " + "a" * 32}, json=INIT
        )
    assert r.status_code == 200


async def test_url_key_requests_share_the_ai_rate_limit(tmp_path):
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    codes = []
    async with running(app) as client:
        for _ in range(61):
            r = await client.post("/mcp/", headers=MCP_HEADERS, json=INIT, params={"key": URL_KEY})
            codes.append(r.status_code)
    assert codes[-1] == 429 and codes[0] == 200


async def test_oauth_discovery_paths_answer_404_not_401(tmp_path):
    # A 401 on discovery makes OAuth-capable clients believe this server demands OAuth.
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    async with running(app) as client:
        for path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
            "/.well-known/openid-configuration",
        ):
            assert (await client.get(path)).status_code == 404


# ---- real wire test: official MCP client, URL only, no headers -----------------------


@pytest.fixture
def server(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = make_app(tmp_path, mcp_url_key=URL_KEY)
    srv = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Test server failed to start")
        time.sleep(0.01)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(timeout=10)
    sock.close()


@pytest.mark.parametrize("path", ["/mcp/", "/mcp"])
async def test_official_mcp_client_connects_with_url_key_only(server, path):
    url = f"{server}{path}?key={URL_KEY}"
    async with (
        httpx.AsyncClient(trust_env=False, follow_redirects=True) as http_client,
        streamable_http_client(url, http_client=http_client) as (read, write, _),
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            assert {"similar_videos", "propose_playlist", "playlist_status"} <= tools
            assert not any("approve" in t or "create" in t for t in tools)
            result = await session.call_tool("similar_videos", {"video": "aaaaaaaaaaa"})
            assert not result.isError
            assert json.loads(result.content[0].text)["results"]


async def test_official_mcp_client_without_key_is_refused(server):
    async with httpx.AsyncClient(trust_env=False) as http_client:
        r = await http_client.post(f"{server}/mcp/", headers=MCP_HEADERS, json=INIT)
    assert r.status_code == 401
