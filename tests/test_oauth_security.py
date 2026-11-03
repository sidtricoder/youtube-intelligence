import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy import select

from ytintel.security import AuthServer, SecurityStore
from ytintel.store import Store


@pytest.fixture
def security(tmp_path):
    raw = Store(str(tmp_path / "security.sqlite"), Fernet.generate_key().decode())
    store = SecurityStore(raw)
    yield store
    raw.close()


async def issued(security):
    server = AuthServer(security, "https://intel.example")
    client = OAuthClientInformationFull(
        client_id="test",
        redirect_uris=[AnyUrl("https://client.example/callback")],
        token_endpoint_auth_method="none",
    )
    await server.register_client(client)
    params = AuthorizationParams(
        state="client-state",
        scopes=["youtube.read"],
        code_challenge="a" * 43,
        redirect_uri=client.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=server.resource,
    )
    url = await server.authorize(client, params)
    transaction = parse_qs(urlsplit(url).query)["transaction"][0]
    user = security.upsert_user("google-subject")
    redirect = server.complete_login(transaction, user)
    code = parse_qs(urlsplit(redirect).query)["code"][0]
    record = await server.load_authorization_code(client, code)
    token = await server.exchange_authorization_code(client, record)
    return server, client, user, code, token


async def test_codes_are_single_use_and_secrets_hashed(security):
    server, client, user, code, token = await issued(security)
    assert await server.load_authorization_code(client, code) is None
    access = await server.load_access_token(token.access_token)
    assert access.user_id == user
    with security.raw.tx() as db:
        row = db.execute(select(security.access_tokens)).mappings().one()
        assert row["digest"] == hashlib.sha256(token.access_token.encode()).hexdigest()
        assert token.access_token not in str(row)


async def test_refresh_rotation_replay_revokes_family(security):
    server, client, user, code, token = await issued(security)
    old = await server.load_refresh_token(client, token.refresh_token)
    rotated = await server.exchange_refresh_token(client, old, old.scopes)
    assert await server.load_access_token(rotated.access_token)
    with pytest.raises(TokenError):
        await server.exchange_refresh_token(client, old, old.scopes)
    assert await server.load_access_token(rotated.access_token) is None


def test_subject_stable_encrypted_google_sessions_and_revocation(security):
    user = security.upsert_user("subject")
    assert security.upsert_user("subject") == user
    security.save_google(user, {"refresh_token": "google-secret"})
    assert security.google(user)["refresh_token"] == "google-secret"
    cookie, csrf = security.create_session(user)
    assert security.session(cookie) == {
        "user_id": user,
        "csrf": csrf,
        "generation": security.generation(user),
    }
    with security.raw.tx() as db:
        row = db.execute(select(security.user_google_tokens)).mappings().one()
        assert b"google-secret" not in row["payload"]
    security.revoke_user(user)
    assert security.google(user) is None
    assert security.session(cookie) is None


@pytest.mark.parametrize(
    "uri",
    [
        "http://example.com/cb",
        "https://a.example/cb#frag",
        "https://user@a.example/cb",
        "https://*.example/cb",
    ],
)
async def test_invalid_redirects_rejected(security, uri):
    server = AuthServer(security, "https://intel.example")
    client = OAuthClientInformationFull(
        client_id="test", redirect_uris=[AnyUrl(uri)], token_endpoint_auth_method="none"
    )
    with pytest.raises(Exception):
        await server.register_client(client)


async def test_expiry_audience_and_cross_client_isolation(security):
    from mcp.server.auth.provider import AuthorizeError

    server, client, user, code, token = await issued(security)
    attacker = client.model_copy(update={"client_id": "attacker"})
    assert await server.load_refresh_token(attacker, token.refresh_token) is None
    params = AuthorizationParams(
        state=None,
        scopes=[],
        code_challenge="a" * 43,
        redirect_uri=client.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource="https://different.example/mcp/",
    )
    with pytest.raises(AuthorizeError):
        await server.authorize(client, params)
    now = security.clock.now()

    class ExpiredClock:
        def now(self):
            return now + 4000

    security.clock = ExpiredClock()
    assert await server.load_access_token(token.access_token) is None


async def test_user_revocation_invalidates_oauth_credentials(security):
    server, client, user, code, token = await issued(security)
    security.revoke_user(user)
    assert await server.load_access_token(token.access_token) is None
    assert await server.load_refresh_token(client, token.refresh_token) is None


async def test_login_consumed_once_and_authorization_state_preserved(security):
    from mcp.server.auth.provider import AuthorizeError

    server = AuthServer(security, "https://intel.example")
    client = OAuthClientInformationFull(
        client_id="test",
        redirect_uris=[AnyUrl("https://client.example/callback")],
        token_endpoint_auth_method="none",
    )
    params = AuthorizationParams(
        state="state with symbols &",
        scopes=[],
        code_challenge="a" * 43,
        redirect_uri=client.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=server.resource,
    )
    url = await server.authorize(client, params)
    transaction = parse_qs(urlsplit(url).query)["transaction"][0]
    value = security.get_login(transaction)
    value.update(state="google-state", nonce="oidc-nonce", verifier="pkce-secret")
    security.update_login(transaction, value)
    redirect = server.complete_login(transaction, security.upsert_user("sub"))
    assert parse_qs(urlsplit(redirect).query)["state"] == ["state with symbols &"]
    with pytest.raises(AuthorizeError):
        server.complete_login(transaction, "any-user")


def test_google_subject_upsert_is_atomic(security):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(4) as pool:
        users = list(pool.map(lambda _: security.upsert_user("one-verified-subject"), range(8)))
    assert len(set(users)) == 1


def test_security_services_implement_structural_boundaries(security):
    from ytintel.security.protocols import ClientRegistry, SessionStore, TokenStore

    assert isinstance(security, TokenStore)
    assert isinstance(security, SessionStore)
    assert isinstance(AuthServer(security, "https://issuer.example"), ClientRegistry)


def test_refresh_cannot_restore_revoked_or_replaced_google_grant(security):
    user = security.upsert_user("refresh-race-user")
    assert security.generation(user) == 0
    previous = {"refresh_token": "old-refresh", "access_token": "old-access"}
    security.save_google(user, previous)
    generation = security.generation(user)
    assert generation == 1
    assert security.revoke_user(user, expected_generation=generation)
    assert security.generation(user) == generation + 1
    assert not security.save_google_if_current(user, previous, {"access_token": "late-access"})
    assert security.google(user) is None
    fresh = {"refresh_token": "new-grant"}
    security.save_google(user, fresh)
    assert not security.revoke_user(user, expected_generation=generation)
    assert security.google(user) == fresh
    assert not security.save_google_if_current(user, previous, {"access_token": "late-access"})
    assert security.google(user) == fresh


def test_current_google_refresh_preserves_generation_and_compare_is_atomic(security):
    from concurrent.futures import ThreadPoolExecutor

    user = security.upsert_user("current-refresh")
    previous = {"refresh_token": "refresh", "access_token": "old"}
    security.save_google(user, previous)
    generation = security.generation(user)
    with ThreadPoolExecutor(4) as pool:
        saved = list(
            pool.map(
                lambda n: security.save_google_if_current(
                    user,
                    previous,
                    {"refresh_token": "refresh", "access_token": str(n)},
                    expected_generation=generation,
                ),
                range(4),
            )
        )
    assert sum(saved) == 1
    assert security.generation(user) == generation


def test_fresh_google_save_compares_generation_atomically(security):
    user = security.upsert_user("conditional-fresh-login")
    original = security.generation(user)
    assert security.save_google(user, {"refresh_token": "first"}, expected_generation=original)
    assert security.generation(user) == original + 1
    assert not security.save_google(user, {"refresh_token": "stale"}, expected_generation=original)
    assert security.google(user) == {"refresh_token": "first"}
    assert security.generation(user) == original + 1
    assert security.save_google(
        user, {"refresh_token": "current"}, expected_generation=original + 1
    )
    assert security.generation(user) == original + 2


def test_grant_generation_and_browser_sessions_follow_authorization(security):
    from ytintel.errors import AppError

    user = security.upsert_user("session-authorization-generation")
    assert security.current_grant_generation(user) is None
    security.save_google(user, {"refresh_token": "original"})
    generation = security.current_grant_generation(user)
    assert generation == security.generation(user)
    cookie, csrf = security.create_session(user, expected_generation=generation)
    assert security.session(cookie) == {
        "user_id": user,
        "csrf": csrf,
        "generation": security.generation(user),
    }
    security.save_google(user, {"refresh_token": "replacement"})
    assert security.session(cookie) is None
    with pytest.raises(AppError):
        security.create_session(user, expected_generation=generation)
    with security.raw.tx() as db:
        assert len(db.execute(select(security.web_sessions)).all()) == 1
    security.revoke_user(user)
    assert security.current_grant_generation(user) is None


async def test_pending_consent_and_issued_code_cannot_outlive_authorization(security):
    from mcp.server.auth.provider import AuthorizeError

    server = AuthServer(security, "https://intel.example")
    client = OAuthClientInformationFull(
        client_id="test",
        redirect_uris=[AnyUrl("https://client.example/callback")],
        token_endpoint_auth_method="none",
    )
    await server.register_client(client)
    user = security.upsert_user("consent-bound-user")
    security.save_google(user, {"refresh_token": "grant"})

    async def pending():
        params = AuthorizationParams(
            state="state",
            scopes=[],
            code_challenge="a" * 43,
            redirect_uri=client.redirect_uris[0],
            redirect_uri_provided_explicitly=True,
            resource=server.resource,
        )
        transaction = parse_qs(urlsplit(await server.authorize(client, params)).query)[
            "transaction"
        ][0]
        data = security.get_login(transaction)
        data.update(consent_user_id=user, consent_generation=security.generation(user))
        security.update_login(transaction, data)
        return transaction

    transaction = await pending()
    security.revoke_user(user)
    with pytest.raises(AuthorizeError):
        server.complete_login(transaction, user)
    security.save_google(user, {"refresh_token": "new-grant"})
    transaction = await pending()
    redirect = server.complete_login(transaction, user)
    code = parse_qs(urlsplit(redirect).query)["code"][0]
    record = await server.load_authorization_code(client, code)
    security.save_google(user, {"refresh_token": "replaced-again"})
    with pytest.raises(TokenError):
        await server.exchange_authorization_code(client, record)
