"""Allow-listed JSON events: no request bodies, URLs, identities or exception text."""

import json
import logging
import os
import re
import secrets
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone

request_id: ContextVar[str] = ContextVar("request_id", default="background")
logger = logging.getLogger("ytintel")
FIELDS = {
    "tool",
    "operation",
    "route",
    "method",
    "status",
    "outcome",
    "error_code",
    "fields",
    "duration_ms",
    "auth_class",
    "units",
    "searches",
    "used_units",
    "used_searches",
    "scope_class",
    "candidate_count",
    "selected_count",
    "excluded_count",
    "video_count",
    "inserted_count",
    "cached",
    "public",
    "endpoint",
    "version",
    "database",
    "step",
}
INPUT_FIELDS = {
    "topic",
    "total_seconds",
    "max_seconds",
    "language",
    "exclude_saved",
    "video",
    "channel",
    "request",
    "draft_id",
    "start",
    "end",
    "previous_start",
}


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(record.event_data, separators=(",", ":"), ensure_ascii=True)


def configure_logging() -> None:
    if not any(isinstance(h.formatter, JSONFormatter) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    level = os.environ.get("YT_LOG_LEVEL", "INFO").upper()
    logger.setLevel(level if level in {"DEBUG", "INFO", "WARNING", "ERROR"} else "INFO")
    logger.propagate = False
    for name in ("httpx", "httpcore", "mcp"):
        # SDK exception text can contain raw tool arguments. Application events replace it.
        logging.getLogger(name).setLevel(logging.CRITICAL)


def event(name: str, *, warning: bool = False, **fields) -> None:
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": "WARNING" if warning else "INFO",
        "event": name,
        "request_id": request_id.get(),
    }
    data.update({k: v for k, v in fields.items() if k in FIELDS})
    logger.log(logging.WARNING if warning else logging.INFO, name, extra={"event_data": data})


def validation_fields(exc: Exception) -> list[str]:
    from pydantic import ValidationError

    if not isinstance(exc, ValidationError):
        return []
    return sorted(
        {
            str(part)
            for error in exc.errors(include_input=False, include_context=False)
            for part in error["loc"]
            if part in INPUT_FIELDS
        }
    )


def invalid_input(exc: Exception) -> dict:
    fields = validation_fields(exc)
    message = "Invalid input parameters. Use the tool schema and retry."
    if "language" in fields:
        message = "language must be a language code such as 'en' or 'hi', not a language name."
    elif any(f in fields for f in ("total_seconds", "max_seconds")):
        message = "Duration bounds must be positive whole seconds; omit them for no duration bound."
    elif "topic" in fields:
        message = "topic must contain 2 to 200 characters."
    return {
        "error": {
            "code": "invalid_input",
            "message": message,
            "fields": fields,
            "request_id": request_id.get(),
        }
    }


def safe_route(path: str) -> str:
    if path.startswith("/approve/"):
        return "/approve/{draft_id}" + ("/enable-writes" if path.endswith("/enable-writes") else "")
    if path.startswith("/api/drafts/") and path != "/api/drafts/from-request":
        return "/api/drafts/{draft_id}"
    known = {
        "/",
        "/health",
        "/mcp",
        "/mcp/",
        "/authorize",
        "/token",
        "/register",
        "/revoke",
        "/login",
        "/oauth/start",
        "/oauth/callback",
        "/oauth/consent",
        "/api/preview",
        "/api/drafts",
        "/api/drafts/from-request",
        "/api/disconnect",
        "/api/quota",
        "/api/recommendations",
        "/api/analysis",
        "/api/similar-videos",
        "/api/similar-channels",
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource",
    }
    return path if path in known else "/unmatched"


class RequestLogging:
    """Outermost ASGI observer includes HTTP auth gate rejections without reading bodies."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        ident = secrets.token_hex(12)
        token = request_id.set(ident)
        scope.setdefault("state", {})["request_id"] = ident
        route = safe_route(scope.get("path", ""))
        method = scope.get("method", "")
        method = method if re.fullmatch("[A-Z]{1,12}", method) else "UNKNOWN"
        status, started = 500, time.monotonic()
        response_started = False
        response_complete = False
        event("http.started", route=route, method=method)

        async def observed_send(message):
            nonlocal status, response_started, response_complete
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                message = {
                    **message,
                    "headers": list(message.get("headers", []))
                    + [(b"x-request-id", ident.encode())],
                }
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                response_complete = True
            await send(message)

        try:
            await self.app(scope, receive, observed_send)
        except Exception:
            event("http.failed", warning=True, route=route, error_code="internal_error")
            try:
                if not response_started:
                    from starlette.responses import JSONResponse

                    await JSONResponse(
                        {
                            "error": {
                                "code": "internal_error",
                                "message": "Request could not be completed.",
                                "request_id": ident,
                            }
                        },
                        500,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                    )(scope, receive, observed_send)
                elif not response_complete:
                    # Never retry side effects or append error text to an in-progress response.
                    await send({"type": "http.response.body", "body": b"", "more_body": False})
            except Exception:
                # A disconnected/finished transport must not trigger a chained exception dump.
                event("http.transport_failed", warning=True, error_code="response_interrupted")
        finally:
            event(
                "http.completed",
                route=route,
                method=method,
                status=status,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            request_id.reset(token)
