import importlib.util
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.context import UserContext
from ytintel.errors import AppError
from ytintel.providers.google import GoogleProvider
from ytintel.quota import Quota
from ytintel.store import Store
from ytintel.tenancy import ScopedStore
from ytintel.tenant_quota import TenantQuota


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "google.db"), Fernet.generate_key().decode())


async def test_production_public_lookup_uses_google_api_without_fixture_provider(
    tmp_path, monkeypatch
):
    import ytintel.app as app_module

    requests = []
    client_type = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    def offline_client(*args, **kwargs):
        return client_type(*args, **{**kwargs, "transport": httpx.MockTransport(respond)})

    monkeypatch.setattr(app_module.httpx, "AsyncClient", offline_client)
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "app.db"),
        encryption_key=Fernet.generate_key().decode(),
        youtube_api_key="public-key",
    )
    app = create_app(settings)
    async with client_type(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/similar-videos", params={"video": "aaaaaaaaaaa"})
    assert response.status_code == 404  # The real adapter received no matching Google video.
    assert requests[0].url.host == "www.googleapis.com"
    assert requests[0].url.path == "/youtube/v3/videos"
    assert requests[0].headers["x-goog-api-key"] == "public-key"
    assert "authorization" not in requests[0].headers


async def test_public_video_reads_use_key_without_oauth(store):
    requests = []

    async def forbidden_token():
        pytest.fail("Public key-only lookup must not ask for user OAuth")

    def handler(r):
        requests.append(r)
        return httpx.Response(200, json={"items": []})

    provider = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        forbidden_token,
        store,
        public_api_key="synthetic-public-key",
    )
    with Quota(store).reserve(1, 0):
        assert await provider.videos(["aaaaaaaaaaa"]) == []
    assert requests[0].headers["X-Goog-Api-Key"] == "synthetic-public-key"
    assert "authorization" not in requests[0].headers


async def test_api_key_never_substitutes_for_private_oauth(store):
    requests = []

    async def missing_token():
        raise AppError("reauthorization_required", "Sign in", 401)

    provider = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: requests.append(r))),
        missing_token,
        store,
        public_api_key="synthetic-public-key",
    )
    with Quota(store).reserve(51, 0):
        with pytest.raises(AppError) as e:
            await provider.request("videos", {"myRating": "like"})
        assert e.value.code == "reauthorization_required"
        with pytest.raises(AppError):
            await provider.create_playlist("Title")
    assert requests == []


async def test_connected_public_reads_use_api_key_without_account_credentials(store):

    async def token():
        pytest.fail("Public lookup must not use connected account credentials")

    requests = []

    def handler(r):
        requests.append(r)
        return httpx.Response(200, json={"items": []})

    provider = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        token,
        store,
        public_api_key="synthetic-public-key",
    )
    with Quota(store).reserve(1, 0):
        await provider.videos(["aaaaaaaaaaa"])
    assert requests[0].headers["X-Goog-Api-Key"] == "synthetic-public-key"
    assert "authorization" not in requests[0].headers


@pytest.mark.parametrize(
    "reason,code",
    [
        ("keyInvalid", "invalid_api_key"),
        ("accessNotConfigured", "api_not_enabled"),
        ("ipRefererBlocked", "api_key_restricted"),
    ],
)
async def test_api_key_errors_are_actionable_and_redacted(store, reason, code):
    async def token():
        return "synthetic-token"

    provider = GoogleProvider(
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(
                    403,
                    json={
                        "error": {
                            "errors": [{"reason": reason}],
                            "message": "Sensitive synthetic-public-key",
                        }
                    },
                )
            )
        ),
        token,
        store,
        public_api_key="synthetic-public-key",
    )
    with Quota(store).reserve(1, 0):
        with pytest.raises(AppError) as e:
            await provider.videos(["aaaaaaaaaaa"])
    assert e.value.code == code
    assert "synthetic-public-key" not in str(e.value)


def test_json_configuration_imports_project_and_preserves_generated_encryption_key(tmp_path):
    import json

    spec = importlib.util.spec_from_file_location(
        "configure_google", Path(__file__).parents[1] / "scripts/configure_google.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    credentials = tmp_path / "client_secret.json"
    credentials.write_text(
        json.dumps(
            {
                "web": {
                    "project_id": "synthetic-project",
                    "client_id": "synthetic-id",
                    "client_secret": "synthetic-secret",
                    "redirect_uris": [],
                }
            }
        )
    )
    destination = tmp_path / ".env"
    report = module.configure(credentials, destination, "synthetic-public-key")
    settings = Settings(_env_file=destination)
    before = settings.encryption_key
    assert settings.google_project_id == "synthetic-project"
    assert settings.youtube_api_key == "synthetic-public-key"
    assert settings.google_client_secret == "synthetic-secret"
    assert report["redirect_registered_in_download"] is False
    module.configure(credentials, destination, "new-synthetic-key")
    settings = Settings(_env_file=destination)
    assert settings.encryption_key == before
    assert not hasattr(settings, "api_key") and not hasattr(settings, "owner_key")


async def test_revoked_account_private_request_never_falls_back_to_api_key(store):
    calls = []

    async def revoked():
        raise AppError("reauthorization_required", "Sign in again", 401)

    quota = TenantQuota(store, "revoked-user")
    context = UserContext("revoked-user", revoked, quota)
    provider = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))),
        revoked,
        ScopedStore(store, "revoked-user"),
        public_api_key="synthetic-key",
        context=context,
    )
    with quota.reserve(1, 0):
        with pytest.raises(AppError) as error:
            await provider.request("subscriptions", {"mine": "true"})
    assert error.value.code == "reauthorization_required"
    assert calls == []


async def test_private_google_requests_use_each_request_account_and_isolated_cache(store):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"items": [{"account": request.headers["Authorization"]}]})

    async def alice_credentials():
        return "alice-token"

    async def bob_credentials():
        return "bob-token"

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for user, credentials in [("alice", alice_credentials), ("bob", bob_credentials)]:
            quota = TenantQuota(store, user)
            context = UserContext(user, credentials, quota)
            provider = GoogleProvider(
                client,
                credentials,
                ScopedStore(store, user),
                public_api_key="public",
                context=context,
            )
            with quota.reserve(1, 0):
                result = await provider.request("subscriptions", {"mine": "true"})
                assert result["items"] == [{"account": f"Bearer {user}-token"}]
    assert len(calls) == 2
    assert all("x-goog-api-key" not in request.headers for request in calls)
