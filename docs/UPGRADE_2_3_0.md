# Upgrade to 2.3.0: actionable errors and Render diagnostics

Deploy the complete source archive. Preserve your existing environment, database and encryption key. No Google Cloud scope, redirect URI or database migration change is required. JSON application logging is on at INFO by default and writes to stdout, so it appears in Render's service log monitor. Optionally set the process environment variable `YT_LOG_LEVEL=INFO` explicitly in Render. Do not enable Uvicorn access logs or HTTP client debug logging; these can expose OAuth query strings and credentials.

After deploy, confirm a `server.started` record with `version: "2.3.0"`. Refresh/reconnect the AI connector if it still uses an older tool schema. Repeat the failing request once and ask the AI to show the exact tool name, arguments and complete error response. Share the error's request_id and matching Render log lines, removing any sensitive content. This version cannot recover arguments from an earlier deployment's absent logs.

## What the supplied error establishes

`invalid_input / Invalid input parameters` came from a tool's ValueError/Pydantic handling. It does not identify the field, and is not evidence of a Google permissions failure. The original parameters are unavailable, so the exact rejected field cannot be stated. The old code discarded validation details.

The new response names safe field names and explains their format, without echoing values. Examples: language must be a code (`en`, not `English`); duration bounds are optional positive whole seconds; a topic has 2–200 characters. This is input validation, not a playlist-duration maximum. The same restrictions now appear in tool schemas so clients can prepare valid calls.

A separate reproduced selection bug is fixed: requesting `en` now accepts metadata marked `en-US`/`en-GB`. A request for a particular regional code still requires that code; unknown metadata language stays excluded. This can prevent no_matches but is not a demonstrated explanation of the reported invalid_input.

## Safe end-to-end smoke check

Ask: “Use create_playlist_draft with topic C++ beginner tutorials, language en, and omit both duration arguments. Show the exact returned approval_url. If it fails, show the exact error code, fields and request_id; do not invent a learning playlist.”

Protected tools still require sign-in. A draft is successful only when the tool returns an id, pending status and approval_url. Open the link, review the actual videos, type CREATE and confirm. Then ask playlist_status. A table of suggested lessons alone is not a server draft or YouTube playlist.

## Reading the logs

Every HTTP request has a fresh server-generated request_id, also returned as X-Request-ID. Tool errors include it; draft-not-found and existing REST error bodies remain unchanged for compatibility and use the header instead. Search Render logs for the ID to follow the request. HTTP 200 only means the MCP exchange succeeded; inspect tool.failed/tool.completed for the actual tool outcome.

| Event | What it tells you |
|---|---|
| server.started / storage.ready | Running version and database engine, never connection strings |
| http.started / http.completed | Safe route template, method, HTTP status and duration |
| mcp.received / tool.started | Protocol operation and allow-listed tool name |
| auth.resolved / auth.challenge / auth.token_rejected | Anonymous/authenticated request or real OAuth challenge |
| request.rejected / tool.failed | Controlled error code, safe failing field names and tool timing |
| quota.reserved / quota.settled / quota.rejected | Reserved/consumed units and searches; project, anonymous or user budget class |
| discovery.started / discovery.completed / playlist.selected | Candidate and selected counts; zero selection explains no_matches |
| youtube.cache_hit / youtube.started / youtube.completed / youtube.failed | Endpoint name, public/private mode, status, mapped error and timing |
| google.login_started / google.exchange_* / google.refresh_* | Google consent, code exchange and credential renewal stages |
| oauth.authorize_* / oauth.code_* / oauth.refresh_* / oauth.consent_completed | MCP authorization stages, code exchange/rotation and consent outcome |
| draft.created / playlist.approval_verified / playlist.write_* / playlist.video_inserted | Own-account draft, explicit browser approval and write progress |
| http.failed | Sanitized unexpected failure; no automatic retry or exception dump |

No raw arguments, topics, titles, profile data, email/sub/user IDs, draft/playlist IDs, IPs, query strings, request/response bodies, token material or exception text are logged. This deliberately excludes sensitive “every byte” tracing. SDK protocol chatter is suppressed in favor of these events. Render's platform deployment/port messages remain outside application control. Configure platform log retention and restrict team access appropriately.

The application cannot force the AI client to stop generating its own prose. Tool instructions now require it to report exact failures and avoid claiming a nonexistent draft or substituting unrelated web results.
