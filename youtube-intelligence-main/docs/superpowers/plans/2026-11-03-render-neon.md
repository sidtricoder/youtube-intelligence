# Render + Neon cloud implementation plan

> Execute inline, continuing the user's one-pass implementation request.

Goal: Deliver the complete private project with actual PostgreSQL persistence and Render/Claude configuration, preserving local use and the OAuth UI fix.
Architecture: Portable SQLAlchemy encrypted repository with SQLite for explicit local configuration and psycopg PostgreSQL when DATABASE_URL is configured. Quota operations move behind repository methods. PostgreSQL transactions use a namespaced transaction-level advisory lock, compatible with Neon transaction pooling. Failure to connect to a configured database never falls back to local storage.

- [x] Tests first: durable reopen, atomic take/draft claims, rollback, quota reservation/refund/concurrency, fail-closed database selection; Render callback/host/origin configuration and port binding.
- [x] Implement portable encrypted Store and quota methods; preserve existing local database table names and encrypted values.
- [x] Read DATABASE_URL / DATABASE_URL_POOLED as secret fields; prefer pooled at runtime. Add HTTPS public origin/Render URL derivation with strict callback matching. Render requires PostgreSQL.
- [x] Restrict MCP Host/Origin to configured cloud hostname plus loopback; retain credential roles, separate-tab sign-in and explicit owner confirmation.
- [x] Add Docker/Render runtime port binding, Blueprint, environment template and exact Claude connection instructions.
- [x] Execute offline suite, browser regression, PostgreSQL integration and real Neon connectivity/persistence checks where network permits; distinguish infrastructure restrictions from code failures.
- [x] Independent review; fix important findings; include existing credentials and database URLs only in private .env; package/save ZIP.

Review focus: secrets never in tracked source/logs; no connection-failure fallback; persistent keys consistent across redeploy; pooled transaction lock correctness; public HTTPS callback and MCP hostname; no change to owner confirmation guarantees.
