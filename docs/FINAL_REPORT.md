# Final multi-account/lazy-auth report — version 2.3.0

## Result and verification

The server now supports public stateless discovery and authenticated per-Google-subject account
operations at one `/mcp/` endpoint. No shared owner bearer, URL key, shared Google account or
MCP write-approval tool remains. Code, PostgreSQL/SQLite schema, offline tests and deployment
instructions are included in this archive.

Observed final checks (Python 3.12.14, MCP SDK 1.30.0):

| Check | Result |
|---|---|
| `pytest --cov=ytintel --cov-report=term --cov-fail-under=85` | **254 passed, 10 skipped, 0 failed; 91.83% statement coverage** |
| `ruff check src tests scripts` | Passed |
| `ruff format --check src tests scripts` | Passed (71 Python files) |
| Official MCP client over real TCP | Anonymous and two interleaved synthetic Google identities; FR-1 through FR-5, OAuth/PKCE, refresh replay, isolation and own-browser approvals passed |
| Chromium `node scripts/browser_smoke.cjs` | Own-session/CSRF, wrong phrase refusal, CREATE, replay 409, mobile, modal/Escape denial, cross-origin callback/token and Google consent passed |
| Wheel build and isolated installed import | Version 2.3.0 built; imported from site-packages; health and both discovery documents passed |
| SQLite migration/reference DDL | Idempotent migration tested; reference DDL applied twice below during archive validation |
| Secret-pattern/source scan | No configured API keys, database passwords or private-key material found; no `.env`/database in archive |
| Independent scoped security review | Credential races and stale authority fixed; 71 focused regressions passed for the latest scope/duration review; no remaining critical/important finding in final scoped recheck |

The optional ten PostgreSQL tests were skipped because TEST_DATABASE_URL was not supplied.
CI includes a disposable PostgreSQL 17 service and runs those tests there. This local run did
not verify Neon or PostgreSQL behavior with a live server. The suite reports one upstream
Starlette/httpx TestClient deprecation warning; it does not fail tests.

## What is covered

- Explicit complete public/protected allow-list; all tools are listed and protected tools say
  Requires sign-in. Real HTTP 401/403 challenges occur before MCP dispatch, including batch
  preflight. Invalid tokens cannot downgrade to anonymous. SDK BearerAuthBackend,
  ProviderTokenVerifier, OAuth handlers and access-token models are used.
- Strict DCR redirect URIs, S256, exact resource/audience binding, expiring single-use codes,
  hashed access/refresh credentials, rotating refresh tokens, replay-family revocation.
- Google RS256 OIDC verification (issuer/audience/expiry/nonce/sub), upfront read/write consent,
  upfront write scope with declined/legacy-grant recovery, browser session/CSRF/account matching and typed confirmation.
- Account-bound immutable context and persistent authorization generation. Concurrent refresh,
  old Google failures, stale browser callbacks, stale contexts, code issuance/redemption and
  session creation cannot restore revoked authority or revoke a newer grant.
- Separate encrypted user caches/drafts, API-key-only public metadata cache, own quota/status,
  anonymous aggregate pool, trusted-proxy IP policy, per-user rates and pre-call quota checks.
- Public previews store no user state; personal drafts exclude sampled liked/saved videos by
  default (`exclude_saved=False` opts out). No transcript/watch-history claim is made.
- Disconnect revokes Google access where reachable and deletes only that user's credentials,
  drafts and personal cache. If Google cannot be reached, local access is still revoked and
  the user is told how to remove the grant manually.

Existing valid ranking, input, duration, constraint, provider error/pagination, bounded profile,
quota and partial/uncertain-write regressions remain. Tests formerly asserting shared owner
keys, cache wiping or key URLs were deliberately rewritten to assert their removal, OAuth
account binding, no query-key elevation and browser authority separation; they were not
silently dropped. The former owner HTML and singleton OAuth implementation were removed.

## External limits and remaining risks

1. Live Google consent, Google production verification, actual YouTube writes, Render deployment
   and two real human Google accounts were not exercised. Upstream Google/YouTube components
   are fakes in CI; the local HTTP/MCP transport is real. Use DEPLOY_RENDER.md for the live
   end-user acceptance sequence and exact root `/oauth/callback` URI.
2. SDK 1.30 lacks an authorization-server CIMD primitive. Select Register Automatically (DCR)
   in Claude; do not select its published identity. A small public-client `/revoke` form shim
   works around a nullable-field SDK bug and retains SDK client authentication/ownership checks.
3. Run one instance/one worker. Token/quota transactions use database locks, but request rate
   windows are in process. Add distributed rate limiting before horizontal scaling. Configure
   exact trusted proxy networks; with no trusted proxy all callers behind one ingress share an
   IP bucket. Free hosting can sleep and has provider-specific resource limits.
4. The project quota is shared with all Google users and any external software using the same
   Google project. Reservations cannot observe external consumers. Testing mode is limited to
   100 users and refresh grants can expire after seven days; production verification is external.
5. Google offers no transactional idempotency for playlist writes. Ambiguous outcomes stop in
   uncertain state and must be inspected manually; only known partial failures can explicitly
   resume. Samples and TF-IDF ranking are bounded heuristics, not full history/quality guarantees.
6. Fernet keys and database backups must be protected and retained. Encryption does not protect
   against a compromised app host. This release does not automate key rotation, security-table
   retention cleanup, infrastructure backups or deployment; operators own those tasks.

No `.env` or `data/` from the source deployment was modified. The supplied source ZIP contained
only `.env.example`, which was updated to the new settings; no secret-bearing `.env` was added.
The output keeps the original top-level `youtube-intelligence-main/` layout.

## Files changed

### Modified

- `.env.example`
- `.github/workflows/live.yml`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DEPLOYMENT.md`
- `docs/DEPLOY_RENDER.md`
- `docs/GOOGLE_SETUP.md`
- `docs/SECURITY.md`
- `docs/TESTING.md`
- `docs/VERIFICATION.md`
- `pyproject.toml`
- `render.yaml`
- `scripts/bootstrap.py`
- `scripts/browser_smoke.cjs`
- `scripts/check_google.py`
- `scripts/check_oauth.py`
- `scripts/configure_google.py`
- `scripts/live_smoke.py`
- `scripts/mcp_client.py`
- `skills/video-to-playlist/SKILL.md`
- `src/ytintel/app.py`
- `src/ytintel/config.py`
- `src/ytintel/mcp_server.py`
- `src/ytintel/providers/google.py`
- `src/ytintel/server.py`
- `src/ytintel/service.py`
- `tests/browser_server.py`
- `tests/test_api.py`
- `tests/test_cloud.py`
- `tests/test_google_only.py`
- `tests/test_infrastructure.py`
- `tests/test_mcp.py`
- `tests/test_postgres.py`
- `tests/test_setup.py`
- `tests/test_url_key.py`
- `tests/test_workflows.py`

### Added

- `MANIFEST.sha256`
- `docs/FINAL_REPORT.md`
- `docs/MULTI_TENANT_PLAN.md`
- `docs/REQUIREMENTS_INTERPRETATION.md`
- `migrations/001_postgresql.sql`
- `migrations/001_sqlite.sql`
- `migrations/README.md`
- `src/ytintel/api.py`
- `src/ytintel/context.py`
- `src/ytintel/credentials.py`
- `src/ytintel/http_boundary.py`
- `src/ytintel/http_gate.py`
- `src/ytintel/identity.py`
- `src/ytintel/migrate.py`
- `src/ytintel/oauth_routes.py`
- `src/ytintel/policy.py`
- `src/ytintel/security/__init__.py`
- `src/ytintel/security/oauth.py`
- `src/ytintel/security/protocols.py`
- `src/ytintel/security/store.py`
- `src/ytintel/tenancy.py`
- `src/ytintel/tenant_quota.py`
- `src/ytintel/web.py`
- `tests/test_approval.py`
- `tests/test_credentials.py`
- `tests/test_http_gate.py`
- `tests/test_identity.py`
- `tests/test_migrations.py`
- `tests/test_mixed_mcp.py`
- `tests/test_oauth_security.py`
- `tests/test_scripts.py`
- `tests/test_tenancy.py`
- `tests/wire_helpers.py`

### Removed

- `src/ytintel/auth.py`
- `src/ytintel/owner.html`



## 2.0.1 corrective update

See UPGRADE_2_0_1.md for exact Render/Google settings and a fresh sign-in sequence. Added
`browser_policy.py` and policy regressions; updated `http_boundary.py`, `web.py`, the Windows
bootstrap assertion and cross-platform exclusive-create check. Expanded the Chromium regression
through a real form POST, registered cross-origin callback, token exchange and intercepted Google
write-consent page. Native Windows CI remains to be re-run by GitHub Actions. No `.env`/data changed.


## 2.1.0 permissions and duration update

User-directed changes supersede the old incremental-write/default-duration requirements. The
initial sign-in requests both read and write scopes, and the local client consent wording explains
that per-draft browser approval is still necessary. No fixed playlist/per-video duration floor or
ceiling remains; optional null/omitted bounds are unlimited, positive caller bounds are enforced.
Updated domain.py, identity.py, web.py, mcp_server.py, setup/script/MCP tests and current guides.
Added tests/test_duration_freedom.py, docs/UPFRONT_CONSENT_PLAN.md and docs/UPGRADE_2_1_0.md.
The two-account system test now verifies initial write grants and zero extra consent for normal
writes; declined/legacy-write recovery retains separate regression coverage. Reconnect once after
redeployment to grant the broader Google scope. No existing .env/data was read or edited.

## 2.2.0 consent dialog and browser design

Added `src/ytintel/ui.py`, `ui_theme.py`, `content_negotiation.py`, `tests/test_ui.py`, and `docs/UPGRADE_2_2_0.md`. Updated `web.py`, `http_boundary.py`, `browser_policy.py`, `security/oauth.py`, `app.py`, `pyproject.toml`, `tests/test_mcp.py`, `scripts/browser_smoke.cjs`, README, SECURITY, ARCHITECTURE and this report.

Consent is a native modal dialog within the OAuth browser tab, with Allow, Cancel and Escape handling. Denial consumes the transaction without issuing a code. The home, draft review, completion/partial/uncertain result and browser errors share responsive styling. All untrusted metadata remains escaped. Minimal dialog JavaScript uses a per-response CSP nonce; APIs retain JSON, including when HTML is explicitly unacceptable or JSON is preferred. No new infrastructure configuration or migration is needed.

The existing cross-account approval test now captures each user's CSRF while their own draft is pending; completed pages correctly show a result without another creation form. The cross-account rejection assertion remains. New tests first failed for missing dialog rendering, denial minting a code, unstyled browser errors and ignored Accept preferences, then passed after implementation.

Scoped review found no security regression. Its minor Accept-header negotiation finding was corrected with failing-first regressions. Native Windows, live Google/YouTube, Render and optional PostgreSQL were not exercised in this UI revision.

## 2.3.0 validation and Render diagnostics

Added `observability.py`, `mcp_observer.py`, `tests/test_observability.py`, `docs/OBSERVABILITY_PLAN.md` and `docs/UPGRADE_2_3_0.md`. Updated MCP tool registration/schema/instructions, domain language selection, composition root/version, HTTP boundary/gate, quota, Google provider, credentials, OAuth/browser flow, playlist service, duration tests, README, Render deployment and security docs. No production environment or data files were read or changed.

The supplied generic invalid_input response identifies the old ValueError handler but cannot establish which original field failed. The patch exposes safe failing field names and actionable format guidance with a request ID. Schemas advertise 2–200 character topics, language codes and optional positive whole-second bounds without upper duration caps. A separately reproduced bug now permits primary-language requests to match regional metadata (en to en-US), preserving strict requested regions and excluding unknown metadata languages.

JSON stdout events cover request/protocol/tool/auth/quota/cache/provider/discovery/draft/approval/write stages. They include timing and aggregate counts, never identities, raw arguments, metadata, URLs/queries, headers, dynamic IDs, credentials, bodies or exception text. X-Request-ID is server-generated. Existing indistinguishable draft-not-found responses remain unchanged; their correlation uses the header. SDK protocol chatter is suppressed, Uvicorn access logs remain off. Unexpected HTTP errors and broken/completed transport fallbacks cannot emit chained raw exception dumps.

Ten new observability cases and the regional-language regression were added. Red runs observed absent correlation/events, opaque language errors, SDK type rejection without safe diagnostics, missing schema guidance, exact-only language mismatch, and unsafe pre/post-response exception behavior. All now pass. No pre-existing isolation test was removed or weakened. Scoped independent review found a post-start exception-chain risk; failing regressions reproduced it and the fix passed final recheck with no remaining finding.

Final local suite: 254 passed, 10 optional PostgreSQL tests skipped, 91.83% coverage. Ruff check and formatting pass for 71 Python files. Chromium consent/approval/mobile suite passes. Installed 2.3.0 wheel source bytes, imports, HTTP health, OAuth discovery and correlation headers match. All upstream account and YouTube operations remain synthetic in verification; the original deployed failing request cannot be replayed without its actual tool arguments. Render deployment and real Google/YouTube behavior were not exercised.
