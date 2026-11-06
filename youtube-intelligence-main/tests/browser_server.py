"""Browser-test composition only. Production has no synthetic runtime mode."""

import base64
import hashlib
import os
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.errors import AppError
from ytintel.identity import READ_SCOPE, WRITE_SCOPE


def create_browser_app():
    settings = Settings(
        _env_file=None,
        encryption_key=Fernet.generate_key().decode(),
        db_path=os.environ.get("YT_DB_PATH")
        or str(Path(tempfile.mkdtemp(prefix="ytintel-browser-")) / "browser.db"),
        database_url=None,
        database_url_pooled=None,
        render_external_url="",
        public_base_url="",
        redirect_uri="http://localhost:8000/oauth/callback",
    )
    provider = FixtureProvider()
    original_add = provider.add_video
    app = create_app(settings, provider=provider)
    user = app.state.security.upsert_user("synthetic-browser-account")
    app.state.security.save_google(
        user,
        {
            "access_token": "synthetic-browser-access",
            "expires_at": time.time() + 3600,
            "scope": WRITE_SCOPE,
        },
    )
    with app.state.store.tx() as db:
        token = app.state.auth._mint(db, "browser-fixture", user, ["youtube:read"])
    cookie, csrf = app.state.security.create_session(user)
    app.state.browser_fixture = {
        "user_id": user,
        "access_token": token.access_token,
        "cookie": cookie,
        "csrf": csrf,
    }

    @app.get("/__fixture")
    async def synthetic_fixture():
        return app.state.browser_fixture

    @app.post("/__write_failure")
    async def write_failure(mode: str):
        if mode == "clear":
            provider.add_video = original_add
        else:

            async def reject(*args):
                raise AppError(
                    "quota_exceeded" if mode == "partial" else "upstream_unavailable",
                    "Synthetic Google failure",
                    429 if mode == "partial" else 503,
                    details={"source": "google", "reason": "quotaExceeded", "upstream_status": 403},
                )

            provider.add_video = reject
        return {"status": "configured"}

    @app.get("/__consent_fixture")
    async def synthetic_consent_fixture():
        redirect = "http://127.0.0.1:8000/__client_callback"
        client = OAuthClientInformationFull(
            client_id="browser-ai",
            client_name="Browser AI",
            redirect_uris=[AnyUrl(redirect)],
            scope="youtube:read",
            token_endpoint_auth_method="none",
        )
        await app.state.auth.register_client(client)
        verifier = "v" * 64
        transaction = app.state.security.create_login(
            {
                "client_id": client.client_id,
                "consent_user_id": user,
                "consent_generation": app.state.security.generation(user),
                "params": {
                    "state": "browser-state",
                    "redirect_uri": redirect,
                    "redirect_uri_provided_explicitly": True,
                    "resource": "http://localhost:8000/mcp/",
                    "scopes": ["youtube:read"],
                    "code_challenge": base64.urlsafe_b64encode(
                        hashlib.sha256(verifier.encode()).digest()
                    )
                    .decode()
                    .rstrip("="),
                },
            }
        )
        return {
            "url": "/oauth/consent?transaction=" + transaction,
            "verifier": verifier,
            "client_id": client.client_id,
            "redirect_uri": redirect,
        }

    @app.get("/__write_fixture")
    async def synthetic_write_fixture():
        tokens = app.state.security.google(user)
        tokens["scope"] = READ_SCOPE
        app.state.security.save_google(user, tokens)
        cookie, csrf = app.state.security.create_session(user)
        return {"cookie": cookie, "csrf": csrf}

    @app.get("/__client_callback")
    async def synthetic_client_callback():
        return {"status": "AI client received authorization code"}

    return app
