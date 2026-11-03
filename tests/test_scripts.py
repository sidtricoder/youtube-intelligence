"""CLI contracts use temporary configuration and offline transports only."""

import importlib.util
import json
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from cryptography.fernet import Fernet

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings


def script(name):
    path = Path(__file__).parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"script_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configured():
    return Settings(
        _env_file=None,
        encryption_key=Fernet.generate_key().decode(),
        google_client_id="client-id",
        google_client_secret="private-secret",
        youtube_api_key="private-key",
    )


async def test_public_google_check_uses_anonymous_preview_and_explicit_bounded_budget(
    tmp_path, monkeypatch
):
    module = script("check_google")
    monkeypatch.setattr(module, "Settings", configured)
    seen = []

    def offline_app(settings):
        seen.append(settings)
        assert settings.database_connection is None
        provider = FixtureProvider()
        provider.items[0] = provider.items[0].model_copy(update={"id": "rfscVS0vtbw"})
        return create_app(settings, provider=provider)

    monkeypatch.setattr(module, "create_app", offline_app)
    output = tmp_path / "check.json"
    assert await module.check(output) == 0
    result = json.loads(output.read_text())
    assert result["live_writes"] == 0 and result["failed"] == 0
    assert seen[0].units_per_day == 10 and seen[0].searches_per_day == 3
    assert seen[0].anonymous_units_per_day == 10
    assert any("preview" in item["name"].lower() for item in result["checks"])
    assert "private-secret" not in output.read_text() and "private-key" not in output.read_text()


async def test_oauth_check_builds_pkce_authorization_without_network_or_store(
    tmp_path, monkeypatch
):
    module = script("check_oauth")
    monkeypatch.setattr(module, "Settings", configured)
    urls = []
    client_type = httpx.AsyncClient
    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(
            **kwargs,
            transport=httpx.MockTransport(lambda request: pytest.fail("OAuth readiness is local")),
        ),
    )
    real_provider = module.GoogleIdentityProvider

    class CaptureProvider(real_provider):
        def authorization_url(self, state, nonce, verifier, write=True):
            assert len(state) >= 32 and len(nonce) >= 32 and len(verifier) >= 43
            urls.append(super().authorization_url(state, nonce, verifier, write=write))
            return urls[-1]

    monkeypatch.setattr(module, "GoogleIdentityProvider", CaptureProvider)
    output = tmp_path / "oauth.json"
    result = await module.check(output)
    query = parse_qs(urlsplit(urls[0]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert "https://www.googleapis.com/auth/youtube" in query["scope"][0].split()
    assert result["user_consent_completed"] is False
    assert "private-secret" not in output.read_text() and "code_challenge" not in output.read_text()


async def test_live_smoke_without_api_key_makes_no_client(tmp_path, monkeypatch, capsys):
    module = script("live_smoke")
    monkeypatch.delenv("LIVE_YOUTUBE_API_KEY", raising=False)
    monkeypatch.setattr(
        module.httpx, "AsyncClient", lambda **kwargs: pytest.fail("No network allowed")
    )
    assert await module.main() == 0
    assert "SKIP" in capsys.readouterr().out


async def test_live_smoke_uses_one_public_video_call_without_oauth(monkeypatch, capsys):
    module = script("live_smoke")
    monkeypatch.setenv("LIVE_YOUTUBE_API_KEY", "synthetic-secret-key")
    requests = []
    client_type = httpx.AsyncClient

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(
        module.httpx,
        "AsyncClient",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(respond)),
    )
    assert await module.main() == 0
    assert len(requests) == 1 and requests[0].url.path == "/youtube/v3/videos"
    assert requests[0].headers["x-goog-api-key"] == "synthetic-secret-key"
    assert "authorization" not in requests[0].headers
    assert "synthetic-secret-key" not in capsys.readouterr().out


@pytest.mark.parametrize("token", [None, "externally-issued-token"])
async def test_mcp_client_uses_public_tool_with_optional_oauth_bearer(monkeypatch, capsys, token):
    module = script("mcp_client")
    monkeypatch.setenv("MCP_URL", "https://intel.example/mcp/")
    monkeypatch.delenv("MCP_ACCESS_TOKEN", raising=False)
    if token:
        monkeypatch.setenv("MCP_ACCESS_TOKEN", token)
    seen = {}

    @asynccontextmanager
    async def transport(url, http_client):
        seen["url"], seen["authorization"] = url, http_client.headers.get("authorization")
        yield "read", "write", None

    class Session:
        def __init__(self, read, write):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def list_tools(self):
            return SimpleNamespace(tools=[SimpleNamespace(name="propose_playlist")])

        async def call_tool(self, name, arguments):
            seen["tool"] = name
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(type="text", text='{"videos": [], "total_seconds": 0}')],
            )

    monkeypatch.setattr(module, "streamable_http_client", transport)
    monkeypatch.setattr(module, "ClientSession", Session)
    assert await module.main() == 0
    assert seen == {
        "url": "https://intel.example/mcp/",
        "authorization": "Bearer " + token if token else None,
        "tool": "propose_playlist",
    }
    assert "externally-issued-token" not in capsys.readouterr().out


async def test_mcp_client_http_error_is_clear_and_redacted(monkeypatch, capsys):
    module = script("mcp_client")
    monkeypatch.setenv("MCP_ACCESS_TOKEN", "secret-bearer")

    @asynccontextmanager
    async def transport(url, http_client):
        request = httpx.Request("POST", "https://intel.example/mcp/?secret=do-not-print")
        response = httpx.Response(401, request=request)
        raise httpx.HTTPStatusError("private upstream body", request=request, response=response)
        yield  # pragma: no cover

    monkeypatch.setattr(module, "streamable_http_client", transport)
    assert await module.main() == 1
    output = capsys.readouterr().out
    assert "401" in output
    assert all(
        secret not in output for secret in ["secret-bearer", "do-not-print", "private upstream"]
    )


def test_configure_generates_no_shared_owner_or_api_credentials(tmp_path):
    module = script("configure_google")
    credentials = tmp_path / "credentials.json"
    credentials.write_text(json.dumps({"web": {"client_id": "client", "client_secret": "secret"}}))
    destination = tmp_path / "test.env"
    module.configure(credentials, destination, "public-key")
    content = destination.read_text()
    assert "YT_API_KEY=" not in content and "YT_OWNER_KEY=" not in content
    assert "YT_ENCRYPTION_KEY=" in content
