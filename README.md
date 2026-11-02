# YouTube Intelligence — Google-connected FastAPI + MCP

Version **1.1.0**. The application uses the **official YouTube Data API v3 exclusively**. There is no demo provider, runtime demo mode, fabricated application result or redirect fallback. Synthetic data exists only in isolated automated tests.

This private ZIP includes a configured `.env` for Google project **dark-smile**, as requested. `.gitignore` excludes `.env`, client-secret JSON files and local data from Git. Your Google API key is `YT_YOUTUBE_API_KEY`; `YT_API_KEY` is a separate generated credential for your own FastAPI/MCP server. Never confuse the two.

## Start the application

Install Python **3.12** and open a terminal inside the extracted `youtube-intelligence` folder, beside this README.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m ytintel
```

### Linux / macOS

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .
.venv/bin/python -m ytintel
```

The `.env` in your private ZIP is already configured. **Do not replace it with `.env.example` or regenerate its encryption key.** Bootstrap only creates a new blank configuration if no `.env` exists; it never overwrites one.

Open **http://localhost:8000**. The exact Google OAuth authorized redirect URI is:

**`http://localhost:8000/oauth/callback`**

Use `localhost` consistently, not `127.0.0.1`, during the browser sign-in flow. No alternative callback is selected automatically.

## Use it

1. Open `.env` privately and copy **`YT_OWNER_KEY`** into the owner access field. The browser keeps it in tab memory only.
2. Public similar-video/channel discovery and constrained previews use the configured Google API key. Try a real video URL such as `https://www.youtube.com/watch?v=rfscVS0vtbw`, or channel `@freecodecamp`.
3. For personal recommendations and engagement analysis, click **Connect Google (read)** and complete Google's sign-in/consent screen.
4. For playlist creation, click **Enable playlist writes** and approve the stronger Google consent. Then build/review a fresh preview and click **Create private playlist**. Scope authorization does not approve a particular playlist; each exact draft needs confirmation.
5. Drafts expire in 30 minutes. Known rejected writes can be explicitly resumed; uncertain outcomes never auto-retry. Stop the server with Ctrl+C. Encrypted SQLite persists across restarts.

Successful Google reconnection or scope escalation clears cached data and existing drafts, preventing one account's preview from being written into another. Connect with the desired scope before proposing your final playlist.

## Automated checks

Run in your virtual environment:

```bash
python -m pytest --cov=ytintel --cov-report=term-missing --cov-fail-under=85
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

The current verification run: **71 tests passed**, zero failures, **91.73% Python coverage**. Ordinary tests are offline and never use your credentials. MCP system tests exercise FR1–FR5 over real loopback HTTP with test-only injected fixtures. See [testing](docs/TESTING.md).

Live public checks, using your configured Google project (maximum 10 general units and 3 searches per invocation, no writes):

```bash
python scripts/check_google.py
```

Check Google's authorization endpoint and the exact callback without signing in:

```bash
python scripts/check_oauth.py
```

This checks redirect readiness; it does not grant consent. Live personal recommendations, private analytics and account writes cannot be verified until you complete sign-in. Current results and boundaries are in [verification](docs/VERIFICATION.md), [live checks](docs/LIVE_CHECKS.json) and [OAuth readiness](docs/OAUTH_READINESS.json).

Optional Chromium UI test (Node.js 22+):

```bash
npm ci
npx playwright install chromium
node scripts/browser_smoke.cjs
```

It starts a test-only server using fixtures under `tests/`, not a production mode. Free port 8000 first. Set `YTINTEL_PYTHON` to your virtual-environment Python if `python` on PATH refers elsewhere. For an existing local Chromium, `YTINTEL_CHROMIUM_PATH` can select that executable. The application itself requires no Node.js. Standard CI installs Chromium automatically.

## MCP without a paid AI subscription

Keep the real server running and run in a second terminal:

```bash
python scripts/mcp_client.py
```

This uses the official MCP client to list tools and request a real Google-backed playlist preview. It sends only your app's API credential and never approves writes. It uses Google quota; it is not a synthetic demonstration.

For an existing local AI client supporting Streamable HTTP and custom headers:

- URL: **`http://localhost:8000/mcp/`** (trailing slash).
- Header: `Authorization: Bearer <YT_API_KEY value from .env>`.
- Never give the AI client `YT_OWNER_KEY`, the Google client secret or the encryption key.

Typical client configuration (actual schemas vary):

```json
{
  "mcpServers": {
    "youtube-intelligence": {
      "url": "http://localhost:8000/mcp/",
      "headers": {"Authorization": "Bearer YOUR_LOCAL_APP_API_KEY"}
    }
  }
}
```

Replace the example value in private client configuration. A cloud-only AI client cannot reach your laptop's localhost. The included Python MCP client and the browser interface need no paid AI service. The server uses private bearer credentials, not a public multi-user MCP OAuth authorization server.

| MCP tool | Purpose |
|---|---|
| `similar_videos(video)` | FR1, rank public candidates by metadata similarity |
| `similar_channels(channel)` | FR2, channel ID/@handle/URL → similar channels |
| `recommendations()` | FR3, bounded samples of liked videos, subscriptions and playlists; OAuth required |
| `engagement_analysis(start?, end?, previous_start?)` | FR4, metadata/activity statistics and optional period comparisons; OAuth required |
| `propose_playlist(topic, total_seconds, max_seconds, language?)` | FR5, strict constrained immutable preview |
| `playlist_from_request(request)` | Documented English request → preview |
| `video_to_playlist(video, topic, total_seconds, max_seconds, language?)` | Metadata summary → similar candidates → preview and analysis |
| `playlist_status(draft_id)` | Read progress after independent owner confirmation |

Resources: `ytintel://quota`, `ytintel://capabilities`, `ytintel://skills/video-to-playlist`. Prompt: `video_to_playlist_workflow`. Product skill: [skills/video-to-playlist/SKILL.md](skills/video-to-playlist/SKILL.md).

Built-in numeric English request example:

> Build a 2 hour playlist on Python, no video over 20 minutes, language en

For other phrasing, an existing MCP AI client translates the request into structured arguments; the server never silently invents constraints. The browser form needs no LLM.

## Architecture and limits

Modular SOLID design: immutable pure domain models/algorithms, provider protocol, Google adapter, OAuth service, encrypted SQLite repository, quota reservations, application orchestration, thin FastAPI/MCP transports. No paid embeddings or paid LLM dependency; TF-IDF runs locally.

- Similarity is a metadata heuristic, not a verified quality ranking or an understanding of the full video.
- Summaries use title/description metadata only, never pretend transcripts.
- Total runtime is a strict upper bound, not an exact-fill guarantee. Greedy relevance selection may leave time unused.
- Requested language requires an exact declared audio/default metadata match; unknown values are excluded. A null language imposes no language filter.
- Discovery is bounded to 50 video candidates or 25 channels. Profile sample caps: 100 likes, 100 subscriptions, 10 playlists × 100 items; truncation is disclosed.
- No watch history. Playlist-add dates drive dated engagement comparisons. Liked dates are unavailable, publication dates are not substituted. Subscription trends are separate. Statistics use UTC, with explicit offsets converted correctly.
- One local owner, one Google account and one running application process. All app instances must share a database for quota accounting. The ledger cannot see unrelated software using the same Google project.
- No private-data or write fallback to API-key-only access. A connected account with expired/revoked OAuth must reauthorize.
- Google Testing refresh tokens can expire; sign in again when requested. Real writes require a YouTube channel and owner confirmation.

REST docs: **http://localhost:8000/docs**. Click **Authorize** and enter the relevant API/owner key without `Bearer`; middleware enforces roles. See [architecture/API](docs/ARCHITECTURE.md), [Google setup](docs/GOOGLE_SETUP.md), [free deployment](docs/DEPLOYMENT.md) and [security](docs/SECURITY.md).

The ZIP deliberately contains your private `.env`; Git ignores do not encrypt files or remove secrets from an archive. Keep this configured ZIP private. Project code is MIT licensed; it is not affiliated with Google or YouTube.
