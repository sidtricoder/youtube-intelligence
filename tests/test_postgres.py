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
        assert sum(results) == 2
        assert Quota(store).status()["units_used"] == 2
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


def test_postgres_security_sessions_and_google_grants_are_isolated(pg):
    from ytintel.migrate import migrate
    from ytintel.security import SecurityStore
    from ytintel.tenancy import ScopedStore

    raw, url, schema, key = pg
    assert migrate(raw) == 1
    security = SecurityStore(raw)
    alice, bob = (security.upsert_user(sub) for sub in ("google-sub-alice", "google-sub-bob"))
    assert alice != bob
    security.save_google(alice, {"refresh_token": "synthetic-alice"})
    security.save_google(bob, {"refresh_token": "synthetic-bob"})
    alice_cookie, alice_csrf = security.create_session(alice)
    bob_cookie, _ = security.create_session(bob)
    ScopedStore(raw, alice).put("draft:same-id", {"owner": "alice"})
    ScopedStore(raw, bob).put("draft:same-id", {"owner": "bob"})
    raw.close()
    reopened = Store.from_url(url.get_secret_value(), key, schema=schema)
    try:
        durable = SecurityStore(reopened)
        assert durable.upsert_user("google-sub-alice") == alice
        assert durable.session(alice_cookie) == {
            "user_id": alice,
            "csrf": alice_csrf,
            "generation": durable.generation(alice),
        }
        assert ScopedStore(reopened, alice).get("draft:same-id") == {"owner": "alice"}
        assert ScopedStore(reopened, bob).get("draft:same-id") == {"owner": "bob"}
        durable.revoke_user(alice)
        assert durable.google(alice) is None
        assert durable.session(alice_cookie) is None
        assert durable.google(bob) == {"refresh_token": "synthetic-bob"}
        assert durable.session(bob_cookie)["user_id"] == bob
    finally:
        reopened.close()


async def test_postgres_oauth_rotation_replay_and_two_user_isolation(pg):
    from urllib.parse import parse_qs, urlsplit

    from mcp.server.auth.provider import AuthorizationParams, TokenError
    from mcp.shared.auth import OAuthClientInformationFull
    from pydantic import AnyUrl

    from ytintel.security import AuthServer, SecurityStore

    raw, *_ = pg
    security = SecurityStore(raw)
    server = AuthServer(security, "https://synthetic.example")
    client = OAuthClientInformationFull(
        client_id="synthetic-client",
        redirect_uris=[AnyUrl("https://synthetic-client.example/callback")],
        token_endpoint_auth_method="none",
    )
    await server.register_client(client)

    async def issue(subject):
        user = security.upsert_user(subject)
        params = AuthorizationParams(
            state="state",
            scopes=["youtube.read"],
            code_challenge="a" * 43,
            redirect_uri=client.redirect_uris[0],
            redirect_uri_provided_explicitly=True,
            resource=server.resource,
        )
        transaction = parse_qs(urlsplit(await server.authorize(client, params)).query)[
            "transaction"
        ][0]
        callback = server.complete_login(transaction, user)
        code = parse_qs(urlsplit(callback).query)["code"][0]
        record = await server.load_authorization_code(client, code)
        token = await server.exchange_authorization_code(client, record)
        assert await server.load_authorization_code(client, code) is None
        return user, token

    alice, alice_token = await issue("alice")
    bob, bob_token = await issue("bob")
    assert (await server.load_access_token(alice_token.access_token)).user_id == alice
    assert (await server.load_access_token(bob_token.access_token)).user_id == bob
    refresh = await server.load_refresh_token(client, alice_token.refresh_token)
    rotated = await server.exchange_refresh_token(client, refresh, refresh.scopes)
    with pytest.raises(TokenError):
        await server.exchange_refresh_token(client, refresh, refresh.scopes)
    assert await server.load_access_token(rotated.access_token) is None
    assert await server.load_access_token(bob_token.access_token)
    security.revoke_user(bob)
    assert await server.load_access_token(bob_token.access_token) is None


def test_postgres_subject_upsert_is_atomic_across_repository_instances(pg):
    from ytintel.security import SecurityStore

    raw, url, schema, key = pg
    first = SecurityStore(raw)
    second_raw = Store.from_url(url.get_secret_value(), key, schema=schema)
    second = SecurityStore(second_raw)
    barrier = threading.Barrier(2)

    def upsert(security):
        barrier.wait()
        return security.upsert_user("same-verified-google-subject")

    try:
        with ThreadPoolExecutor(2) as pool:
            users = list(pool.map(upsert, [first, second]))
        assert users[0] == users[1]
    finally:
        second_raw.close()
