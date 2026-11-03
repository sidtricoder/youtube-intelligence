"""Offline real-TCP fixtures: only upstream identity and YouTube are synthetic."""

import base64
import hashlib
import json
import re
import secrets
import socket
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
import uvicorn
from cryptography.fernet import Fernet
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from sqlalchemy import select

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.context import UserContext
from ytintel.identity import READ_SCOPE, WRITE_SCOPE, GoogleIdentity
from ytintel.quota import active_ticket


class FakeIdentity:
    def __init__(self):
        self.pending = {}
        self.exchanges = []

    def authorization_url(self, state, nonce, verifier, write=False):
        self.pending[state] = (nonce, verifier, write)
        return "https://fake-google.invalid/auth?" + urlencode({"state": state})

    async def exchange(self, code, verifier, nonce):
        state = next(s for s, p in self.pending.items() if p[:2] == (nonce, verifier))
        _, _, write = self.pending.pop(state)
        assert code in ("alice", "bob")
        self.exchanges.append((code, write))
        return GoogleIdentity(
            code,
            {
                "access_token": "google-" + code,
                "refresh_token": "refresh-" + code,
                "scope": READ_SCOPE + (" " + WRITE_SCOPE if write else ""),
                "expires_at": time.time() + 3600,
            },
        )

    async def refresh(self, refresh_token):
        raise AssertionError("Unexpected upstream refresh")

    async def revoke(self, refresh_token):
        pass


class AccountProvider(FixtureProvider):
    def __init__(self, label):
        super().__init__()
        self.label, self.calls = label, []
        self.items = [v.model_copy(update={"title": label + " " + v.title}) for v in self.items]

    def charge(self, operation, units=1, searches=0):
        self.calls.append(operation)
        ticket = active_ticket.get()
        if ticket is not None:
            ticket.consume(units, searches)

    async def videos(self, ids):
        self.charge("videos")
        return await super().videos(ids)

    async def search(self, query, language=None):
        self.charge("search", 1, 1)
        return await super().search(query, language)

    async def channel(self, ref):
        self.charge("channel")
        return await super().channel(ref)

    async def search_channels(self, query):
        self.charge("search_channels", 1, 1)
        return await super().search_channels(query)

    async def profile(self):
        self.charge("profile")
        result = await super().profile()
        result["subscriptions"][0]["title"] = self.label + " subscription"
        return result

    async def create_playlist(self, title):
        self.charge("create_playlist", 50)
        return await super().create_playlist(title)

    async def add_video(self, playlist_id, video_id):
        self.charge("add_video", 50)
        return await super().add_video(playlist_id, video_id)


@contextmanager
def running_server(tmp_path, **overrides):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    origin = "http://127.0.0.1:" + str(sock.getsockname()[1])
    settings = dict(
        _env_file=None,
        db_path=str(tmp_path / ("wire-" + secrets.token_hex(4) + ".db")),
        encryption_key=Fernet.generate_key().decode(),
        local_base_url=origin,
        redirect_uri=origin + "/oauth/callback",
        database_url=None,
        database_url_pooled=None,
        render_external_url="",
        public_base_url="",
        searches_per_day=1000,
        user_units_per_day=5000,
        anonymous_units_per_day=3000,
        anonymous_rate_limit=300,
    )
    settings.update(overrides)
    idp, providers = FakeIdentity(), {}

    def factory(ctx, store, client):
        label = "public"
        if isinstance(ctx, UserContext):
            with store.raw.tx() as db:
                label = db.execute(
                    select(app.state.security.users.c.google_sub).where(
                        app.state.security.users.c.user_id == ctx.user_id
                    )
                ).scalar_one()
        return providers.setdefault(label, AccountProvider(label))

    app = create_app(Settings(**settings), identity_provider=idp, provider_factory=factory)
    srv = uvicorn.Server(
        uvicorn.Config(app, log_level="error", access_log=False, proxy_headers=False)
    )
    thread = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not srv.started:
        if time.monotonic() > deadline:
            raise RuntimeError("Server failed to start")
        time.sleep(0.01)
    try:
        yield Wire(origin, app, idp, providers)
    finally:
        srv.should_exit = True
        thread.join(10)
        sock.close()
        assert not thread.is_alive()


@dataclass
class Wire:
    origin: str
    app: object
    idp: object
    providers: dict

    @property
    def challenge(self):
        return f'Bearer resource_metadata="{self.origin}/.well-known/oauth-protected-resource", scope="youtube:read"'


@asynccontextmanager
async def mcp_session(wire, token=None):
    headers = {"Authorization": "Bearer " + token} if token else {}
    async with httpx.AsyncClient(headers=headers, trust_env=False) as http:
        async with streamable_http_client(wire.origin + "/mcp/", http_client=http) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


async def call(session, name, arguments=None):
    result = await session.call_tool(name, arguments or {})
    assert not result.isError, result
    return json.loads(result.content[0].text)


def csrf(response):
    assert response.status_code == 200, response.text
    return re.search(r'name="csrf" value="([^"]+)"', response.text)[1]


def query(url):
    return {k: v[-1] for k, v in parse_qs(urlsplit(url).query).items()}


async def upstream(browser, location, sub):
    started = await browser.get(location)
    assert started.status_code == 302
    state = query(started.headers["location"])["state"]
    callback = await browser.get("/oauth/callback", params={"state": state, "code": sub})
    assert callback.status_code == 302, callback.text
    return callback.headers["location"]


async def login(wire, browser, sub):
    registration = await browser.post(
        "/register",
        json={
            "client_name": "Offline official MCP client " + sub,
            "redirect_uris": ["http://127.0.0.1:9876/client-callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "scope": "youtube:read",
        },
    )
    assert registration.status_code == 201, registration.text
    client_id = registration.json()["client_id"]
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    authorize = await browser.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "http://127.0.0.1:9876/client-callback",
            "response_type": "code",
            "scope": "youtube:read",
            "state": "client-state-" + sub,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": wire.origin + "/mcp/",
        },
    )
    assert authorize.status_code == 302, authorize.text
    consent_url = await upstream(browser, authorize.headers["location"], sub)
    page = await browser.get(consent_url)
    transaction = query(consent_url)["transaction"]
    callback = await browser.post(
        "/oauth/consent", data={"csrf": csrf(page), "transaction": transaction}
    )
    assert callback.status_code == 302, callback.text
    values = query(callback.headers["location"])
    assert values["state"] == "client-state-" + sub
    token = await browser.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": values["code"],
            "redirect_uri": "http://127.0.0.1:9876/client-callback",
            "code_verifier": verifier,
            "resource": wire.origin + "/mcp/",
        },
    )
    assert token.status_code == 200, token.text
    replay = await browser.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": values["code"],
            "redirect_uri": "http://127.0.0.1:9876/client-callback",
            "code_verifier": verifier,
            "resource": wire.origin + "/mcp/",
        },
    )
    assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
    return {**token.json(), "client_id": client_id}


async def rpc(wire, message, token=None, headers=None):
    request_headers = {"Accept": "application/json, text/event-stream", **(headers or {})}
    if token:
        request_headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(trust_env=False) as c:
        return await c.post(wire.origin + "/mcp/", json=message, headers=request_headers)


def tool(name, arguments=None, ident=1):
    return {
        "jsonrpc": "2.0",
        "id": ident,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}},
    }
