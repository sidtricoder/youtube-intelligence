"""Google OIDC contract exercised with local keys and an offline HTTP transport."""

import hashlib
import json
from base64 import urlsafe_b64encode
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from ytintel.errors import AppError
from ytintel.identity import GoogleIdentityProvider

NOW = 2000000000
READ_SCOPE = "https://www.googleapis.com/auth/youtube.readonly"
WRITE_SCOPE = "https://www.googleapis.com/auth/youtube"


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def provider(transport):
    return GoogleIdentityProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        "client-id",
        "client-secret",
        "https://app.example/oauth/callback",
        clock=lambda: NOW,
    )


def id_token(key, **changes):
    claims = {
        "sub": "google-subject",
        "iss": "https://accounts.google.com",
        "aud": "client-id",
        "exp": NOW + 300,
        "iat": NOW - 10,
        "nonce": "nonce",
    }
    claims.update(changes)
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "local-key"})


def transport_for(key, token, seen=None):
    def respond(request):
        if seen is not None:
            seen.append(request)
        if request.url.path == "/oauth2/v3/certs":
            jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
            return httpx.Response(200, json={"keys": [{**jwk, "kid": "local-key", "alg": "RS256"}]})
        return httpx.Response(
            200,
            json={
                "id_token": token,
                "access_token": "access",
                "refresh_token": "refresh",
                "expires_in": 3600,
                "scope": f"openid {READ_SCOPE}",
                "token_type": "Bearer",
            },
        )

    return respond


def test_authorization_uses_pkce_and_minimum_scopes_with_explicit_write_upgrade():
    identity = provider(lambda request: pytest.fail("authorization must be local"))
    query = parse_qs(urlparse(identity.authorization_url("state", "nonce", "verifier")).query)
    assert query["state"] == ["state"]
    assert query["nonce"] == ["nonce"]
    assert query["scope"][0].split() == ["openid", READ_SCOPE]
    assert query["code_challenge_method"] == ["S256"]
    challenge = urlsafe_b64encode(hashlib.sha256(b"verifier").digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]
    assert query["access_type"] == ["offline"]
    assert query["prompt"] == ["consent"]
    assert query["include_granted_scopes"] == ["true"]
    write = parse_qs(urlparse(identity.authorization_url("s", "n", "v", write=True)).query)
    assert WRITE_SCOPE in write["scope"][0].split()


async def test_exchange_verifies_google_subject_and_normalizes_credentials(signing_key):
    seen = []
    identity = provider(transport_for(signing_key, id_token(signing_key), seen))
    result = await identity.exchange("code", "verifier", "nonce")
    assert result.sub == "google-subject"
    assert result.tokens == {
        "access_token": "access",
        "refresh_token": "refresh",
        "expires_at": NOW + 3600,
        "scope": f"openid {READ_SCOPE}",
    }
    form = parse_qs(seen[0].content.decode())
    assert form["code_verifier"] == ["verifier"]
    assert form["redirect_uri"] == ["https://app.example/oauth/callback"]
    assert form["grant_type"] == ["authorization_code"]


@pytest.mark.parametrize(
    "change",
    [
        {"nonce": "wrong"},
        {"iss": "https://attacker.example"},
        {"aud": "other-client"},
        {"exp": NOW - 1},
        {"exp": None},
        {"exp": 10**400},
        {"sub": ""},
        {"sub": None},
    ],
)
async def test_exchange_rejects_invalid_identity_claims(signing_key, change):
    identity = provider(transport_for(signing_key, id_token(signing_key, **change)))
    with pytest.raises(AppError) as error:
        await identity.exchange("code", "verifier", "nonce")
    assert error.value.code == "identity_verification_failed"


@pytest.mark.parametrize("token", ["not-a-jwt", "eyJhbGciOiJub25lIn0.e30."])
async def test_exchange_rejects_malformed_and_unsigned_id_tokens(signing_key, token):
    identity = provider(transport_for(signing_key, token))
    with pytest.raises(AppError):
        await identity.exchange("code", "verifier", "nonce")


async def test_exchange_rejects_signature_from_an_untrusted_key(signing_key):
    attacker_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity = provider(transport_for(signing_key, id_token(attacker_key)))
    with pytest.raises(AppError) as error:
        await identity.exchange("code", "verifier", "nonce")
    assert error.value.code == "identity_verification_failed"


async def test_refresh_normalizes_tokens_without_erasing_existing_refresh_token():
    def respond(request):
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["refresh_token"]
        assert form["refresh_token"] == ["old-refresh"]
        return httpx.Response(
            200,
            json={
                "access_token": "renewed",
                "expires_in": 1800,
                "scope": f"openid {READ_SCOPE}",
                "token_type": "Bearer",
            },
        )

    result = await provider(respond).refresh("old-refresh")
    assert result == {
        "access_token": "renewed",
        "expires_at": NOW + 1800,
        "scope": f"openid {READ_SCOPE}",
    }


async def test_revoked_refresh_requires_reauthorization_and_sanitizes_upstream_error():
    identity = provider(
        lambda request: httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "secret-upstream-body"}
        )
    )
    with pytest.raises(AppError) as error:
        await identity.refresh("secret-refresh")
    assert error.value.code == "reauthorization_required"
    assert error.value.status == 401
    assert "secret" not in str(error.value)


async def test_revoke_posts_token_and_accepts_success():
    def respond(request):
        assert request.url.host == "oauth2.googleapis.com"
        assert request.url.path == "/revoke"
        assert parse_qs(request.content.decode()) == {"token": ["refresh"]}
        return httpx.Response(200)

    await provider(respond).revoke("refresh")


@pytest.mark.parametrize(
    "response", [httpx.Response(500, text="secret"), httpx.Response(200, text="not json")]
)
async def test_token_failures_are_safe_application_errors(response):
    with pytest.raises(AppError) as error:
        await provider(lambda request: response).refresh("secret-refresh")
    assert "secret" not in str(error.value)
