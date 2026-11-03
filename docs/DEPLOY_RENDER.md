# Deploy on Render + Neon and connect Claude

Deploy source from a private GitHub repository, use Neon for persistence, and enter secrets manually in Render Environment. The handoff contains only `.env.example`; never upload an existing `.env`, database or configured ZIP. No persistent Render disk is needed.

## 1. Prepare source and Google

Push the Dockerfile, lockfile, project metadata, source, scripts and deployment configuration. Confirm `.env` and local data are ignored and untracked before pushing. Keep existing local `.env` and data untouched. If secrets were previously committed, remove them from tracking and rotate exposed secrets; ignoring a file does not erase history.

Create/use a Google OAuth **Web application** client and enable YouTube Data API v3. Configure the external consent screen and test users. Initial consent requests `openid`, `https://www.googleapis.com/auth/youtube.readonly` and `https://www.googleapis.com/auth/youtube`. Google grants are checked; declined or legacy read-only grants have explicit write-permission recovery. Each end user supplies their own consent; the operator never connects an account for everyone.

Testing mode is limited to 100 test users and refresh tokens for this scope flow may expire after seven days. Production distribution requires applicable Google verification/review. Check actual project quota settings: the application defaults to 10,000 general units/day and a separate 100 `search.list` calls/day ceiling; these are local caps, not guaranteed upstream availability.

## 2. Configure Render

Create a Docker web service from the private repository. Root Directory is the directory containing Dockerfile and pyproject.toml. The entry point honors `PORT`; use `/health` as the health check. Configure secrets without surrounding shell quotes:

| Variable | Purpose |
|---|---|
| `DATABASE_URL_POOLED` | Neon pooled PostgreSQL URL, preferred for runtime |
| `DATABASE_URL` | Optional direct URL for an explicitly documented administration workflow |
| `YT_ENCRYPTION_KEY` | Fernet key, retained across deploys; generate once for a new installation |
| `YT_YOUTUBE_API_KEY` | Restricted Google API key for public metadata calls |
| `YT_GOOGLE_CLIENT_ID` | Google Web client ID |
| `YT_GOOGLE_CLIENT_SECRET` | Google Web client secret |
| `YT_GOOGLE_PROJECT_ID` | Your Google project identifier |
| `YT_PUBLIC_BASE_URL` | Canonical HTTPS origin if overriding Render's external origin |
| `YT_REDIRECT_URI` | Omit to derive, or exact canonical origin + `/oauth/callback` |
| `YT_LOCAL_BASE_URL` | Local development origin only; defaults to `http://localhost:8000`, set for a custom port |
| `YT_TRUSTED_PROXIES` | Comma-separated trusted ingress IPs/CIDRs; default empty, never `*` |
| `YT_USER_UNITS_PER_DAY` | Per-user daily general units; default `1000` |
| `YT_ANONYMOUS_UNITS_PER_DAY` | Anonymous global pool; omitted defaults dynamically to 30% of project units |

Use `.env.example` for the complete current setting names and defaults, including tenant/anonymous budgets and rate limits. Preserve Neon TLS parameters, including `sslmode=require` and supplied channel binding. A configured database outage fails closed rather than switching to an ephemeral local database. Keep the encryption key out of Git; changing it without migration makes stored records unreadable.

Render supplies `RENDER_EXTERNAL_URL`. Remove stale localhost/different-host callback overrides from Render only. Choose one canonical HTTPS origin and use it for browser sessions, MCP discovery and callback registration. Configure trusted proxy addresses for the deployed ingress explicitly; trusting arbitrary forwarded IPs defeats IP quotas. Do not enable wildcard CORS or set a wildcard proxy trust as a shortcut.

Do not configure legacy `YT_API_KEY`, `YT_OWNER_KEY` or `YT_MCP_URL_KEY` as a client authorization mechanism. They do not replace per-user OAuth. Redeploy after setting secrets. Run the idempotent migration once with the configured production environment:

```bash
python -m ytintel.migrate --database-url-env DATABASE_URL_POOLED
```

The CLI reads that URL and `YT_ENCRYPTION_KEY` from environment variables without printing their values. For an explicit local file, use `python -m ytintel.migrate --sqlite /path/to/local.db` with the encryption key exported. A bare migration command is rejected because the target must be explicit. Startup performs the same idempotent version-1 table initialization. Existing single-owner records are ignored, never imported into a user account; users connect again and build fresh drafts. Before migrating an existing installation, back up encrypted data and retain its encryption key. Do not point tests at production data.

## 3. Register the exact hosted callback

For a service whose canonical origin is `https://your-service.onrender.com`, register this exact Google redirect URI:

```text
https://your-service.onrender.com/oauth/callback
```

The callback is at the root, never under `/mcp`. An independently registered localhost URI can remain for local development; it is not a runtime fallback. Startup/callback mismatches must be resolved with the canonical origin rather than bypassing validation.

## 4. Add Claude connector

In the custom remote connector dialog choose:

| Field | Value |
|---|---|
| Server URL | `https://your-service.onrender.com/mcp/` |
| Transport | Streamable HTTP |
| Authentication | Sign In Now |
| Client registration | Register Automatically |

Use the trailing slash. Do not append `?key=`, supply a static bearer token/header or paste Google secrets. The server advertises SDK dynamic client registration with HTTPS/loopback redirect validation. CIMD is unsupported and is not advertised. The root protected-resource metadata and OAuth challenge let the client discover sign-in when protected work is requested. MCP scope `youtube:read` is distinct from Google's consent scopes.

## 5. Verify as an end user

First ask anonymously:

> Find videos similar to https://www.youtube.com/watch?v=rfscVS0vtbw.

Then:

> Preview a one-hour Python playlist, with no video over 15 minutes, language en.

Public previews are stateless and cannot be approved as user drafts. Next ask for personal recommendations and complete Google sign-in as your own account when prompted. For a real playlist, create an authenticated draft, open its approval page in that same user's browser session and approve the exact draft. Read/write Google permission is requested during initial connection; enable-writes recovery is shown only if writes were declined or missing. The AI cannot approve on your behalf. Ask for its status afterward.

Repeat with a second account in an independent browser session to confirm private results, draft/status access and disconnect are isolated. See TESTING.md for the complete acceptance sequence. Successful public discovery alone does not verify refresh tokens, production Google approval or live writes.

Render free instances may sleep and cold-start, and Neon free plans have resource/availability limits. Wake the root page before reconnecting after a long idle period. Durable database storage survives an app restart but does not guarantee uptime. Check current plan terms and quotas in the provider dashboards; this guide does not promise permanent free pricing or a production SLA.

| Symptom | Action |
|---|---|
| Callback mismatch | Use the exact HTTPS root callback in both app configuration and Google Web client |
| Public call with token returns 401 | Remove/re-authorize the invalid token; supplied bad credentials are never downgraded to anonymous |
| Protected call returns 401 | Complete the discovered sign-in flow; inspect the Bearer resource metadata challenge |
| Write scope required | Enable writes in your own browser, then review a fresh owned draft |
| Draft unavailable | Use the account that created it; IDs never grant cross-user access |
| Quota exhausted | Wait for reset or lower usage; sign-in does not bypass project/search ceilings |
| Database unavailable | Check Neon connectivity/TLS and secrets; no silent SQLite fallback is expected |
| Connector timeout after idle | Wake the hosted root page, then reconnect; inspect deployment health if it persists |

Run one application process/worker per deployment. The launcher explicitly uses one worker; in-process request rate windows require one instance (daily quota and token rotation are database-atomic). Add a distributed rate limiter before horizontal scaling.

For the 2.1.0 scope/optional-duration upgrade and existing-account reconnection steps, see UPGRADE_2_1_0.md.
