"""Browser-test composition only. Production has no synthetic runtime mode."""

import os
import tempfile
import time
from pathlib import Path

from cryptography.fernet import Fernet

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.identity import WRITE_SCOPE


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
    app = create_app(settings, provider=FixtureProvider())
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

    return app
