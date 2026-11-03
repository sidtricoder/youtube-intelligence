# Google setup

Follow [Deploy on Render + Neon](DEPLOY_RENDER.md) for current setup and the exact hosted callback. Enable YouTube Data API v3 and configure a Google OAuth **Web application** client for the canonical origin. The hosted redirect URI is exactly `https://<host>/oauth/callback`, at the root. Local development defaults to `http://localhost:8000/oauth/callback`; configure `YT_LOCAL_BASE_URL` and register the exact URI when using another port.

Each user signs in to their own account. Default consent requests `openid` plus `https://www.googleapis.com/auth/youtube.readonly`; verified OIDC `sub` is the isolation identity. Only the explicit POST write-enable action on the user's draft approval page requests `https://www.googleapis.com/auth/youtube`. Scope consent does not approve a draft; the same user must review and confirm the exact immutable draft afterward. There is no shared operator Google account.

For an external app in Testing, plan for a 100-test-user limit and seven-day refresh-token expiry for this non-basic scope flow. Production availability requires applicable Google verification/review; check the actual consent-screen status and quotas in Google Cloud. The application's default project caps are 10,000 general units/day and separately 100 `search.list` calls/day; other project consumers and Google limits can reduce availability.

Set the Google API key, OAuth client ID and client secret privately in Render Environment. Do not attach or commit a configured `.env`, client-secret JSON or token. The MCP scope `youtube:read` belongs to the app's authorization flow and is not a Google scope. Claude uses Sign In When Needed and Register Automatically with the plain HTTPS `/mcp/` URL.
