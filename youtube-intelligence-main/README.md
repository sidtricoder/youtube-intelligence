# YouTube Intelligence — multi-account FastAPI + MCP

Discover related YouTube videos and channels publicly, then sign in with your own Google account for recommendations, engagement analysis and reviewed private playlists. The production provider uses the official YouTube Data API v3. Summaries use title/description metadata, not transcripts or claims of watching a video.

Version 2.6.0 adds `max_videos` and `min_seconds` playlist limits that are verified before a draft is shown and again before any YouTube write, and the server now rejects unknown tool parameters instead of ignoring them. Check `/health` reports `2.6.0` after deploying; a client that cached an older tool list should reconnect the connector. Version 2.5.0 added AI-mediated confirmation (confirm_playlist_draft after user agreement in chat), modern button-based browser fallback, and leaves quota/rate enforcement entirely to Google. Follow [the 2.4.0 upgrade and reconnect steps](docs/UPGRADE_2_4_0.md) then update your client.

Start with [Render + Neon deployment](docs/DEPLOY_RENDER.md). The hosted MCP URL is **`https://<host>/mcp/`**. In Claude choose **Streamable HTTP**, **Sign In Now** and **Register Automatically**. Use the plain URL with its trailing slash; no static bearer key, query key or custom header is needed. Choose Sign In Now to grant permissions during setup. Public tools still support anonymous access; Sign In When Needed defers this same sign-in until protected work.

The handoff contains `.env.example`, never a configured `.env`. Keep secrets in Render Environment or a private local environment; do not commit or attach them. Preserve an existing encryption key for existing records.

## Use it

1. Ask for videos similar to a YouTube URL or channels similar to an `@handle`. Public results use public metadata and are not personalized.
2. Ask for a constrained playlist preview, specifying topic and any optional length, count and language preferences. Public previews are stateless. The AI passes these as optional tool parameters (omit any for no bound):

   | Parameter | Meaning |
   |---|---|
   | `total_seconds` | Maximum combined playlist length, e.g. `7200` for 2 hours |
   | `max_seconds` | Maximum length of any single video, e.g. `1200` for 20 minutes |
   | `min_seconds` | Minimum length of every video, e.g. `300` for 5 minutes (cannot exceed `max_seconds`) |
   | `max_videos` | Maximum number of videos, 1 to 50 (one YouTube search page of candidates) |
   | `language` | Language code such as `en` |

   The most relevant matching videos are kept. If fewer than `max_videos` match, the result includes `video_count_note`. Every proposal and draft also returns `constraint_check` (count, shortest and longest video, `all_satisfied`).
3. For recommendations or account analysis, sign in with Google during connector setup (or when first prompted by a client using lazy sign-in). Initial Google consent requests OpenID identity plus YouTube read and write access.
4. To save a playlist, create a signed-in draft. Your AI shows the exact ordered videos in the conversation. After you agree, the AI calls confirm_playlist_draft. An optional modern browser page with a confirm button is also available. Initial sign-in requests playlist-write permission.
5. Read `playlist_status` after approval. A known partial failure can be explicitly resumed; an uncertain outcome requires manual inspection of YouTube and never auto-retries.

Each Google subject has separate tokens, refreshes, profile caches, drafts, quota and approvals. Another user's connection or disconnect does not select your account or authorize your writes. The operator does not provide a shared Google account.

| MCP access | Tools |
|---|---|
| Public | `similar_videos`, `similar_channels`, `video_summary`, `propose_playlist`, `playlist_from_request`, `video_to_playlist` |
| Sign-in required | `recommendations`, `engagement_analysis`, `create_playlist_draft`, `playlist_status`, `disconnect` |

The server uses the official MCP Python SDK 1.30 authorization provider/routes with dynamic client registration. Its MCP scope `youtube:read` is separate from Google scopes. Playlist write consent is `https://www.googleapis.com/auth/youtube` and is requested during initial Google sign-in. Tools cannot approve writes.

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

Google alone enforces quota and rate limits. App-level budgets, search caps and request-rate limits have been removed; legacy settings are ignored. Usage counters are informational and account-scoped. Render/Neon free plans still have their own resource and availability limits.


Read the [requirements interpretation](docs/REQUIREMENTS_INTERPRETATION.md), [architecture](docs/ARCHITECTURE.md), [security model](docs/SECURITY.md) and [video-to-playlist workflow](skills/video-to-playlist/SKILL.md). Older verification snapshots describe their recorded revision, not proof that this multi-account revision has passed live consent or writes.
