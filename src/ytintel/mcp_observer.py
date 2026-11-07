"""Instrument the SDK dispatch boundary, including validation before a tool runs."""

import json
import re
import time

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from .observability import event, invalid_input, request_id
from .policy import TOOL_TIERS


class ObservedMCP(FastMCP):
    async def _unknown_arguments(self, name, arguments):
        """The SDK ignores undeclared arguments; a dropped limit must fail loudly instead."""
        if not isinstance(arguments, dict):
            return None
        schema = next((t.inputSchema for t in await self.list_tools() if t.name == name), None)
        allowed = set((schema or {}).get("properties", {}))
        extra = sorted(set(arguments) - allowed) if schema else []
        if not extra:
            return None
        safe = [k if re.fullmatch(r"[A-Za-z0-9_]{1,40}", str(k)) else "<invalid>" for k in extra]
        return {"names": safe[:10], "allowed": sorted(allowed)}

    async def call_tool(self, name, arguments):
        tool = name if name in TOOL_TIERS else "unknown"
        started = time.monotonic()
        event("tool.started", tool=tool)
        try:
            unknown = await self._unknown_arguments(name, arguments)
            if unknown:
                result = {
                    "error": {
                        "code": "unknown_parameter",
                        "message": "Unsupported parameter(s): "
                        + ", ".join(unknown["names"])
                        + ". Nothing was run, so no limit was silently ignored. Supported: "
                        + ", ".join(unknown["allowed"])
                        + ". If a parameter you need is missing, the server is older than your "
                        "tool list: reconnect the connector or ask the operator to redeploy.",
                        "fields": unknown["names"],
                        "request_id": request_id.get(),
                    }
                }
            else:
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
