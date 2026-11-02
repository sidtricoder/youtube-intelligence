import importlib.util
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet

from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.errors import AppError
from ytintel.providers.google import GoogleProvider
from ytintel.quota import Quota
from ytintel.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "google.db"), Fernet.generate_key().decode())


def test_production_is_google_only(tmp_path):
    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "app.db"),
        encryption_key=Fernet.generate_key().decode(),
        api_key="a" * 32,
        owner_key="o" * 32,
    )
    app = create_app(settings)
    assert isinstance(app.state.service.provider, GoogleProvider)
    assert not hasattr(settings, "mode")
    assert not Path(__file__).parents[1].joinpath("src/ytintel/providers/demo.py").exists()


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


async def test_connected_public_reads_preserve_private_video_access(store):
    store.put("oauth:tokens", {"access_token": "synthetic-token"})

    async def token():
        return "synthetic-token"

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
    assert requests[0].headers["Authorization"] == "Bearer synthetic-token"


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


def test_json_configuration_imports_project_and_preserves_generated_local_keys(tmp_path):
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
    before = settings.api_key, settings.owner_key, settings.encryption_key
    assert settings.google_project_id == "synthetic-project"
    assert settings.youtube_api_key == "synthetic-public-key"
    assert settings.google_client_secret == "synthetic-secret"
    assert report["redirect_registered_in_download"] is False
    module.configure(credentials, destination, "new-synthetic-key")
    settings = Settings(_env_file=destination)
    assert (settings.api_key, settings.owner_key, settings.encryption_key) == before


async def test_revoked_connected_account_never_falls_back_to_api_key(store):
    store.put("oauth:tokens", {"access_token": "expired"})
    calls = []

    async def revoked():
        raise AppError("reauthorization_required", "Sign in again", 401)

    provider = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))),
        revoked,
        store,
        public_api_key="synthetic-key",
    )
    with Quota(store).reserve(1, 0):
        with pytest.raises(AppError):
            await provider.videos(["aaaaaaaaaaa"])
    assert calls == []
