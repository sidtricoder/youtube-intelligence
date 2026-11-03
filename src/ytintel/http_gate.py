"""ASGI preflight: real HTTP challenges before MCP dispatch, including mixed batches."""

import ipaddress
import json
import time
from collections import defaultdict, deque

from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend
from mcp.server.auth.provider import ProviderTokenVerifier
from pydantic import AnyHttpUrl
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse, Response

from .errors import AppError
from .policy import MCP_SCOPE, Tier, required_tier


def client_address(scope: dict, trusted_proxies: tuple[str, ...]) -> str:
    peer = (scope.get("client") or ("unknown", 0))[0]
    networks = [ipaddress.ip_network(item, strict=False) for item in trusted_proxies]

    def trusted(address):
        try:
            ip = ipaddress.ip_address(address)
            return any(ip in network for network in networks)
        except ValueError:
            return False

    if not trusted(peer):
        return peer
    value = dict(scope.get("headers", [])).get(b"x-forwarded-for", b"").decode("latin1")
    if len(value) > 2048:
        return peer
    chain = [x.strip() for x in value.split(",") if x.strip()] + [peer]
    for address in reversed(chain):
        try:
            ipaddress.ip_address(address)
        except ValueError:
            return peer
        if not trusted(address):
            return address
    return chain[0]


class MCPGate:
    def __init__(
        self,
        app,
        auth,
        issuer,
        context_factory,
        *,
        trusted_proxies=(),
        rate_limit=60,
        user_rate_limit=120,
        max_body=1048576,
        credential_check=None,
        windows=None,
        max_searches=3,
    ):
        self.app, self.auth, self.issuer = app, auth, issuer.rstrip("/")
        self.context_factory, self.trusted_proxies = context_factory, trusted_proxies
        self.rate_limit, self.user_rate_limit, self.max_body = rate_limit, user_rate_limit, max_body
        self.credential_check = credential_check
        self.max_searches = max_searches
        self.bearer = BearerAuthBackend(
            ProviderTokenVerifier(auth), resource_server_url=AnyHttpUrl(self.issuer + "/mcp/")
        )
        self.windows = windows if windows is not None else defaultdict(deque)

    def challenge(self, status=401):
        header = f'Bearer resource_metadata="{self.issuer}/.well-known/oauth-protected-resource", scope="{MCP_SCOPE}"'
        if status == 403:
            header = f'Bearer error="insufficient_scope", scope="{MCP_SCOPE}"'
        return JSONResponse(
            {"error": "insufficient_scope" if status == 403 else "authentication_required"},
            status,
            headers={"WWW-Authenticate": header, "Cache-Control": "no-store"},
        )

    def allow_rate(self, key, limit):
        now = time.monotonic()
        # Bound retained keys; expired identities need not accumulate indefinitely.
        if len(self.windows) > 4096:
            for old_key in list(self.windows):
                if not self.windows[old_key] or self.windows[old_key][-1] < now - 60:
                    del self.windows[old_key]
        window = self.windows[key]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path", "").rstrip("/") != "/mcp":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        token = None
        if b"authorization" in headers:
            value = headers[b"authorization"].decode("latin1")
            if not value.lower().startswith("bearer ") or not value[7:] or len(value) > 8192:
                return await self.challenge()(scope, receive, send)
            authenticated = await self.bearer.authenticate(HTTPConnection(scope))
            token = authenticated[1].access_token if authenticated else None
            if token is None:
                return await self.challenge()(scope, receive, send)
            if self.credential_check:
                try:
                    await self.credential_check(token.user_id)
                except AppError as exc:
                    if exc.status == 401:
                        return await self.challenge()(scope, receive, send)
                    return await JSONResponse({"error": exc.code}, exc.status)(scope, receive, send)
        body = b""
        if scope["method"] == "POST":
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                body += message.get("body", b"")
                if len(body) > self.max_body:
                    return await JSONResponse({"error": "request_too_large"}, 413)(
                        scope, receive, send
                    )
                if not message.get("more_body"):
                    break
            try:
                parsed = json.loads(body)
                items = parsed if isinstance(parsed, list) else [parsed]
                if not items or len(items) > 100:
                    raise ValueError()
                for item in items:
                    if (
                        not isinstance(item, dict)
                        or item.get("jsonrpc") != "2.0"
                        or not isinstance(item.get("method"), str)
                        or not isinstance(item.get("params", {}), dict)
                        or isinstance(item.get("id"), (list, dict, bool))
                    ):
                        raise ValueError()
                protected = any(required_tier(item) == Tier.AUTHENTICATED for item in items)
            except (ValueError, TypeError, UnicodeError):
                return await JSONResponse({"error": "invalid_jsonrpc"}, 400)(scope, receive, send)
            if protected and token is None:
                return await self.challenge()(scope, receive, send)
            if protected and MCP_SCOPE not in token.scopes:
                return await self.challenge(403)(scope, receive, send)
        else:
            parsed = None
        if isinstance(parsed, list):
            search_costs = {
                "similar_videos": 1,
                "similar_channels": 1,
                "propose_playlist": 1,
                "playlist_from_request": 1,
                "video_to_playlist": 1,
                "create_playlist_draft": 1,
                "recommendations": 3,
            }
            searches = sum(
                search_costs.get(item.get("params", {}).get("name"), 0)
                for item in parsed
                if item["method"] == "tools/call"
            )
            if searches > self.max_searches:
                return await JSONResponse(
                    {
                        "error": "quota_exceeded",
                        "message": "Request search cap exceeded; split the request or retry later.",
                    },
                    429,
                )(scope, receive, send)
        ip = client_address(scope, self.trusted_proxies)
        key = ("user", token.user_id) if token else ("ip", ip)
        if not self.allow_rate(key, self.user_rate_limit if token else self.rate_limit):
            return await JSONResponse(
                {"error": "rate_limited", "message": "Sign in or retry later."},
                429,
                headers={"Retry-After": "60"},
            )(scope, receive, send)
        try:
            context = await self.context_factory(token, ip)
        except AppError as exc:
            if exc.status == 401:
                return await self.challenge()(scope, receive, send)
            return await JSONResponse({"error": exc.code}, exc.status)(scope, receive, send)
        scope.setdefault("state", {})["user_context"] = context
        if isinstance(parsed, list):
            # Preflight the entire batch first; only then dispatch each request to SDK transport.
            responses = []
            for item in parsed:
                status, chunks = 200, []
                payload = json.dumps(item).encode()
                single_scope = {
                    **scope,
                    "headers": [(k, v) for k, v in scope["headers"] if k != b"content-length"]
                    + [(b"content-length", str(len(payload)).encode())],
                }

                async def single_receive(payload=payload):
                    return {"type": "http.request", "body": payload, "more_body": False}

                async def collect(event):
                    nonlocal status
                    if event["type"] == "http.response.start":
                        status = event["status"]
                    elif event["type"] == "http.response.body":
                        chunks.append(event.get("body", b""))

                await self.app(single_scope, single_receive, collect)
                if status >= 400:
                    return await Response(
                        b"".join(chunks), status_code=status, media_type="application/json"
                    )(scope, receive, send)
                if "id" in item and chunks and b"".join(chunks):
                    responses.append(json.loads(b"".join(chunks)))
            return await JSONResponse(responses, 200 if responses else 202)(scope, receive, send)
        consumed = False

        async def replay():
            nonlocal consumed
            if not consumed and scope["method"] == "POST":
                consumed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)
