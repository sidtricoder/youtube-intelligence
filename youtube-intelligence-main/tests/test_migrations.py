"""Schema creation has no implicit account migration or configuration loading."""

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import inspect, select

from ytintel.migrate import migrate
from ytintel.store import Store


def test_schema_migration_is_idempotent_and_preserves_existing_data(tmp_path):
    raw = Store(str(tmp_path / "migration.sqlite"), Fernet.generate_key().decode())
    raw.put("old-google-grant", {"refresh_token": "unassigned-legacy-token"})
    assert migrate(raw) == 1
    assert migrate(raw) == 1
    names = set(inspect(raw.engine).get_table_names())
    assert {
        "users",
        "user_google_tokens",
        "oauth_clients",
        "auth_codes",
        "access_tokens",
        "refresh_tokens",
        "web_sessions",
        "login_transactions",
        "token_families",
        "drafts",
        "tenant_cache",
        "public_cache",
        "quota_ledger",
        "schema_migrations",
    } <= names
    table = raw.metadata.tables["schema_migrations"]
    with raw.tx() as db:
        assert db.execute(select(table.c.version)).scalars().all() == [1]
        assert db.execute(select(raw.metadata.tables["users"])).first() is None
        assert "generation" in raw.metadata.tables["users"].c
    assert raw.get("old-google-grant")["refresh_token"] == "unassigned-legacy-token"
    raw.close()


def test_unknown_future_schema_is_rejected(tmp_path):
    raw = Store(str(tmp_path / "migration.sqlite"), Fernet.generate_key().decode())
    migrate(raw)
    table = raw.metadata.tables["schema_migrations"]
    with raw.tx() as db:
        db.execute(table.insert().values(version=999, applied_at=0))
    with pytest.raises(RuntimeError, match="newer"):
        migrate(raw)
    raw.close()
