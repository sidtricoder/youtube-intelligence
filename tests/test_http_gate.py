import json

import httpx
import pytest

from ytintel.http_gate import MCPGate, client_address
from ytintel.policy import Tier, tool_tier


class Token:
    expires_at = None
    client_id = "fixture"
    resource = "https://example.test/mcp/"
    user_id = "alice"
    scopes = ["youtube:read"]


class Auth:
    async def load_access_token(self, token):
        return Token() if token == "valid" else None


@pytest.fixture
async def gate():
    seen = []

    async def downstream(scope, receive, send):
        seen.append(scope["state"]["user_context"])
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    async def context(user, ip):
        return user.user_id if user else "anonymous:" + ip

    app = MCPGate(downstream, Auth(), "https://example.test", context, rate_limit=5)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="https://example.test"
    ) as c:
        yield c, seen


async def test_public_allowed_protected_challenged_before_execution(gate):
    client, seen = gate
    public = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "similar_videos"},
    }
    assert (await client.post("/mcp/", json=public)).status_code == 200
    protected = {**public, "params": {"name": "recommendations"}}
    r = await client.post("/mcp/", json=protected)
    assert r.status_code == 401
    assert (
        r.headers["www-authenticate"]
        == 'Bearer resource_metadata="https://example.test/.well-known/oauth-protected-resource", scope="youtube:read"'
    )
    assert len(seen) == 1
    assert (
        await client.post("/mcp/", json=protected, headers={"Authorization": "Bearer valid"})
    ).status_code == 200


async def test_invalid_token_denied_on_public_and_cookie_not_token(gate):
    c, seen = gate
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    assert (
        await c.post("/mcp/", json=body, headers={"Authorization": "Bearer bad"})
    ).status_code == 401
    assert not seen
    c.cookies.set("yt_session", "valid")
    body.update(method="tools/call", params={"name": "playlist_status"})
    assert (await c.post("/mcp/", json=body)).status_code == 401


async def test_mixed_batch_challenges_whole_batch_before_execution(gate):
    c, seen = gate
    payload = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": n}}
        for n in ("similar_videos", "playlist_status")
    ]
    assert (await c.post("/mcp/", json=payload)).status_code == 401
    assert not seen


@pytest.mark.parametrize("payload", [[], {}, {"jsonrpc": "1.0", "method": "ping"}, "broken", [1]])
async def test_malformed_jsonrpc_clean_failure(gate, payload):
    c, seen = gate
    assert (await c.post("/mcp/", content=json.dumps(payload))).status_code == 400
    assert not seen


def test_unknown_defaults_protected_and_untrusted_forwarded_ip_ignored():
    assert tool_tier("future_tool") == Tier.AUTHENTICATED
    scope = {"client": ("192.0.2.1", 123), "headers": [(b"x-forwarded-for", b"198.51.100.42")]}
    assert client_address(scope, ()) == "192.0.2.1"
    assert client_address(scope, ("192.0.2.0/24",)) == "198.51.100.42"


async def test_batch_searches_dispatch_without_application_cap(gate):
    client, seen = gate
    payload = [
        {"jsonrpc": "2.0", "id": n, "method": "tools/call", "params": {"name": "similar_videos"}}
        for n in range(4)
    ]
    response = await client.post("/mcp/", json=payload)
    assert response.status_code == 200
    assert len(seen) == 4


async def test_bearer_scheme_is_case_insensitive_using_sdk_verifier(gate):
    client, _ = gate
    response = await client.post(
        "/mcp/",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "recommendations"},
        },
        headers={"Authorization": "bearer valid"},
    )
    assert response.status_code == 200
