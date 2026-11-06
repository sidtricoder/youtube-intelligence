"""Instrument the SDK dispatch boundary, including validation before a tool runs."""

import json
import time

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from .observability import event, invalid_input, request_id
from .policy import TOOL_TIERS


class ObservedMCP(FastMCP):
    async def call_tool(self, name, arguments):
        tool = name if name in TOOL_TIERS else "unknown"
        started = time.monotonic()
        event("tool.started", tool=tool)
        try:
            result = await super().call_tool(name, arguments)
        except Exception as exc:
            cause = exc
            while cause.__cause__ is not None:
                cause = cause.__cause__
            if isinstance(cause, ValidationError):
                result = invalid_input(cause)
            else:
                result = {
                    "error": {
                        "code": "tool_unavailable" if tool == "unknown" else "internal_error",
                        "message": "Tool request could not be completed. Share the request_id with the operator.",
                        "request_id": request_id.get(),
                    }
                }
        structured = result[1] if isinstance(result, tuple) else result
        if isinstance(structured, list) and len(structured) == 1:
            text = getattr(structured[0], "text", "")
            try:
                structured = json.loads(text)
            except (ValueError, TypeError):
                structured = None
        error = structured.get("error") if isinstance(structured, dict) else None
        if error:
            event(
                "tool.failed",
                warning=True,
                tool=tool,
                outcome="error",
                error_code=error["code"],
                fields=error.get("fields", []),
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        else:
            event(
                "tool.completed",
                tool=tool,
                outcome="success",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
        return result
