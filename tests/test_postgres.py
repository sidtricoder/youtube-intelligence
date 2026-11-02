"""Opt-in real PostgreSQL contract tests; use disposable schemas, never account records."""

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.schema import DropSchema

from ytintel.errors import AppError
from ytintel.quota import Quota
from ytintel.store import Store

pytestmark = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for explicit PostgreSQL integration tests",
)


@pytest.fixture
def pg():
    url = os.environ["TEST_DATABASE_URL"]
    schema = "ytintel_test_" + uuid.uuid4().hex
    key = Fernet.generate_key().decode()
    store = Store.from_url(url, key, schema=schema)
    try:
        yield store, SecretStr(url), schema, key
    finally:
        assert schema.startswith("ytintel_test_")
        with store.tx() as db:
            db.execute(DropSchema(schema, cascade=True))
        store.close()


def test_encrypted_data_persists_after_connection_disposal(pg):
    store, url, schema, key = pg
    store.put("oauth:test", {"refresh_token": "synthetic-token-only"})
    with store.tx() as db:
        payload = db.execute(select(store.records.c.v)).scalar_one()
        assert b"synthetic-token-only" not in bytes(payload)
    store.close()
    reopened = Store.from_url(url.get_secret_value(), key, schema=schema)
    assert reopened.get("oauth:test")["refresh_token"] == "synthetic-token-only"
    reopened.close()


def test_postgres_atomic_take_under_concurrency(pg):
    store, *_ = pg
    store.put("once", {"value": 1})
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: store.take("once"), range(4)))
    assert sum(v is not None for v in results) == 1


def test_postgres_atomic_draft_claim_under_concurrency(pg):
    store, *_ = pg
    store.put("draft:test", {"status": "pending"})
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(lambda _: store.transition("draft:test", "pending", "writing"), range(4))
        )
    assert sum(v is not None for v in results) == 1


def test_postgres_quota_is_atomic_across_repository_instances(pg):
    store, url, schema, key = pg
    second = Store.from_url(url.get_secret_value(), key, schema=schema)
    gate = threading.Barrier(2)

    def reserve(repository):
        gate.wait()
        try:
            with Quota(repository, units=1, searches=0).reserve(1, 0) as ticket:
                ticket.consume(1, 0)
            return True
        except AppError as exc:
            assert exc.code == "quota_exceeded"
            return False

    try:
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(reserve, [store, second]))
        assert sum(results) == 1
        assert Quota(store).status()["units_used"] == 1
    finally:
        second.close()


def test_postgres_quota_refunds_unused_and_preserves_spent_units(pg):
    store, *_ = pg
    q = Quota(store, units=100, searches=5)
    with q.reserve(50, 3) as ticket:
        ticket.consume(2, 1)
    assert q.status()["units_used"] == 2 and q.status()["searches_used"] == 1


def test_postgres_transaction_rolls_back_on_application_error(pg):
    store, *_ = pg
    store.put("retain", {"v": 1})
    with pytest.raises(RuntimeError):
        with store.tx() as db:
            db.execute(delete(store.records))
            raise RuntimeError("synthetic rollback")
    assert store.get("retain") == {"v": 1}


def test_postgres_upsert_expiry_and_literal_prefix(pg):
    store, *_ = pg
    store.put("cache:one", {"v": 1})
    store.put("cache:one", {"v": 2})
    assert store.get("cache:one") == {"v": 2}
    store.put("expired", {"v": 1}, ttl=-1)
    store.purge()
    assert store.get("expired") is None
    store.put("literal%:value", {"v": 1})
    store.put("literalABC:value", {"v": 2})
    store.delete_prefix("literal%:")
    assert store.get("literal%:value") is None
    assert store.get("literalABC:value") == {"v": 2}
