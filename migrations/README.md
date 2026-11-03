# Schema migration 001

`python -m ytintel.migrate` is the supported versioned, idempotent migration runner. It explicitly initializes the configured target and records version 1 in `schema_migrations`. The runner rejects databases whose recorded schema version is newer than the application. It does not load a `.env` file or select a default database file.

With environment variables already supplied by the deployment environment:

```sh
python -m ytintel.migrate --database-url-env DATABASE_URL --key-env YT_ENCRYPTION_KEY --schema ytintel
```

For an explicitly selected local database:

```sh
python -m ytintel.migrate --sqlite /absolute/path/database.sqlite --key-env YT_ENCRYPTION_KEY
```

Use the same Fernet encryption key as the application. Neither keys nor URLs are printed. Back up an existing deployment before schema changes. No rollback command deletes records; restoring a backup is an operator decision.

The SQL files are equivalent fresh-schema reference DDL generated from SQLAlchemy metadata for SQLite and PostgreSQL. PostgreSQL DDL uses the default `ytintel` schema; use the Python runner for another schema. Existing deployments should use the runner for the schema-version compatibility check.

The migration adds users, encrypted Google credentials, OAuth clients, hashed authorization/access/refresh secrets, revocable token families, encrypted web sessions/login transactions, per-user drafts/cache, public metadata cache, and the quota ledger. Existing legacy key/value and quota tables remain intact. Legacy Google grants are deliberately never assigned to a user: each account must establish ownership with a new verified Google login.

The runner and SQLite DDL are checked by offline tests. Optional PostgreSQL tests require `TEST_DATABASE_URL`, use fresh disposable `ytintel_test_*` schemas, and drop only those test schemas on completion. They cover encrypted durability, session/grant isolation, tenant drafts, atomic subject creation, authorization-code consumption, refresh rotation/replay, and user revocation; the original repository/quota contracts remain covered.
