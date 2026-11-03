"""OAuth request constraints and safe default HTTP responses."""

from urllib.parse import parse_qs

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .browser_policy import form_redirect_policy
from .content_negotiation import prefers_html
from .errors import AppError
from .observability import event, validation_fields
from .policy import MCP_SCOPE
from .ui import error_page


def browser_html(request: Request) -> bool:
    path = request.url.path
    return (
        prefers_html(request.headers.get("accept", ""))
        and not path.startswith(("/api/", "/mcp", "/.well-known/"))
        and path not in {"/token", "/register", "/revoke"}
    )


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
            }
        )
        response.headers.setdefault("Content-Security-Policy", form_redirect_policy())
        return response

    @app.exception_handler(AppError)
    async def application_error(request, exc):
        event("request.rejected", warning=True, error_code=exc.code, status=exc.status)
        headers = (
            {
                "WWW-Authenticate": f'Bearer resource_metadata="{issuer}/.well-known/oauth-protected-resource", scope="{MCP_SCOPE}"'
            }
            if exc.status == 401
            else None
        )
        if browser_html(request):
            response = error_page(exc.message, exc.status)
            response.headers.update(headers or {})
            response.headers["Vary"] = "Accept"
            return response
        return JSONResponse(
            {"error": {"code": exc.code, "message": exc.message}},
            exc.status,
            headers=headers,
        )

    @app.exception_handler(ValueError)
    async def invalid_input(request, exc):
        event(
            "request.rejected",
            warning=True,
            error_code="invalid_input",
            status=422,
            fields=validation_fields(exc),
        )
        if browser_html(request):
            return error_page("Invalid input parameters. Review the request and try again.", 422)
        return JSONResponse(
            {"error": {"code": "invalid_input", "message": "Invalid input parameters"}}, 422
        )

    @app.exception_handler(RequestValidationError)
    async def browser_validation_error(request, exc):
        event(
            "request.rejected",
            warning=True,
            error_code="invalid_input",
            status=422,
            fields=validation_fields(exc),
        )
        if browser_html(request):
            return error_page(
                "This link is incomplete or invalid. Start again from your AI client or your own draft link.",
                422,
            )
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(HTTPException)
    async def browser_http_error(request, exc):
        if browser_html(request):
            response = error_page(
                "We couldn't find that page."
                if exc.status_code == 404
                else "The request could not be completed.",
                exc.status_code,
            )
            response.headers.update(exc.headers or {})
            return response
        return await http_exception_handler(request, exc)
