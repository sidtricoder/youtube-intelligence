# Final multi-account/lazy-auth report — version 2.0.1

## Result and verification

The server now supports public stateless discovery and authenticated per-Google-subject account
operations at one `/mcp/` endpoint. No shared owner bearer, URL key, shared Google account or
MCP write-approval tool remains. Code, PostgreSQL/SQLite schema, offline tests and deployment
instructions are included in this archive.

Observed final checks (Python 3.12.14, MCP SDK 1.30.0):

| Check | Result |
|---|---|
| `pytest --cov=ytintel --cov-report=term --cov-fail-under=85` | **220 passed, 10 skipped, 0 failed; 91.22% statement coverage** |
| `ruff check src tests scripts` | Passed |
| `ruff format --check src tests scripts` | Passed (63 Python files) |
| Official MCP client over real TCP | Anonymous and two interleaved synthetic Google identities; FR-1 through FR-5, OAuth/PKCE, refresh replay, isolation and own-browser approvals passed |
| Chromium `node scripts/browser_smoke.cjs` | Own-session/CSRF form, wrong phrase refusal, typed CREATE, completed playlist, replay 409 and mobile page passed |
| Wheel build and isolated installed import | Version 2.0.1 built; imported from site-packages; health and both discovery documents passed |
| SQLite migration/reference DDL | Idempotent migration tested; reference DDL applied twice below during archive validation |
| Secret-pattern/source scan | No configured API keys, database passwords or private-key material found; no `.env`/database in archive |
| Independent scoped security review | Credential races and stale authority fixed; 50 focused regressions passed; no remaining critical/important finding in final scoped recheck |

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
- Google RS256 OIDC verification (issuer/audience/expiry/nonce/sub), read-only default consent,
  incremental write scope, browser session/CSRF/account matching and typed confirmation.
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
