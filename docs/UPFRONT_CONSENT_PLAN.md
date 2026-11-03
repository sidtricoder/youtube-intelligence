# Upfront Google permissions and user-controlled durations

We implement the user's explicit 2.1.0 change request on top of 2.0.1.

1. Request OpenID plus YouTube read and write scopes on the first connection/login.
   Google remains authoritative for actual granted scopes; retain read-only functionality
   and an explicit recovery option if write permission was declined or an older grant is used.
2. Explain on the MCP consent page that the server creates playlists after per-draft human approval.
   Preserve tenant isolation, browser sessions, CSRF, PKCE, precise redirects and no MCP write tool.
3. Remove all fixed total/per-video duration minima and maxima. Optional duration values are
   positive integer seconds; omitted/null means unbounded. Enforce only bounds the caller supplies.
   Natural-language parsing also permits omitted duration bounds. Keep quota and API sampling.
4. Test first: long courses, omitted limits, strict caller limits, initial write grant and two-account
   HTTP/MCP creation with no second Google consent. Retain legacy/declined-write recovery tests.
5. Run the complete offline suite, Ruff/format, Chromium and package build; update migration/setup
   docs and deliver the same complete archive without reading/changing .env or data/.
