# Verification record — 2026-11-03 — Google-only v1.1

## Latest results

| Check | Result |
|---|---|
| Complete offline Python suite | **71 passed, 0 failed** |
| Python statement coverage | **91.73%** (798 statements; 66 unexercised), threshold 85% |
| Ruff lint / format | Passed; 30 Python files formatted |
| MCP system tests | FR1–FR5 through real TCP/Streamable HTTP using isolated test fixtures |
| Chromium owner interface | Discovery, preview, cancel confirmation, confirm synthetic test write, replay-disabled UI, mobile viewport; no JavaScript errors |
| Live Google public suite | **6 passed, 0 failed** |
| Live FR1 | 10 ranked similar-video candidates returned |
| Live FR2 | 10 ranked similar-channel candidates returned |
| Live FR5 preview | 24 real candidates selected; total 3,506 seconds ≤ 3,600 seconds, every video ≤ 1,200 seconds; status pending |
| Google OAuth redirect readiness | **Passed**: HTTP 200 sign-in page, no redirect error for `http://localhost:8000/oauth/callback` |
| Installed-package / live MCP smoke | Google-only wheel installed; bundled owner page, server entry point and real MCP client returned a pending Google-backed preview |
| Independent review | No important security or correctness findings in v1.1 |

The six-check public suite reserved a maximum of 10 general units and 3 searches; actual usage was 5 general units and 3 searches, with **zero playlist writes**. An initial direct metadata smoke and installed-MCP smoke were separate small read-only checks. OAuth endpoint readiness requests do not call the YouTube Data API.

Detailed safe machine-readable reports: LIVE_CHECKS.json, OAUTH_READINESS.json, INSTALLED_CHECK.json. Reports deliberately exclude credential values, authorization URLs with transient state, headers and raw upstream error bodies.

## Blocked pending owner sign-in, not test failures

- Live FR3 recommendations from the user's likes, playlists and subscriptions.
- Live FR4 analysis of the user's account data.
- Real YouTube playlist creation/insertion, which also requires explicit owner confirmation of the exact draft.

The user registered the fixed callback and Google accepted it. That checks the authorization request and redirect configuration, **not** completion of consent or validation of a token exchange using the client secret. OAuth client credentials and an API key cannot substitute for the user's consent grant. No redirect fallback or private/write API-key fallback was added.

## Environment and commands

Linux / Python 3.12.14. Commands:

```bash
python -m pytest --cov=ytintel --cov-report=term-missing --cov-fail-under=85 -q
ruff check src tests scripts
ruff format --check src tests scripts
python scripts/check_google.py
python scripts/check_oauth.py
```

Chromium smoke used Playwright 1.62.1 with a local Chromium 153 executable because this environment's managed-browser download was unavailable. The delivered browser script also supports normal Playwright-managed Chromium, as used in CI. Synthetic results are injected by `tests/browser_server.py`; there is no production mode that selects them.

One harmless Starlette/httpx TestClient deprecation warning remains; tests still pass. Coverage is a Python statement measure, not a guarantee of all real-world states.

Docker daemon execution, Windows execution and GitHub-hosted workflows were not executed in this environment. Their configuration is included, not claimed as remotely deployed. No remote account playlist was created or modified.

## Private handoff

The user explicitly requested that the ZIP include its configured `.env`. It contains the supplied project credentials and generated local application keys. `.gitignore` excludes it from Git; the archive itself must remain private. Source/tests/reports contain no actual credential values. The original OAuth JSON is not duplicated because its relevant fields have been imported into `.env`.
