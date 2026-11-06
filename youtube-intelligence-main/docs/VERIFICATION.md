# Historical verification archive

**The results below describe earlier single-owner revisions. They are retained as historical evidence only and do not verify the current multi-account OAuth release.** Follow [TESTING.md](TESTING.md) for current commands, requirement traceability and end-user acceptance. In particular, old static-key, owner-key, URL-key and configured-secret handoff claims are superseded. No current passing count, live user consent, production Google verification or private playlist write is asserted by this archive.

---

# Verification — v1.2 Render + Neon

This version implements actual PostgreSQL persistence, not just a DATABASE_URL setting around a SQLite-only application. The supplied direct and pooled URLs are present only in the private `.env`. Runtime prefers the pooled URL and preserves its TLS/channel-binding options. A failed configured database never falls back to SQLite.

## Executed checks

- Full Python suite includes SQLite, domain/provider/service/API/MCP, cloud configuration and seven real PostgreSQL contract tests.
- Real Neon driver tests cover encrypted persistence across reopened engines, concurrent single-use records, concurrent draft claims, quota reservations across independent repository instances, refunds, rollback, expiry and literal-prefix deletion.
- Tests use randomly named `ytintel_test_*` schemas and remove their own schemas afterward. They do not read or change account data or unrelated tables.
- Chromium checks cover the separate-tab OAuth owner-key fix, actionable missing/incorrect owner-key errors, discovery, preview, cancel/confirm and replay-disabled UI.
- Cloud tests verify the configured remote MCP hostname, rejected foreign hostname, exact HTTPS callback derivation, fail-closed callback mismatch, Render port binding and correct HTTPS Origin handling through Render's proxy.
- A dedicated isolation regression prevents browser fixtures from using an exported production DATABASE_URL. Ordinary tests clear production application environment variables and use `_env_file=None` or synthetic configuration; explicit TEST_DATABASE_URL is retained only for PostgreSQL integration tests.
- Lint/format checks and wheel packaging checks passed. The wheel includes PostgreSQL dependencies, the cloud entry point and the owner interface; it contains no demo provider.
- Independent review found one Render proxy-header issue; it was fixed and regression-tested. Follow-up review found no important remaining blockers.

**Final result: 93 passed, 0 failed, 0 skipped; 92.14% Python coverage.** All seven PostgreSQL tests executed against real Neon. Machine-readable results are recorded in LIVE_NEON_VERIFICATION.json.

## Live transport qualification

This execution environment cannot directly resolve/connect to PostgreSQL TCP endpoints. The provided Neon credentials first passed an HTTPS SELECT 1. The full PostgreSQL tests then used **the actual psycopg/SQLAlchemy driver against real Neon**, carried through an ephemeral test-only TLS WebSocket bridge supported by Neon. This permitted real PostgreSQL transactions and concurrent sessions, rather than mocking the database. The bridge is not part of the delivered application, not a production fallback and not a deployment requirement.

Production uses standard psycopg PostgreSQL over TLS with the original supplied connection parameters. Direct Render-to-Neon TCP connectivity and the Render container itself were not executed here because this environment has no Render deployment/account session or Docker daemon. Docker/Blueprint configuration and the actual repository SQL have been verified separately.

## Google and account operations

The prior six public YouTube checks and localhost OAuth authorization-request readiness passed. Real Google owner sign-in must be completed on the deployed HTTPS owner page after registering that exact hosted callback. No remote YouTube playlist was created or modified during verification. Google client credentials alone do not grant user consent.

## Repeating checks

Ordinary tests:

```bash
pytest --cov=ytintel --cov-fail-under=85
ruff check src tests scripts
ruff format --check src tests scripts
```

Without TEST_DATABASE_URL, the seven PostgreSQL tests explicitly skip. GitHub CI includes a dedicated PostgreSQL 17 service and runs them without real user credentials. With an explicit test database URL, every PostgreSQL test creates a disposable schema. `scripts/check_database.py` provides an optional persistence probe for a configured database, also using a disposable schema. Do not enable verbose/debug logging with real credentials.

One Starlette/httpx TestClient deprecation warning remains with the tested pins. It does not prevent tests from passing.
