# YouTube Intelligence — multi-account FastAPI + MCP

Discover related YouTube videos and channels publicly, then sign in with your own Google account for recommendations, engagement analysis and reviewed private playlists. The production provider uses the official YouTube Data API v3. Summaries use title/description metadata, not transcripts or claims of watching a video.

For the Windows CI and consent-form fixes, follow [the 2.0.1 upgrade steps](docs/UPGRADE_2_0_1.md).

Start with [Render + Neon deployment](docs/DEPLOY_RENDER.md). The hosted MCP URL is **`https://<host>/mcp/`**. In Claude choose **Streamable HTTP**, **Sign In When Needed** and **Register Automatically**. Use the plain URL with its trailing slash; no static bearer key, query key or custom header is needed. Sign-in is requested when you use protected features.

The handoff contains `.env.example`, never a configured `.env`. Keep secrets in Render Environment or a private local environment; do not commit or attach them. Preserve an existing encryption key for existing records.

## Use it

1. Ask for videos similar to a YouTube URL or channels similar to an `@handle`. Public results use public metadata and are not personalized.
2. Ask for a constrained playlist preview, specifying topic, total-duration ceiling, maximum video duration and optional language. Public previews are stateless.
3. For recommendations or account analysis, sign in with Google when prompted. The default consent is OpenID identity plus YouTube read-only access.
4. To save a playlist, create a signed-in draft, open its approval page in your own browser session and review the ordered videos. Enable playlist writes through the browser consent action, create a fresh draft if asked, then explicitly approve that exact draft.
5. Read `playlist_status` after approval. A known partial failure can be explicitly resumed in the browser; an uncertain outcome requires manual inspection of YouTube and never auto-retries.

Each Google subject has separate tokens, refreshes, profile caches, drafts, quota and approvals. Another user's connection or disconnect does not select your account or authorize your writes. The operator does not provide a shared Google account.

| MCP access | Tools |
|---|---|
| Public | `similar_videos`, `similar_channels`, `video_summary`, `propose_playlist`, `playlist_from_request`, `video_to_playlist` |
| Sign-in required | `recommendations`, `engagement_analysis`, `create_playlist_draft`, `playlist_status`, `disconnect` |

The server uses the official MCP Python SDK 1.30 authorization provider/routes with dynamic client registration. Its MCP scope `youtube:read` is separate from Google scopes. Playlist write consent is `https://www.googleapis.com/auth/youtube` and is requested only through the browser action. Tools cannot approve writes.

## Local development

Use Python 3.12. Create a virtual environment, then install and run:

```bash
python -m pip install -r requirements.lock
python -m pip install --no-deps -e .
python -m ytintel
```

For a fresh local setup, use `.env.example` as a configuration reference and provide your own secrets. Do not overwrite an existing `.env` or data directory. `YT_LOCAL_BASE_URL` defaults to `http://localhost:8000`; set it explicitly when using another local port so the exact registered callback matches. The default local Google callback is `http://localhost:8000/oauth/callback`; a cloud client cannot reach your laptop's localhost.

## Validation and limits

```bash
python -m pytest --cov=ytintel --cov-report=term-missing --cov-fail-under=85
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

These are verification commands, not a claim that the current revision passed them. See [testing and traceability](docs/TESTING.md) for offline, real TCP, database and end-user checks.

Ranking uses local TF-IDF over bounded metadata candidates; it is a relevance heuristic, not a quality guarantee. Runtime is a strict ceiling, not an exact-fill promise. Unknown language is excluded when a language is requested. Samples are bounded and disclosed; watch history is unavailable. Dates in engagement comparisons use available activity dates, never substituted video publication dates.

The default project ledger permits at most 10,000 general units and 100 searches/day, with a 30% anonymous pool, IP limits and a 1,000-unit per-user daily allocation. Google or other users of the same project may impose a lower effective allowance. Render/Neon free plans have sleep and resource limits and do not provide an availability guarantee.

Read the [requirements interpretation](docs/REQUIREMENTS_INTERPRETATION.md), [architecture](docs/ARCHITECTURE.md), [security model](docs/SECURITY.md) and [video-to-playlist workflow](skills/video-to-playlist/SKILL.md). Older verification snapshots describe their recorded revision, not proof that this multi-account revision has passed live consent or writes.
