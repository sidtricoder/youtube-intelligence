"""OAuth request constraints and safe default HTTP responses."""

from urllib.parse import parse_qs

from fastapi import Request
from fastapi.responses import JSONResponse

from .errors import AppError
from .policy import MCP_SCOPE


def install_http_boundary(app, auth, issuer):
    @app.middleware("http")
    async def boundary(request: Request, call_next):
        path = request.url.path
        if path in {"/authorize", "/token"}:
            body = await request.body() if request.method == "POST" else b""
            if len(body) > 16384:
                return JSONResponse({"error": "invalid_request"}, 413)
            values = (
                dict(request.query_params)
                if request.method == "GET"
                else {k: v[-1] for k, v in parse_qs(body.decode("utf-8", errors="replace")).items()}
            )
            # SDK handles verifier validation, but does not pass token request resource to provider.
            if path == "/authorize" and values.get("code_challenge_method") != "S256":
                return JSONResponse(
                    {"error": "invalid_request", "error_description": "S256 required"}, 400
                )
            if values.get("resource") != auth.resource:
                return JSONResponse({"error": "invalid_target"}, 400)
        response = await call_next(request)
        response.headers.update(
            {
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "strict-origin",
                "Cache-Control": "no-store",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
            }
        )
        return response

    @app.exception_handler(AppError)
    async def application_error(request, exc):
        headers = (
            {
                "WWW-Authenticate": f'Bearer resource_metadata="{issuer}/.well-known/oauth-protected-resource", scope="{MCP_SCOPE}"'
            }
            if exc.status == 401
            else None
        )
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}}, exc.status, headers=headers
        )

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "Invalid input parameters"}}, 422
        )
