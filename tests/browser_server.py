"""Browser-test composition only. Production has no synthetic runtime mode."""

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings


def create_browser_app():
    settings = Settings(
        _env_file=None,
        database_url=None,
        database_url_pooled=None,
        render_external_url="",
        public_base_url="",
        redirect_uri="http://localhost:8000/oauth/callback",
    )
    app = create_app(settings, provider=FixtureProvider())
    app.state.service.store.put("oauth:tokens", {"write": True})
    return app
