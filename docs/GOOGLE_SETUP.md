# Official YouTube setup, without paid services

The private ZIP is configured with the supplied Google client and API key. All application results come from the official API. The project uses its default quota. No paid LLM or billing-enabled compute service is needed for local operation.

1. Open https://console.cloud.google.com/ and create or choose **one** project. Enable **YouTube Data API v3** in APIs & Services → Library. Do not create extra projects to evade quota.
2. Configure Google Auth Platform / OAuth consent (UI labels may vary): app name, support email and developer contact. For an external app in Testing, add your Google account as a test user.
3. Create an OAuth client of type **Web application**. Add exactly `http://localhost:8000/oauth/callback` as an authorized redirect URI. Scheme, hostname, port and path must match. Use `localhost` consistently in the browser, rather than switching to `127.0.0.1` mid-flow.
4. Open your generated `.env` and set:

   ```dotenv
   YT_GOOGLE_CLIENT_ID=your-client-id
   YT_GOOGLE_CLIENT_SECRET=your-client-secret
   YT_REDIRECT_URI=http://localhost:8000/oauth/callback
   ```

   Preserve the generated API key, owner key and encryption key. Values above describe where to place your own credentials; no real credentials are included in this project.
The callback is fixed to `http://localhost:8000/oauth/callback`; no alternate URI is selected. Public metadata uses `YT_YOUTUBE_API_KEY`, sent in the `X-Goog-Api-Key` header. Private data and all writes require OAuth.

5. Restart the server. In http://localhost:8000, enter your owner key and click **Connect Google (read)**. Sign in using the listed test account and review Google's consent screen. OAuth state is single-use, browser-bound and expires after ten minutes. Complete it in the same browser.
6. Read features use only `youtube.readonly`. When you want playlist creation, click **Enable playlist writes**, review the stronger `youtube.force-ssl` consent and authorize it. This is an available playlist-write scope, not a playlist-only permission: Google's grant is broader. The application implements only private playlist creation and item insertion. Enabling a scope does not approve any playlist; each draft still needs owner confirmation.
7. Ensure your Google account has an actual **YouTube channel** (create it on YouTube if needed). An account without a channel can read some data but playlist writes may produce `channel_required` (`youtubeSignupRequired`).
8. Try a real public educational video URL, then generate/review a draft. Click **Create private playlist** only when ready. Check YouTube → You / Playlists for the result. Use real YouTube URLs in the application; repeated-letter IDs exist only in offline test fixtures.

OAuth access tokens refresh automatically when near expiry. External Testing refresh tokens normally expire after seven days for these scopes. Revoked/expired refresh tokens return `reauthorization_required`: connect again. Public distribution may require Google's OAuth verification and policy review; this project does not bypass that process.

**Disconnect & erase local data** revokes the token with Google, then clears local tokens, cached metadata and drafts. It does not delete existing YouTube playlists. If the revocation service is unavailable, retry; access can also be revoked at https://myaccount.google.com/permissions. Backups remain your responsibility.

## Quota

Current official documentation (checked 2026-11-02) assigns `search.list` a separate **100 calls/day** bucket at one unit per search call, and **10,000 general units/day** for other endpoints. This differs from older teaching materials that charge search 100 general units. Reads normally cost 1 general unit; playlist and playlist-item insertions cost 50 each. Reset is midnight **America/Los_Angeles**, including DST.

The application reserves each entire workflow's upper bound before calling the provider, tracks actual attempted API calls including failures, and releases unused capacity. Default bounded reservations:

| Workflow | General units reserved | Search calls reserved |
|---|---:|---:|
| Similar videos or channels | 2 | 1 |
| Playlist proposal / seed workflow | 2 | 1 |
| Profile analytics | 45 | 0 |
| Recommendations | 50 | 3 |
| Write n remaining items, new playlist | 50 × (n + 1) | 0 |
| Resume existing playlist with n remaining items | 50 × n | 0 |

Metadata cache TTL is five minutes, encrypted and single-account. Cache hits make no API call. Reservations intentionally overestimate and can reject a workflow that would happen to hit cache; this favors predictable quota safety. A crash conservatively leaves its reserved quota counted until the daily reset. Set `YT_UNITS_PER_DAY` and `YT_SEARCHES_PER_DAY` to lower allocations if the Google project is also used elsewhere. The local ledger cannot inspect project consumption outside this app; compare it with Google Cloud Console. No automatic quota-error retries.

Check your own project's actual quotas before live use; Google may change defaults or grant different limits. References:

- https://developers.google.com/youtube/data/getting-started
- https://developers.google.com/youtube/data/determine_quota_cost
- https://developers.google.com/youtube/data/reference/rest/v3/search/list
- https://developers.google.com/identity/protocols/oauth2/web-server
- https://developers.google.com/youtube/data/guides/auth/server-side-web-apps

Successful Google reconnection or scope escalation clears cached data and existing drafts to prevent cross-account writes. Enable write consent before proposing the playlist, or create a fresh preview after authorization. New authorizations never inherit another authorization's refresh token. Workflows and account changes are serialized within the single application process.
