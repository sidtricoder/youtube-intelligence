"""MCP SDK OAuth endpoints, metadata and one narrowly scoped SDK compatibility shim."""

from mcp.server.auth.routes import create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from pydantic import AnyHttpUrl
from starlette.datastructures import FormData

from .policy import MCP_SCOPE


def install_oauth_routes(app, auth, issuer):
    # Use SDK handlers for standards metadata, DCR, PKCE exchange and revocation.
    app.router.routes.extend(
        create_auth_routes(
            auth,
            AnyHttpUrl(issuer),
            client_registration_options=ClientRegistrationOptions(
                enabled=True, valid_scopes=[MCP_SCOPE], default_scopes=[MCP_SCOPE]
            ),
            revocation_options=RevocationOptions(enabled=True),
        )
    )
    # SDK 1.30 RevocationRequest mistakenly requires a nullable client_secret for public clients.
    # Supply only its missing empty form field; the SDK still authenticates and revokes the client.
    revoke_route = next(
        route for route in app.router.routes if getattr(route, "path", None) == "/revoke"
    )
    from mcp.server.auth.handlers.revoke import RevocationHandler
    from mcp.server.auth.middleware.client_auth import ClientAuthenticator
    from mcp.server.auth.routes import cors_middleware

    sdk_revoke = RevocationHandler(auth, ClientAuthenticator(auth)).handle

    async def revoke_public_compatible(request):
        form = await request.form()
        if "client_secret" not in form:
            request._form = FormData([*form.multi_items(), ("client_secret", "")])
        return await sdk_revoke(request)

    revoke_route.app = cors_middleware(revoke_public_compatible, ["POST", "OPTIONS"])
    revoke_route.endpoint = revoke_route.app

    resource_routes = create_protected_resource_routes(
        AnyHttpUrl(auth.resource),
        [AnyHttpUrl(issuer)],
        scopes_supported=[MCP_SCOPE],
        resource_name="YouTube Intelligence",
    )
    app.router.routes.extend(resource_routes)
    app.add_route(
        "/.well-known/oauth-protected-resource",
        resource_routes[0].endpoint,
        methods=["GET", "OPTIONS"],
    )
