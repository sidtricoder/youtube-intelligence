"""Composition root. MCP bearer authority and browser approval authority stay separate."""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from . import ui
from .api import install_api_routes
from .config import Settings
from .context import AnonymousContext, UserContext
from .credentials import Credentials
from .errors import AppError
from .http_boundary import install_http_boundary
from .http_gate import MCPGate
from .identity import GoogleIdentityProvider, IdentityProvider
from .mcp_server import build_mcp
from .migrate import migrate
from .oauth_routes import install_oauth_routes
from .observability import RequestLogging, configure_logging, event
from .providers.google import GoogleProvider
from .security import AuthServer, SecurityStore
from .service import Intelligence
from .store import Store
from .tenancy import PublicStore, ScopedStore
from .tenant_quota import TenantQuota
from .web import install_browser_routes


def create_app(
    settings: Settings | None = None,
    *,
    provider=None,
    identity_provider: IdentityProvider | None = None,
    provider_factory=None,
):
    configure_logging()
    s = settings or Settings()
    issuer = s.public_base_url or s.local_base_url.rstrip("/")
    raw = (
        Store.from_url(s.database_connection, s.encryption_key)
        if s.database_connection
        else Store(s.db_path, s.encryption_key)
    )
    migrate(raw)
    event("storage.ready", database="postgres" if s.database_connection else "sqlite")
    security = SecurityStore(raw)
    auth = AuthServer(security, issuer)
    client = httpx.AsyncClient(timeout=20, follow_redirects=False)
    idp = identity_provider or GoogleIdentityProvider(
        client, s.google_client_id, s.google_client_secret, s.redirect_uri
    )
    credentials = Credentials(security, idp)
    public_cache = PublicStore(raw)

    async def context_factory(token, ip):
        user_id = token.user_id if token else None
        quota = TenantQuota(
            raw,
            user_id or "public",
            units=s.units_per_day,
            searches=s.searches_per_day,
            user_units=s.user_units_per_day,
            anonymous_units=s.anonymous_units_per_day,
            max_searches=s.max_searches_per_request,
            anonymous=user_id is None,
        )
        if user_id:
            generation = security.current_grant_generation(user_id)
            if generation is None:
                raise AppError("reauthorization_required", "Sign in with Google again", 401)
            return UserContext(user_id, lambda: credentials.access(user_id), quota, generation)
        return AnonymousContext(ip, quota)

    def service_factory(context):
        generation = context.generation if isinstance(context, UserContext) else None
        scoped = (
            ScopedStore(raw, context.user_id, generation=context.generation)
            if isinstance(context, UserContext)
            else public_cache
        )
        selected = provider_factory(context, scoped, client) if provider_factory else provider
        if selected is None:

            async def no_private_access():
                raise AppError("authentication_required", "Sign in to access account data", 401)

            async def invalidate():
                if isinstance(context, UserContext):
                    credentials.invalidate(context.user_id, generation)

            selected = GoogleProvider(
                client,
                context.credentials if isinstance(context, UserContext) else no_private_access,
                scoped,
                public_api_key=s.youtube_api_key,
                context=context,
                public_store=public_cache,
                on_unauthorized=invalidate,
            )
        return Intelligence(
            selected,
            scoped,
            context.quota,
            (lambda: credentials.require_write(context.user_id))
            if isinstance(context, UserContext)
            else None,
            context=context,
            account_lock=credentials.workflow_lock(context.user_id)
            if isinstance(context, UserContext)
            else None,
        )

    mcp = build_mcp(service_factory, issuer, credentials.disconnect)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            event("server.started", version="2.6.2")
            event("quota.policy", outcome="google_only")
            yield
        event("server.stopping", version="2.6.2")
        await client.aclose()
        raw.close()

    app = FastAPI(title="YouTube Intelligence", version="2.6.2", lifespan=lifespan)
    app.state.store, app.state.security, app.state.auth = raw, security, auth
    app.state.mcp, app.state.credentials = mcp, credentials
    app.state.context_factory, app.state.service_factory = context_factory, service_factory

    install_http_boundary(app, auth, issuer)

    @app.api_route("/health", methods=["GET", "HEAD"])
    async def health():
        return {"status": "ok", "provider": "youtube", "version": app.version}

    @app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
    async def home():
        return ui.home_page(issuer)

    install_oauth_routes(app, auth, issuer)

    install_browser_routes(
        app,
        security=security,
        auth=auth,
        idp=idp,
        credentials=credentials,
        service_factory=service_factory,
        raw=raw,
        s=s,
        issuer=issuer,
    )

    rate_windows = install_api_routes(
        app,
        auth=auth,
        issuer=issuer,
        s=s,
        credentials=credentials,
        context_factory=context_factory,
        service_factory=service_factory,
    )

    app.mount("/mcp", mcp.streamable_http_app())
    app.add_middleware(
        MCPGate,
        auth=auth,
        issuer=issuer,
        context_factory=context_factory,
        trusted_proxies=tuple(x.strip() for x in s.trusted_proxies.split(",") if x.strip()),
        rate_limit=s.anonymous_rate_limit,
        user_rate_limit=s.user_rate_limit,
        credential_check=credentials.access,
        windows=rate_windows,
        max_searches=s.max_searches_per_request,
    )
    app.add_middleware(RequestLogging)
    return app
