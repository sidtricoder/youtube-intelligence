# Deploy this version on Render Free + Neon, then connect Claude

This release supports PostgreSQL directly. No persistent Render disk is needed. The private ZIP includes the supplied Neon direct/pooled URLs and Google/app keys in `.env`; Git excludes that file. Application tables are created automatically in a dedicated PostgreSQL schema named `ytintel`. Existing unrelated tables are not modified. The pooled URL is preferred when both URLs are set.

## 1. Update GitHub

Replace the previous project source with this version, including `Dockerfile`, `requirements.lock`, `pyproject.toml`, `src/`, `scripts/` and `render.yaml`. Commit/push source changes. Do not commit the configured `.env` or the ZIP containing it. If `.env` was previously tracked, `.gitignore` alone cannot untrack it; remove it from the index with `git rm --cached .env` before committing.

## 2. Configure the existing Render service

Keep the detected **Docker** runtime and **Free** instance. Set Root Directory to the directory containing `Dockerfile` and `pyproject.toml`. If those files are under `youtube-intelligence/` in GitHub, use that as Root Directory; if they are at repository root, leave Root Directory blank.

In the service's **Environment** page, add/import these variables from the private `.env`:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Your supplied direct Neon PostgreSQL URL |
| `DATABASE_URL_POOLED` | Your supplied pooled Neon PostgreSQL URL (runtime prefers this) |
| `YT_ENCRYPTION_KEY` | Preserve the exact value in your configured `.env` |
| `YT_API_KEY` | App/MCP credential from `.env` |
| `YT_OWNER_KEY` | Separate owner credential from `.env` |
| `YT_YOUTUBE_API_KEY` | Google API key from `.env` |
| `YT_GOOGLE_CLIENT_ID` | Google OAuth client ID from `.env` |
| `YT_GOOGLE_CLIENT_SECRET` | Google OAuth client secret from `.env` |
| `YT_GOOGLE_PROJECT_ID` | `dark-smile` |

Paste values without surrounding quotes. Preserve `sslmode=require&channel_binding=require` in Neon URLs. Do not regenerate encryption/app keys on every deploy; saved credentials are encrypted with that encryption key.

**Remove `YT_REDIRECT_URI` if it contains the old localhost callback.** Also remove an old `YT_PUBLIC_BASE_URL` if it names a different deployment. Render supplies `RENDER_EXTERNAL_URL`; the application derives its exact HTTPS callback and MCP hostname from that origin. A mismatched explicit callback now stops startup with a clear configuration error instead of silently using a fallback.

For your own custom domain, explicitly set `YT_PUBLIC_BASE_URL=https://your-domain.example` and set `YT_REDIRECT_URI` to the same origin plus `/oauth/callback`, or omit `YT_REDIRECT_URI` to derive it. Use the chosen domain consistently for the owner UI and OAuth.

No manual Docker start command is needed. The image starts `python -m ytintel`, binds `0.0.0.0`, honors Render's `PORT`, and correctly trusts Render's proxy headers. Health Check Path: `/health`. Keep one instance/process for this single-owner application.

Select **Save, rebuild and deploy** (or deploy the latest commit). `render.yaml` provides equivalent settings for a new Blueprint deployment; secret values are prompted, never included in YAML.

## 3. Register the hosted Google callback

Copy your actual HTTPS Render service URL from the dashboard. Example only:

```
https://your-service.onrender.com
```

In the Google OAuth Web client, add:

```
https://your-service.onrender.com/oauth/callback
```

Keep the existing localhost callback if you still want local use. These are separately registered exact URIs, not runtime fallbacks.

## 4. Connect Google once

Open the hosted owner page, enter `YT_OWNER_KEY`, then click **Enable playlist writes** if you want all features (or **Connect Google (read)** for read-only access). Complete consent in the new tab and return to the original owner tab. Google account consent is separate from the bearer credential Claude uses to reach your MCP server.

Tokens, drafts, cached data and quota counters are stored encrypted in Neon and survive a Render restart/redeploy. Sign-in/scope escalation deliberately invalidates older drafts; build a fresh preview after authorization. Google can still expire/revoke a grant, including Testing-mode token expiry; reauthorize when requested.

## 5. Connect Claude

In Claude: **Customize → Connectors → Add → Custom → Web**.

- Name: `YouTube Intelligence`
- Server URL: `https://your-service.onrender.com/mcp/` (include trailing slash).
- Use fixed-request-header authentication; no MCP OAuth sign-in is required for this server.
- Request header name: `Authorization`.
- Request header value: `Bearer ` followed by your **YT_API_KEY** value.

Do not give Claude your owner key, Google client secret, database URL or encryption key. The server's Google sign-in is performed on the hosted owner page. It is not an MCP OAuth authorization server for ChatGPT.

Enable the connector in a conversation and ask:

> Use YouTube Intelligence to find similar videos to https://www.youtube.com/watch?v=rfscVS0vtbw.

Then:

> Build a one-hour Python learning playlist, with no video over 15 minutes. Show me the preview and where to approve it.

Approve the exact draft in the hosted owner page. AI tools cannot approve writes. The server supplies its owner page URL through MCP metadata/resources. After approval Claude can read `playlist_status`.

Render Free sleeps when idle and may take about a minute to wake. If Claude's initial connection times out after a long idle period, open the hosted owner page, let the service finish waking, then reconnect Claude. Persistent Neon storage prevents that sleep from erasing authorization. Free-tier quotas still apply; this setup is for personal/student use, not an always-on production SLA.

## Errors

| Error | Fix |
|---|---|
| Missing required local app key | Import the existing .env values into Render Environment |
| Callback mismatch at startup | Remove the localhost `YT_REDIRECT_URI` on Render or set the exact hosted callback |
| Google `redirect_uri_mismatch` | Register the exact hosted callback in Google Cloud, not just localhost |
| `database_unavailable` | Check Neon URL/password/TLS and service availability; there is no silent SQLite fallback |
| MCP `421 Invalid Host` | Confirm the service's actual HTTPS origin is configured; v1.2 includes the public hostname in its allowlist |
| `origin_denied` on owner actions | Use the configured HTTPS domain; v1.2 recognizes Render proxy headers |
| Owner `401` | Enter `YT_OWNER_KEY` in the owner page, without quotes; Google consent does not replace it |
| Claude unauthorized | Use `YT_API_KEY` in the Authorization request header, not the Google API key |

## Official references

- https://render.com/docs/docker
- https://render.com/docs/environment-variables
- https://render.com/docs/configure-environment-variables
- https://render.com/docs/free
- https://neon.com/docs/get-started-with-neon/connect-neon
- https://support.claude.com/en/articles/11176164-use-connectors-to-extend-claude-s-capabilities
