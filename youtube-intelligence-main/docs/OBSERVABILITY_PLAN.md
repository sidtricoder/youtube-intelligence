# Render diagnostics plan

Add JSON events per request and meaningful workflow stage, with server-generated request IDs. Log tool names, controlled error codes, validated field names, endpoint names, timing, cache hits and aggregate quota/selection/write counts. Never log raw inputs, user identities, draft IDs, URLs/query strings, headers, credentials, provider response bodies or exception text. Application stdout replaces noisy MCP protocol chatter; access logs remain off.

Investigation found generic swallowed Pydantic errors, no application diagnostics, and exact-only language matching that excludes en-US when en was requested. Return actionable field errors with request IDs, advertise constraints in tool schemas and match a primary language to regional variants. The incident's exact tool arguments are unavailable: invalid_input identifies the generic ValueError handler, but does not identify the original rejected field.

Use failing-first offline tests for correlated success/errors, validation before provider calls, gate challenges, redaction, regional languages and provider failures. Run full pytest/coverage, Ruff, real HTTP MCP flows and Chromium; build and verify the installed wheel, then deliver the complete ZIP.

2.4.0 update: quota stage events are metering only; app quota/rate rejection is removed by explicit user request. Google errors retain controlled source/reason/upstream status through MCP and REST.
