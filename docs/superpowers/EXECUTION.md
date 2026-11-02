# Execution ledger

- Domain tests written first; initial missing-domain failure observed; 18 domain cases passed after implementation.
- Persistence/provider tests written first; initial missing-module failure observed; encryption, quota, OAuth and error cases passed after implementation.
- Application tests written first; missing-service/transport failures observed; REST auth and workflow suite passed after implementation.
- Real MCP TCP system tests added and passed for all five requirements.
- Expanded provider/security coverage, tested synthetic official response shapes and partial/uncertain write behavior.
- Independent read-only reviewer reproduced account-isolation and timezone issues. Regression tests failed before each fix, then passed.
- Shared account lock and reauthorization invalidation covered by concurrency regression.
- Final schema and malformed-credential regressions failed before fixes, then passed.
- Fresh pinned install, wheel build/install and installed-package MCP client completed successfully.
- Full final Python suite: 62 passed, 91.80% coverage. Ruff lint and format clean.
- Chromium full owner workflow passed, including cancel/approve/replay-disabled behavior and mobile viewport.
- ZIP delivery chosen by user; no existing git repository or branch to merge/push. All work is local and packaged; no account operations or hosting publication performed.

Ruling: Local single-owner hosting is the guaranteed free deployment path — external free tiers can change — cloud-only AI clients require separately secured reachable hosting.
Ruling: Human writes require a separate owner credential, outside MCP — metadata cannot authorize writes — users review in the browser even when an AI proposes the draft.
Ruling: Current official Google documentation uses separate search/general quota buckets — older brief assumptions differ — quotas remain configurable and user must check their Console.
Ruling: Unknown write outcomes block automatic retry — YouTube lacks application idempotency for these writes — user must inspect uncertain outcomes manually.
Ruling: Authorizations invalidate drafts/cache and never reuse an old authorization's refresh token — no verified account identity is available — scope escalation requires a fresh preview.

Deferred minors: none identified by the independent review. Remaining environment validation limitations are listed in docs/VERIFICATION.md.

## Google integration v1.1 — 2026-11-03

- User requested removing runtime demo behavior and integrating their supplied project credentials.
- User explicitly required private .env in the delivered ZIP; Git ignore rules still exclude it.
- Fixed callback http://localhost:8000/oauth/callback accepted by Google after user registered it. No URI fallback added.
- Public API-key traffic uses X-Goog-Api-Key, never URL parameters. Private data and writes require OAuth.
- New regressions first failed, then passed. Full Python suite: 71 passed, no failures. Chromium workflow passed with test-only fixtures. Six bounded live checks passed.
- Independent follow-up review found no important security/correctness issues. Actual owner sign-in/consent and remote playlist writes remain unexecuted.

## Render + Neon v1.2 — 2026-11-03

- Replaced SQLite-specific persistence/SQL quota coupling with SQLAlchemy repository operations supporting PostgreSQL and SQLite.
- Kept the encrypted record format and existing local table names; PostgreSQL uses schema ytintel and transaction-level advisory locks compatible with transaction pooling.
- Added real database URL secret fields, pooled preference and fail-closed configuration. No database/URI failure fallback.
- Added Render public-origin/callback validation, remote MCP hostname allowlist, runtime PORT handling and trusted proxy behavior.
- Kept separate-tab Google sign-in and owner credential isolation.
- Added Render Blueprint, exact deployment/Claude guide, PostgreSQL CI service and disposable-schema tests.
- Direct TCP to Neon was unavailable in this environment; a test-only TLS WebSocket transport allowed the actual psycopg driver and full PostgreSQL suite to execute against real Neon. Production DSNs/TLS settings were preserved; the test transport is not shipped.
- Independent review found the missing automatic Render proxy trust setting; fixed and verified with a reverse-proxy Origin regression. No remaining important review findings.
- Added browser-fixture isolation from exported database credentials and safe SecretStr representation for PostgreSQL test connection values.
- Final results: docs/LIVE_NEON_VERIFICATION.json. No live YouTube account writes, repository push or Render publication performed.
