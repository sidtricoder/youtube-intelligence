# Multi-account and lazy authentication implementation plan

Goal: isolate every connected Google account while retaining anonymous public discovery.
Architecture: retain FastAPI, official MCP SDK 1.30.0, SQLAlchemy Core, Fernet and the metadata
ranking/playlist workflow. Use SDK OAuth routes/provider contracts, a request-scoped HTTP
policy gate, opaque hashed MCP credentials, injected IdP and explicit per-request contexts.
Specification: the multi-tenant task and mixed-authentication addendum supplied with this archive.

## Audit of version 1.2

- `auth.py`: one `oauth:tokens` record, single account lock, reauthorization deletes all drafts/cache.
- `app.py`: owner/API bearer keys, shared role rate windows, owner-only writes; no MCP OAuth server.
- `config.py`: mandatory shared keys and optional `mcp_url_key`; hosted URL-key access.
- `mcp_server.py`: captures one global service/account; public previews persist shared drafts;
  errors return JSON inside HTTP 200; resources expose shared quota; descriptions say owner.
- `providers/google.py`: adds shared Google credentials to public metadata requests; shared cache
  can contain private data. Cache lookup precedes classification.
- `service.py`: unscoped `draft:<id>`, shared store/quota/approval authority.
- `quota.py`/`store.py`: global ledger only; no per-user or anonymous limits.
- `owner.html`: shared owner key, no browser identity/CSRF separation.
- `server.py`: Render trusts all forwarded headers by default; replace with configured trust.
- scripts, README and deployment/workflow docs teach shared keys and require deliberate updates.
- Existing token data will not be migrated. Existing `.env` and `data/` are not edited.

## Phases and verification

- [x] 1. Audit archive, run baseline, inspect SDK and authorization specification; write this plan.
  Baseline: 104 passed, seven optional Postgres tests skipped; no live credentials used.
- [x] 2. Tests first: tenant records, scoped store, immutable contexts, global/per-user/anonymous quota;
  inject provider and service context; public stateless preview. Run full pytest and ruff.
- [x] 3. Tests first: SDK authorization provider, DCR, exact redirect, S256, resource binding,
  hashed one-use codes/access/refresh rotation/replay, resource metadata and HTTP lazy-auth gate.
  Run full pytest and ruff. SDK has no CIMD server support; do not advertise CIMD.
- [x] 4. Tests first: verified Google OIDC adapter behind IdentityProvider, browser-bound login,
  incremental write consent, own-session approval, CSRF, typed confirmation and disconnect.
  Run full pytest and ruff.
- [x] 5. Two-account and anonymous real TCP/official-MCP-client E2E, hostile input and isolation,
  migrations, CI/Postgres matrix, deployment/security/requirements docs, independent review,
  full pytest/ruff/format and final archive validation. Record limitations honestly.

## Contracts and module ownership

`security/`: persistent identity/client/token/session repositories and SDK AuthServer.
`identity.py`: upstream IdentityProvider/GoogleIdentityProvider.
`context.py`, `tenancy.py`, `tenant_quota.py`: request identity, scoped persistence and budgets.
`credentials.py`: refresh/access/revocation per user, no global identity.
`policy.py`, `http_gate.py`: explicit complete tool/resource tier map and HTTP preflight.
`app.py`: composition only; `web.py` browser login/approval; `api.py` REST;
`oauth_routes.py` SDK routes; `http_boundary.py` request constraints and response security.
`mcp_server.py`: transport registration; obtains request context and invokes injected service.

Review focus: replay during concurrent refresh, private metadata poisoning public cache,
Google account switching during step-up, forged forwarded IP, ambiguous remote write outcomes.
Each needs an explicit negative test. Whole mixed batches are preflighted before any tool runs.


## Verification record

The baseline was 104 passing and seven optional PostgreSQL skips. Storage and authorization
changes deliberately made old shared-owner fixtures red; those fixtures were adapted while
preserving domain/provider/duration/constraint/write-progress coverage. Focused red/green checks
covered missing contexts, token rotation, ID-token validation, lazy HTTP policy, personal
exclusion, quota ownership, disconnect races, stale callbacks and authorization snapshots.
Full-suite and Ruff checks were run repeatedly during integration; transitional failures were
reported and resolved. Final evidence and exact commands are in FINAL_REPORT.md. No live
Google or production data was used. Source `.env` and `data/` were not edited.
