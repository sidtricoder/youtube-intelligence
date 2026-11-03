# Testing and requirement traceability

Ordinary tests run offline with synthetic identities, metadata and credentials. CI and test fixtures never call live Google; only explicitly supplied optional `TEST_DATABASE_URL` enables live disposable PostgreSQL tests. Google adapter tests use `httpx.MockTransport` with official-response-shaped fixtures; they do not establish live consent or playlist access. Keep valid domain, workflow and provider regressions; adapt obsolete fixed-owner/static-URL-key expectations to subject-bound authorization rather than deleting coverage.

| Requirement | Implementation boundary | Required evidence |
|---|---|---|
| FR1 similar videos | domain rank, service, Google adapter, public HTTP policy | scoring/IDs, provider normalization, anonymous real-TCP MCP |
| FR2 similar channels | lookup/rank, service, adapter, public policy | handle/details, workflow, anonymous real-TCP MCP |
| FR3 recommendations | user context, scoped credentials/cache, service/provider | bounded profile/exclusion, A/B account separation, protected real TCP |
| FR4 engagement | domain dates/statistics, user service/provider | sample/UTC/period cases, subject isolation, protected real TCP |
| FR5 playlist | public preview, protected draft, tenant store, browser approval | constraints, ownership/CSRF, atomic claim/replay, partial/uncertain writes |
| Video-to-playlist skill | packaged skill, prompt/resource, workflow | metadata-only summary, stateless public preview, own-session approval |
| TQ1 unit | domain, security policy/clock/store, quotas | deterministic validation, expiry, scope/audience, reservations |
| TQ2 integration | Google adapter, identity/refresh, encrypted storage | response/pagination/write shapes, signature/nonce, wrong-sub refresh rejection |
| TQ3 MCP system | real TCP + uvicorn + official SDK client | `tests/test_mixed_mcp.py`: public/protected tools, metadata/challenge, registration/token flow |
| TQ4 negative | domain/provider, security HTTP gate/browser | invalid input/token, cross-user IDs, insufficient scope, revocation, redirect/CSRF/injection |
| TQ5 isolated live | opt-in read-only smoke | no ordinary CI Google access; minimal calls; no credentials/personal artifacts |
| TQ6 quota | project + tenant/anonymous quota ledger | preflight no-call rejection, attempted calls, refunds, rollover, concurrency/IP/search cap |

## Offline verification

```bash
python -m pytest --cov=ytintel --cov-report=term-missing --cov-fail-under=85
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

These commands define the checks; their presence is not evidence of a passing run. Execution summaries must state revision, command, observed result and skips. Historical VERIFICATION.md/JSON snapshots apply only to the revision they measured. A coverage percentage measures executed Python statements, not successful Google production verification.

Real-TCP tests allocate a loopback port and stop their server. `tests/test_mixed_mcp.py` must verify anonymous initialization, lists, ping/notifications and public calls; protected challenge with root HTTPS metadata and `youtube:read`; invalid token rejection even on public calls; mixed-batch/unknown-operation policy; strict dynamic registration; PKCE/state/nonce; token audience/scope/expiry/revocation; A/B isolation; and no MCP approval authority. Tests must not satisfy these checks by bypassing the actual HTTP gate.

`test_mixed_mcp.py::test_public_client_revocation_over_http` exercises the narrow SDK 1.30 public-client revocation compatibility shim: an omitted nullable `client_secret` receives only a missing empty form field before the original SDK handler performs authentication and revocation.

`test_credentials.py::test_refresh_cannot_restore_disconnected_or_replaced_grant`, `test_credentials.py::test_stale_google_error_does_not_revoke_new_login`, `test_oauth_security.py::test_refresh_cannot_restore_revoked_or_replaced_google_grant` and `test_tenancy.py::test_stale_scoped_store_refuses_operations_after_revocation` verify persistent generation guards around fresh login, revoke, read/write and refresh. In-flight results must not restore disconnected credentials or overwrite a newer grant.

Browser regressions use synthetic dependency injection and temporary databases. `test_identity.py`, `test_oauth_security.py`, `test_tenancy.py`, `test_http_gate.py` and `test_approval.py` cover the identity, provider/store, isolation, policy and browser boundaries. Existing browser/API assertions that require a shared owner key need adaptation to signed-in sessions and CSRF. Domain/provider/workflow coverage remains applicable. Real account tokens, `.env` and existing data are never test input.

For opt-in PostgreSQL tests, supply `TEST_DATABASE_URL` for a dedicated test endpoint. Tests create randomized disposable schemas and drop only those schemas. A skipped PostgreSQL test is not PostgreSQL verification. Never point destructive test setup at a production schema.

## End-user acceptance

1. Open the deployed root page anonymously; ask the MCP connector for similar videos and a constrained preview. Confirm public results are not personalized and the preview is not an approved persistent draft.
2. Ask for personal recommendations. Complete sign-in through **Sign In When Needed** with Google account A. Confirm default consent is OpenID plus YouTube read-only.
3. In a separate browser/client session sign in as B. Verify B's recommendations and drafts cannot reveal A's data. Try an A draft ID from B; read, approve, resume and status must fail without revealing the draft. Disconnect B and confirm A still works.
4. As A, create a protected draft. In A's browser, explicitly enable playlist writes, complete Google's broader consent, then create a fresh draft if consent invalidated it. Review ordered videos and constraints before approving the exact draft. Confirm only A's private playlist changes.
5. Read status through A's MCP session, verify inserted count and the YouTube link, and confirm replay cannot create a duplicate. Do not induce ambiguous live writes merely to test retries; offline tests retain partial/uncertain behavior checks, including `test_partial_known_failure_resumes_without_duplicate_create` and `test_ambiguous_write_stops_retry`. Known partial recovery requires exact `RESUME` browser confirmation; unknown outcomes never auto-retry.
6. Restart/redeploy and verify encrypted persistence and account isolation. Verify revocation/expiry produces reauthorization, not fallback to a shared account.

## Google and hosting boundaries

For an external Google app in Testing, plan around the 100-test-user limit and seven-day refresh-token expiry for this non-basic YouTube scope flow. Reauthorization is expected when a Testing grant expires. Moving to production requires the applicable Google verification/review and consent-screen configuration; offline tests or a working authorization URL do not prove approval. Verify current project quotas and production status in Google Cloud before wider use.

Opt-in live smoke should use a separately consented read-only test account and secret environment, perform a minimal documented budget (for example one `videos.list`, no searches/writes), and never upload personal payloads. Actual live sign-in and writes must be reported only after an end user observes them. Render cold starts, Neon availability and third-party client behavior require deployment acceptance in addition to local tests.
