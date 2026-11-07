"""REST adapters share the same account identity and service isolation as MCP."""

from fastapi import Request

from .domain import Constraints
from .errors import AppError
from .http_gate import MCPGate, client_address
from .policy import MCP_SCOPE


def install_api_routes(app, *, auth, issuer, s, credentials, context_factory, service_factory):
    rest_windows = MCPGate(
        None,
        auth,
        issuer,
        context_factory,
        rate_limit=s.anonymous_rate_limit,
        user_rate_limit=s.user_rate_limit,
    )

    async def rest_service(request, protected=False):
        supplied = request.headers.get("authorization")
        token = None
        if supplied is not None:
            token = (
                await auth.load_access_token(supplied[7:])
                if supplied.startswith("Bearer ")
                else None
            )
            if token is None:
                raise AppError("authentication_required", "Sign in again", 401)
        if protected and token is None:
            raise AppError("authentication_required", "Sign in to access your account", 401)
        if protected and MCP_SCOPE not in token.scopes:
            raise AppError("insufficient_scope", "Additional scope required", 403)
        ip = client_address(
            request.scope, tuple(x.strip() for x in s.trusted_proxies.split(",") if x.strip())
        )
        if token:
            await credentials.access(token.user_id)
        return service_factory(await context_factory(token, ip))

    @app.get("/api/similar-videos")
    async def similar_videos(request: Request, video: str):
        return await (await rest_service(request)).similar_videos(video)

    @app.get("/api/similar-channels")
    async def similar_channels(request: Request, channel: str):
        return await (await rest_service(request)).similar_channels(channel)

    @app.get("/api/recommendations")
    async def recommendations(request: Request):
        return await (await rest_service(request, True)).recommend()

    @app.get("/api/analysis")
    async def analysis(
        request: Request,
        start: str | None = None,
        end: str | None = None,
        previous_start: str | None = None,
    ):
        return await (await rest_service(request, True)).analysis(start, end, previous_start)

    @app.get("/api/quota")
    async def quota(request: Request):
        return (await rest_service(request, True)).quota.status()

    @app.post("/api/drafts")
    async def create_draft(request: Request, constraints: Constraints):
        return await (await rest_service(request, True)).propose(constraints)

    @app.get("/api/drafts/{ident}")
    async def draft_status(request: Request, ident: str):
        return (await rest_service(request, True)).draft(ident)

    @app.post("/api/disconnect")
    async def disconnect(request: Request):
        service = await rest_service(request, True)
        return await credentials.disconnect(service.context.user_id)

    return rest_windows.windows
