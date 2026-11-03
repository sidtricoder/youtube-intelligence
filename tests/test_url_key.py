"""URL credentials never grant account access; OAuth bearer tokens select account tools."""

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

from tests.fakes import FixtureProvider
from tests.test_api import account
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
        **overrides,
    )


def make_app(tmp_path, **overrides):
    return create_app(make_settings(tmp_path, **overrides), provider=FixtureProvider())


@asynccontextmanager
async def running(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
        ) as client:
            yield client


def test_shared_url_key_configuration_is_removed(tmp_path):
    settings = make_settings(tmp_path)
    assert "mcp_url_key" not in type(settings).model_fields
    assert "api_key" not in type(settings).model_fields
    assert "owner_key" not in type(settings).model_fields


@pytest.mark.parametrize("supplied", ["", "short", URL_KEY, "a" * 32, "o" * 32])
async def test_query_key_never_authenticates_protected_rest(tmp_path, supplied):
    async with running(make_app(tmp_path)) as client:
        response = await client.get("/api/quota", params={"key": supplied})
        assert response.status_code == 401
        assert "WWW-Authenticate" in response.headers


async def test_legacy_owner_routes_are_absent(tmp_path):
    async with running(make_app(tmp_path)) as client:
        for path in ("/owner/disconnect", "/owner/oauth/start", "/owner/drafts/example/approve"):
            assert (await client.post(path, params={"key": URL_KEY})).status_code == 404


async def test_query_key_cannot_override_invalid_bearer(tmp_path):
    async with running(make_app(tmp_path)) as client:
        response = await client.post(
            "/mcp/",
            params={"key": URL_KEY},
            json=INIT,
            headers={**MCP_HEADERS, "Authorization": "Bearer invalid"},
        )
        assert response.status_code == 401


async def test_oauth_bearer_authenticates_account_rest(tmp_path):
    app = make_app(tmp_path)
    _, headers, _, _ = account(app)
    async with running(app) as client:
        assert (await client.get("/api/quota", headers=headers)).status_code == 200


async def test_queries_cannot_override_oauth_account_binding(tmp_path):
    app = make_app(tmp_path)
    alice, alice_headers, _, _ = account(app)
    bob, bob_headers, _, _ = account(app, "google-bob")
    assert alice != bob
    async with running(app) as client:
        response = await client.post(
            "/api/drafts",
            headers=alice_headers,
            json={"topic": "Python", "total_seconds": 1800, "max_seconds": 900},
        )
        draft = response.json()
        response = await client.get(
            "/api/drafts/" + draft["id"],
            headers=bob_headers,
            params={"user_id": alice, "key": URL_KEY},
        )
        assert response.status_code == 404


async def test_oauth_discovery_is_public_and_current(tmp_path):
    app = make_app(tmp_path)
    async with running(app) as client:
        for path in (
            "/.well-known/oauth-protected-resource",
            "/.well-known/oauth-authorization-server",
        ):
            response = await client.get(path)
            assert response.status_code == 200
            assert "application/json" in response.headers["content-type"]
        assert (await client.get("/.well-known/openid-configuration")).status_code == 404


@pytest.fixture
def server(tmp_path):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    app = make_app(tmp_path, local_base_url=origin)
    _, headers, _, _ = account(app)
    srv = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Test server failed to start")
        time.sleep(0.01)
    yield origin, headers
    srv.should_exit = True
    thread.join(timeout=10)
    sock.close()


@pytest.mark.parametrize("path", ["/mcp/", "/mcp"])
async def test_official_mcp_client_query_key_stays_public(server, path):
    origin, _ = server
    async with (
        httpx.AsyncClient(trust_env=False, follow_redirects=True) as http_client,
        streamable_http_client(f"{origin}{path}?key={URL_KEY}", http_client=http_client) as (
            read,
            write,
            _,
        ),
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert "similar_videos" in tools
            assert {"create_playlist_draft", "playlist_status"} <= tools
            description = next(
                tool.description
                for tool in (await session.list_tools()).tools
                if tool.name == "create_playlist_draft"
            )
            assert "sign" in description.lower()
            response = await session.call_tool("similar_videos", {"video": "aaaaaaaaaaa"})
            assert not response.isError
            async with httpx.AsyncClient(trust_env=False) as direct:
                response = await direct.post(
                    origin + "/mcp/",
                    headers=MCP_HEADERS,
                    params={"key": URL_KEY},
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "playlist_status", "arguments": {"draft_id": "guessed"}},
                    },
                )
                assert response.status_code == 401


async def test_official_mcp_client_oauth_bearer_lists_account_tools(server):
    origin, headers = server
    async with (
        httpx.AsyncClient(trust_env=False, headers=headers, follow_redirects=True) as http_client,
        streamable_http_client(origin + "/mcp/", http_client=http_client) as (read, write, _),
    ):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = {tool.name for tool in (await session.list_tools()).tools}
            assert {"similar_videos", "propose_playlist", "playlist_status"} <= tools
            assert not any("approve" in name for name in tools)
            assert "create_playlist_draft" in tools
