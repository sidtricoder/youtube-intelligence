# Upgrade to 2.4.0

Deploy this complete project and preserve your database, environment secrets and encryption key. No database migration or Google Cloud OAuth change is required for this update. Confirm Render logs show server.started version 2.4.0 and quota.policy outcome google_only.

## Google-only quota enforcement — explicit latest requirement

There are no application daily unit budgets, per-user allocations, anonymous-pool budgets, request search caps or request-rate limits. Previous YT_UNITS_PER_DAY, YT_SEARCHES_PER_DAY, YT_USER_UNITS_PER_DAY, YT_ANONYMOUS_UNITS_PER_DAY, YT_MAX_SEARCHES_PER_REQUEST, YT_ANONYMOUS_RATE_LIMIT and YT_USER_RATE_LIMIT settings are ignored; remove them from Render if desired. Zero or negative legacy values do not impose limits. No quota reservation/usage estimate can reject a provider call, and direct provider calls need no quota ticket.

Metering remains for operational information and per-account isolation. The quota API/resource reports enforcement google and null limit fields; it cannot know other software's Google project usage. Google remains the authority and can reject calls. Google errors retain a safe details object with source google, known reason (for example quotaExceeded), and upstream_status (for example 403); raw bodies and credentials are never echoed. Stable local error codes remain for AI handling. An actual quota failure during a write becomes a partial/uncertain draft as before; ask playlist_status. An explicit safe resume clears an old error after successful completion and never recreates a known existing playlist.

This explicit change supersedes the original TQ-6 local preflight/fair-share requirement. All callers share Google's project allowance, so another caller can consume it; there is no app-level fairness guarantee. Request-body/batch-size validation, OAuth expiry/PKCE and account/CSRF/approval checks remain security/protocol safeguards, not usage quotas. Bounded metadata sampling and Google's maxResults/pagination rules remain disclosed.

## Plain browser dialogs, AI workflow

The home page is simple. OAuth client consent uses the browser's window.confirm after clicking Allow. Playlist approval uses the browser's window.prompt, showing the exact saved videos and requesting CREATE (or RESUME). Cancel makes no write. Confirmation posts with the same user's browser cookie and CSRF token using fetch; a native alert reports the result/error without navigating to a custom success/error website. Return to the AI conversation and ask playlist_status for the playlist link/result.

A minimal browser document is still necessary to launch a browser-owned dialog at the server's origin. JavaScript-disabled browsers retain a plain form fallback. Google controls its own sign-in/permission pages. A server cannot insert native browser dialogs into Claude/ChatGPT or remove Google's required consent. No MCP tool can approve a write; explicit own-account user confirmation remains.

## Claude reconnect

The code previously rejected the Origin https://claude.ai during post-OAuth initialize/list requests. This was reproduced with an offline OAuth login plus real HTTP and fixed by allowing only the explicit Claude and ChatGPT origins alongside the server/local origins. Arbitrary origins and hosts remain blocked. The fixed /mcp alias is now internally dispatched to /mcp/ without a 307; the OAuth resource/audience remains the exact canonical /mcp/ URL.

1. Redeploy and wait for version 2.4.0 in logs. Wake the home page first if the free Render instance was sleeping.
2. Remove the old Claude connector and add it again with https://youtube-intelligence-vbyf.onrender.com/mcp/ (retain the final slash).
3. Select Streamable HTTP; Sign In Now (or Sign In When Needed); Register Automatically. Leave custom headers empty. Do not select Claude's published identity: this SDK-backed server supports DCR, not CIMD.
4. Complete Google sign-in, click Allow this client and accept the browser confirmation.
5. Enable the connector in a fresh chat. Ask for similar videos first, then a playlist draft. Open the returned approval link only for the short browser confirmation; ask playlist_status in the chat afterward.

These are reproduced compatibility fixes, not proof that a live Claude account/deployment has been exercised. The screenshot's authorization-success error does not identify its failing network request. If it persists, match the next Render request_id and look for auth.token_rejected, auth.challenge, mcp.received, http.completed or tool.failed. The provided ofid reference belongs to Anthropic support; it is not a server request ID. The live deployment was not reachable through our public retrieval tool during this revision, so its current configuration and network response could not be verified.

References: https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp ; https://developers.google.com/youtube/data/determine_quota_cost

## Settings supplied during the incident

The attached deployment log shows 2.3.0 installed, storage.ready with postgres, server.started and successful GET / and GET /health. Logging was functioning. The supplied excerpt contains no /mcp or OAuth traffic, so it cannot explain Claude's failed request. HEAD / and HEAD /health returned 405; 2.4.0 supports those probes with 200 and GET /health includes version for deployment identification.

| Render environment name | Action |
|---|---|
| YT_PUBLIC_BASE_URL | Set https://youtube-intelligence-vbyf.onrender.com without a trailing slash. A trailing slash is normalized, but use the canonical value. |
| YT_REDIRECT_URI | Keep https://youtube-intelligence-vbyf.onrender.com/oauth/callback or remove it so the public-origin callback is derived. The exact same callback must remain registered in Google. |
| YT_LOG_LEVEL | INFO (default); no need for DEBUG/access logs. |
| YT_API_KEY, YT_OWNER_KEY, YT_MCP_URL_KEY | Remove; obsolete single-owner credentials are ignored. Never put these in the connector URL/headers. |
| YT_UNITS_PER_DAY, YT_SEARCHES_PER_DAY and other quota/rate variables | Remove if desired; ignored by 2.4.0 and never used to reject a call. |
| YT_YOUTUBE_API_KEY, YT_GOOGLE_CLIENT_ID, YT_GOOGLE_CLIENT_SECRET | Keep your configured values in Render only. Runtime health does not prove Google has not revoked a credential. |
| YT_ENCRYPTION_KEY | Preserve the existing value for the encrypted database. Do not generate another key for this upgrade. |
| DATABASE_URL_POOLED / DATABASE_URL | Keep existing Neon connection settings and TLS parameters. The pooled URL takes precedence. |
| YT_DB_PATH | Used only without a configured database URL; not Render persistent storage. |

In Render's individual variable fields, paste the value without literal wrapping quotes. In a local dotenv file, wrapping quotes are valid dotenv syntax. This archive contains no supplied secrets, configured .env, personal data or production databases. We have inspected configuration structure and deployment evidence, not performed a new live Google sign-in, YouTube write or Neon connection using the pasted credentials.
