"""FastAPI composition root and authentication boundary for a single local owner."""

import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from importlib.resources import files

import httpx
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.security import HTTPBearer
from pydantic import BaseModel, Field

from .auth import OAuth
from .config import Settings
from .domain import Constraints
from .errors import AppError
from .mcp_server import build_mcp
from .providers.base import Provider
from .providers.google import GoogleProvider
from .quota import Quota
from .service import Intelligence
from .store import Store


class Confirmation(BaseModel):
    confirmation: str = Field(max_length=16)


class RequestText(BaseModel):
    request: str = Field(min_length=5, max_length=1000)


def create_app(settings: Settings | None = None, *, provider: Provider | None = None):
    s = settings or Settings()
    store = (
        Store.from_url(s.database_connection, s.encryption_key)
        if s.database_connection
        else Store(s.db_path, s.encryption_key)
    )
    client = httpx.AsyncClient(timeout=20, follow_redirects=False)
    oauth = OAuth(store, client, s.google_client_id, s.google_client_secret, s.redirect_uri)
    provider = provider or GoogleProvider(
        client, oauth.access_token, store, public_api_key=s.youtube_api_key
    )
    service = Intelligence(
        provider,
        store,
        Quota(store, s.units_per_day, s.searches_per_day),
        oauth.require_write,
        account_lock=oauth.account_lock,
    )
    mcp = build_mcp(service, s.public_base_url)
    mcp_app = mcp.streamable_http_app()
    logging.getLogger("httpx").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app):
        store.purge()
        async with mcp.session_manager.run():
            yield
        await client.aclose()
        store.close()

    app = FastAPI(
        title="YouTube Intelligence",
        version="1.2.0",
        lifespan=lifespan,
        dependencies=[Depends(HTTPBearer(auto_error=False))],
    )
    app.state.service, app.state.mcp, app.state.oauth = service, mcp, oauth
    windows = defaultdict(deque)

    @app.middleware("http")
    async def security(request: Request, call_next):
        path = request.url.path
        # /.well-known/* must answer 404, not 401: a 401 on OAuth discovery makes OAuth-capable
        # clients believe this server requires an OAuth sign-in it does not implement.
        public = path in {
            "/",
            "/health",
            "/oauth/callback",
            "/docs",
            "/openapi.json",
            "/redoc",
        } or path.startswith("/.well-known/")
        if not public:
            header = request.headers.get("authorization", "")
            supplied = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
            is_owner = secrets.compare_digest(supplied.encode(), s.owner_key.encode())
            is_ai = secrets.compare_digest(supplied.encode(), s.api_key.encode())
            # Dedicated URL key: opens /mcp only (never /api or /owner) and only when configured.
            # The explicit emptiness checks matter: compare_digest("", "") is True.
            url_key = request.query_params.get("key", "")
            is_url_key = bool(
                s.mcp_url_key
                and url_key
                and (path == "/mcp" or path.startswith("/mcp/"))
                and secrets.compare_digest(url_key.encode(), s.mcp_url_key.encode())
            )
            if path.startswith("/mcp") and not (is_ai or is_url_key):
                return JSONResponse({"error": {"code": "unauthorized"}}, 401)
            if not (is_owner or is_ai or is_url_key):
                return JSONResponse({"error": {"code": "unauthorized"}}, 401)
            if path.startswith("/owner/") and not is_owner:
                return JSONResponse({"error": {"code": "owner_required"}}, 403)
            if request.method not in ("GET", "HEAD", "OPTIONS") and path.startswith("/owner/"):
                # Authorization header is required and CORS is disabled. Cross-origin browser writes denied.
                origin = request.headers.get("origin")
                if origin and origin != str(request.base_url).rstrip("/"):
                    return JSONResponse({"error": {"code": "origin_denied"}}, 403)
            key = "owner" if is_owner else "ai"
            now = time.monotonic()
            queue = windows[key]
            while queue and queue[0] < now - 60:
                queue.popleft()
            if len(queue) >= 60:
                return JSONResponse(
                    {"error": {"code": "rate_limited"}}, 429, headers={"Retry-After": "60"}
                )
            queue.append(now)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        if path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )
        return response

    @app.exception_handler(AppError)
    async def application_error(request, exc):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, exc.status)

    @app.exception_handler(ValueError)
    async def validation_error(request, exc):
        return JSONResponse({"error": {"code": "invalid_input", "message": str(exc)}}, 422)

    @app.get("/health", openapi_extra={"security": []})
    async def health():
        return {"status": "ok", "provider": "youtube"}

    @app.get("/", response_class=HTMLResponse)
    async def owner_page():
        return files("ytintel").joinpath("owner.html").read_text()

    @app.get("/api/quota")
    async def quota():
        return service.quota.status()

    @app.get("/api/similar-videos")
    async def similar_videos(video: str = Query(max_length=300)):
        return await service.similar_videos(video)

    @app.get("/api/similar-channels")
    async def similar_channels(channel: str = Query(max_length=200)):
        return await service.similar_channels(channel)

    @app.get("/api/recommendations")
    async def recommendations():
        return await service.recommend()

    @app.get("/api/analysis")
    async def analysis(
        start: str | None = None, end: str | None = None, previous_start: str | None = None
    ):
        return await service.analysis(start, end, previous_start)

    @app.post("/api/drafts")
    async def propose(c: Constraints):
        return await service.propose(c)

    @app.post("/api/drafts/from-request")
    async def request_draft(body: RequestText):
        from .domain import parse_request

        return await service.propose(parse_request(body.request))

    @app.get("/api/drafts/{ident}")
    async def draft(ident: str):
        return service.draft(ident)

    @app.post("/owner/drafts/{ident}/approve")
    async def approve(ident: str, body: Confirmation):
        return await service.approve(ident, body.confirmation)

    @app.post("/owner/drafts/{ident}/resume")
    async def resume(ident: str, body: Confirmation):
        return await service.resume(ident, body.confirmation)

    @app.get("/owner/oauth/start")
    async def oauth_start(write: bool = False):
        url, state, binding = oauth.start(write)
        response = JSONResponse({"url": url})
        response.set_cookie(
            "yt_oauth_binding",
            binding,
            max_age=600,
            httponly=True,
            samesite="lax",
            secure=s.redirect_uri.startswith("https://"),
            path="/oauth/callback",
        )
        return response

    @app.get("/oauth/callback", response_class=HTMLResponse)
    async def callback(
        request: Request, state: str = Query(max_length=100), code: str = Query(max_length=4096)
    ):
        await oauth.exchange(code, state, request.cookies.get("yt_oauth_binding", ""))
        response = HTMLResponse(
            "<p>Google connected. Close this tab and return to your original owner tab to continue.</p>"
        )
        response.delete_cookie("yt_oauth_binding", path="/oauth/callback")
        return response

    @app.post("/owner/disconnect")
    async def disconnect():
        await oauth.disconnect()
        return {"status": "disconnected", "local_data": "tokens, cache and drafts deleted"}

    app.mount("/mcp", mcp_app)
    return app
