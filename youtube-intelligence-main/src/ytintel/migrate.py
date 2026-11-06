"""Explicit, versioned, idempotent creation of the multi-tenant schema.

No legacy grant is assigned to a user: ownership requires a new verified login.
"""

import argparse
import os
import time

from sqlalchemy import Column, Float, Integer, Table, select

from .security import SecurityStore
from .store import Store
from .tenancy import tables
from .tenant_quota import TenantQuota

SCHEMA_VERSION = 1


def migrate(raw: Store) -> int:
    """Apply schema creation to an explicitly supplied repository, preserving all records."""
    version_table = Table(
        "schema_migrations",
        raw.metadata,
        Column("version", Integer, primary_key=True),
        Column("applied_at", Float, nullable=False),
        extend_existing=True,
    )
    with raw.tx() as db:
        version_table.create(db, checkfirst=True)
        versions = db.execute(select(version_table.c.version)).scalars().all()
        if versions and max(versions) > SCHEMA_VERSION:
            raise RuntimeError("Database schema is newer than this application")
    # Each component creates its tables under the repository transaction lock. Repeating
    # these operations repairs an interrupted initial migration without moving user data.
    SecurityStore(raw)
    tables(raw)
    TenantQuota(raw, "migration-schema-only")
    with raw.tx() as db:
        db.execute(
            raw._insert(version_table)
            .values(
                version=SCHEMA_VERSION,
                applied_at=time.time(),
            )
            .on_conflict_do_nothing(index_elements=["version"])
        )
    return SCHEMA_VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--sqlite", help="Explicit SQLite file to initialize")
    target.add_argument(
        "--database-url-env", help="Environment variable containing a PostgreSQL URL"
    )
    parser.add_argument("--schema", default="ytintel")
    parser.add_argument(
        "--key-env",
        default="YT_ENCRYPTION_KEY",
        help="Environment variable containing the Fernet key",
    )
    args = parser.parse_args()
    key = os.environ.get(args.key_env)
    if not key:
        parser.error("The configured encryption key environment variable is missing")
    if args.sqlite:
        raw = Store(args.sqlite, key)
    else:
        url = os.environ.get(args.database_url_env)
        if not url:
            parser.error("The configured database URL environment variable is missing")
        raw = Store.from_url(url, key, schema=args.schema)
    try:
        version = migrate(raw)
        print(f"Schema version {version} ready")
    finally:
        raw.close()


if __name__ == "__main__":
    main()
