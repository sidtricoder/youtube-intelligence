# Upgrade to 2.1.0 — permissions at setup, unrestricted durations

## Changed behavior

The first Google sign-in now requests all Google permissions this application uses:

- `openid` — identify the connecting user's Google subject.
- `https://www.googleapis.com/auth/youtube.readonly` — read their YouTube activity/profile.
- `https://www.googleapis.com/auth/youtube` — allow the server to create their playlists.

This is a deliberate change from 2.0.x incremental write consent, requested by the user. No
unrelated Drive/Gmail/other Google permissions are requested. Only permissions Google actually
grants are used. A user may decline write access; read-only functions remain usable, and an
explicit permission-recovery action is shown when needed. Older read-only grants also need
reauthorization once. Existing tokens cannot silently acquire additional Google permissions.

The normal flow is now: connect and grant Google read/write access once; ask the AI for a draft;
review and confirm the exact draft. The approval link is still required for the specific playlist,
not another Google permission request when write access was already granted. The original FR-5
human-confirmation rule remains: neither initial OAuth consent nor an AI statement approves
future playlists, and no MCP tool can approve or publish directly.

Fixed 4-hour total and 2-hour individual-video caps are removed. The old 60/30-second minima are
also removed. `total_seconds` and `max_seconds` are optional positive integer seconds, with no
fixed application maximum. Omit them or pass null for unbounded duration. If supplied, they are
still enforced exactly as the caller's preferences. One-second clips, twelve-hour courses and
multi-day totals are valid. There is no default duration ceiling.

Google API availability, sampling, project/per-user quotas and rate limits remain independent
operational constraints. This release does not increase API quota or return unlimited search
results. Long runtimes themselves do not cost extra quota. The existing topic-based draft tool
still discovers candidates by topic; it does not accept a list of exact video IDs from an earlier
response. Do not promise an exact previously recommended set unless the returned draft matches it.

## Deploy and reconnect

1. Replace repository source with this archive's `youtube-intelligence-main/` contents. Keep your
   real `.env` and `data/` untouched. Remove legacy `src/ytintel/auth.py` and `owner.html` if still
   tracked; retain the `security/` package. No database migration/reset is needed for this update.
2. In Google Cloud / Google Auth Platform / Data Access, ensure the Web OAuth app includes the
   `https://www.googleapis.com/auth/youtube` scope in addition to its existing identity/read scopes.
   Keep intended accounts in the test-user list while the app is in Testing. Public production use
   remains subject to Google's review/verification requirements.
3. Keep the Google Web client authorized redirect URI exactly:
   `https://youtube-intelligence-vbyf.onrender.com/oauth/callback` (substitute your actual host if
   different). Render's public origin/callback must match that same host.
4. Keep existing Neon connection URLs, Fernet encryption key, YouTube API key and Google client
   ID/secret unchanged. No new Render environment variable enables this behavior; it is in code.
5. Redeploy. Start a fresh connector sign-in to grant the new write permission. Existing read-only
   credentials do not change merely because the server was redeployed. Refresh/re-add the AI
   connector if it cached the old tool schemas, then start a new chat.
6. In Claude choose **Sign In Now**, **Register Automatically**, **Streamable HTTP**, and URL
   `https://youtube-intelligence-vbyf.onrender.com/mcp/`. Sign In Now performs OAuth at setup;
   Sign In When Needed deliberately defers it until a protected call. Public tools stay anonymous.
7. Accept the required YouTube read/write permissions at Google's consent screen. Later drafts
   normally show the CREATE confirmation directly, without another enable-writes consent step.

## Example prompt

> Create a Python course playlist draft. Let the AI choose suitable videos and duration; omit
> total_seconds and max_seconds so there is no duration limit. Show the approval URL and explain
> that I am reviewing this playlist, not granting Google permission again.

For a chosen duration instead:

> Preview a 200-hour Python playlist with individual videos up to 24 hours long. Use
> total_seconds=720000 and max_seconds=86400.

## Verification

Offline full suite: 235 passed, 10 optional PostgreSQL tests skipped; 91.27% coverage. Ruff and
format checks passed. Chromium passed the own-session confirmation, registered callback/token
exchange and intercepted Google write-consent navigation tests. Two interleaved synthetic accounts
create their own playlists with upfront writes, and a declined write grant is safely recoverable.
Long-duration, omitted-duration, explicit-bound, positive-integer and MCP-schema tests were added.
Google and YouTube upstreams are fakes/fixtures; live Google consent, native Windows, Neon and the
hosted deployment were not tested here. CI includes Windows and an optional PostgreSQL service.
