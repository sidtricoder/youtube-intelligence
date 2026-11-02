# Testing and requirement traceability

All ordinary tests run offline against synthetic data. There are no user identities, tokens or history captured from a real account. The Google adapter is exercised with `httpx.MockTransport` and synthetic official-response-shaped JSON; these are not claimed to be recordings from a real account.

| Requirement | Implementation | Evidence |
|---|---|---|
| FR1 similar videos | service.similar_videos + domain.rank | domain scoring/IDs; workflow test; real MCP wire test |
| FR2 similar channels | channel lookup + TF-IDF | Google handle/details integration; workflow; real MCP wire |
| FR3 recommendations | liked/playlist/subscription seeds | sampled profile integration; workflow; real MCP wire |
| FR4 analytics | bounded sample, durations, channels, category IDs, trends, periods | activity/date unit tests; timezone regression; workflow; real MCP wire |
| FR5 playlist | immutable preview + independent owner approval + official inserts | constraints; REST owner authorization; replay/partial/uncertain cases; real MCP wire + owner REST |
| video-to-playlist skill | packaged SKILL.md, prompt, resource, workflow tool | MCP workflow test; summary basis; no writes before approval |
| TQ1 unit tests | domain, storage, quota, OAuth, service, settings | test_domain.py, test_infrastructure.py, test_workflows.py, test_setup.py |
| TQ2 integration | Google normalization, pagination, official write shapes; OAuth refresh | MockTransport integration tests |
| TQ3 MCP system tests | actual TCP/uvicorn + official MCP SDK client | test_mcp.py covers FR1–FR5, resources, prompts, negatives |
| TQ4 negative cases | malformed IDs, missing/private/deleted video, missing tags, quota, signup, expired tokens, rate limit | parametrized domain/provider/API tests |
| TQ5 isolated live tests | weekly opt-in read-only smoke; ordinary CI never accesses Google | .github/workflows/ci.yml and live.yml; scripts/live_smoke.py |
| TQ6 quota | preflight reservation, attempted-call charges, refund, rollover, concurrent access | reservation/unit/network-failure/concurrency tests; service provider-not-called guard |
| Security | scope escalation, encrypted values, expiring single-use browser-bound state, separate owner key, metadata injection | infrastructure/API tests; account-swap + serialized-reconnect regressions |
| Browser system | discovery, preview, cancel confirmation, confirm, disabled replay, mobile view | scripts/browser_smoke.cjs (Chromium) |

## Commands

Install `requirements.lock` and the project as in README, then run:

```bash
python -m pytest --cov=ytintel --cov-report=term-missing --cov-fail-under=85
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
```

System tests allocate an ephemeral local TCP port and cleanly stop their uvicorn server. No YouTube calls are made by ordinary pytest. Browser smoke uses fixed port 8000, a temporary database, synthetic keys and explicit test-only dependency injection. It starts and stops the server itself. Free port 8000 first. Node/Chromium are dev-only dependencies.

## Live smoke

The optional scheduled workflow runs once weekly and only when repository secrets `LIVE_CLIENT_ID`, `LIVE_CLIENT_SECRET`, `LIVE_REFRESH_TOKEN` are present. Use a separately consented **read-only** refresh token, stored in private GitHub Actions secrets. No live tokens or account data are printed or uploaded as artifacts. External Testing grants may need reauthorization after seven days. Manual invocation is also possible; the budget is per invocation, not a global cap across repeated manual runs.

It creates an ephemeral encrypted database, refreshes OAuth if needed and performs at most one `videos.list` call: **1 general quota unit, 0 searches, 0 writes**. It does not create or approve playlists. If a token has expired, that run fails safely rather than silently bypassing authentication. Default GitHub Actions quotas/pricing depend on your account/repository; offline local tests are the guaranteed no-hosting-charge path.

## Verification boundaries

Recorded execution results are in VERIFICATION.md. Offline provider tests establish adapter behavior under representative responses, not successful consent/write access to your Google account. No live Google authorization or real playlist write was performed during generation. Docker commands and the Windows CI matrix are supplied for your environment; their actual execution must be observed there. The browser smoke is distinct from the Python coverage percentage, which measures executable Python statements rather than all possible states or real-world quality.

A harmless Starlette deprecation warning about its current httpx TestClient integration may appear with the tested package versions; the test suite still executes. The MCP client uses the current nondeprecated Streamable HTTP interface for the pinned v1 SDK. Upgrading to the newer MCP v2 API is a separate compatibility change, not an automatic dependency upgrade.

Google-only v1.1 regressions are in `tests/test_google_only.py`: runtime provider selection, key-only public reads, no private/write fallback, expired-token behavior, redacted configuration errors and JSON credential import. The current live public result is in LIVE_CHECKS.json; Google accepted the registered redirect and displayed sign-in (OAUTH_READINESS.json). Actual user consent and private account writes remain unexecuted.
