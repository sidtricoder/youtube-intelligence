import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

from ytintel.config import Settings
from ytintel.errors import AppError
from ytintel.quota import Quota
from ytintel.store import Store


def settings(**overrides):
    return Settings(
        _env_file=None,
        encryption_key=Fernet.generate_key().decode(),
        **overrides,
    )


def test_database_urls_are_secret_and_pooled_is_selected():
    s = settings(
        DATABASE_URL="postgresql://user:synthetic-secret@db.test/test?sslmode=require",
        DATABASE_URL_POOLED="postgresql://user:synthetic-secret@pool.test/test?sslmode=require",
    )
    assert s.database_connection.startswith("postgresql://user:synthetic-secret@pool.test")
    assert "synthetic-secret" not in repr(s)


def test_render_derives_https_callback_and_requires_postgres():
    s = settings(
        RENDER_EXTERNAL_URL="https://youtube-example.onrender.com",
        DATABASE_URL="postgresql://user:synthetic@db.test/db",
    )
    assert s.public_base_url == "https://youtube-example.onrender.com"
    assert s.redirect_uri == "https://youtube-example.onrender.com/oauth/callback"
    with pytest.raises(ValueError):
        settings(RENDER_EXTERNAL_URL="https://youtube-example.onrender.com")


def test_mismatched_cloud_callback_is_rejected_without_fallback():
    with pytest.raises(ValueError):
        settings(
            public_base_url="https://youtube-example.onrender.com",
            redirect_uri="http://localhost:8000/oauth/callback",
        )


@pytest.mark.parametrize(
    "origin",
    [
        "http://public.example",
        "https://example.test/path",
        "https://user:pass@example.test",
        "https://example.test?secret=x",
    ],
)
def test_unsafe_public_origins_are_rejected(origin):
    with pytest.raises(ValueError):
        settings(public_base_url=origin)


def test_repository_transactions_rollback_and_persist_across_reopen(tmp_path):
    path = str(tmp_path / "data.db")
    key = Fernet.generate_key().decode()
    store = Store(path, key)
    store.put("secret", {"refresh_token": "synthetic-only"})
    with pytest.raises(RuntimeError):
        with store.tx() as db:
            db.execute(text("DELETE FROM kv WHERE k=:key"), {"key": "secret"})
            raise RuntimeError("rollback")
    store.close()
    reopened = Store(path, key)
    assert reopened.get("secret") == {"refresh_token": "synthetic-only"}
    q = Quota(reopened, units=5, searches=1)
    with q.reserve(5, 1) as ticket:
        ticket.consume(2, 1)
    reopened.close()
    again = Store(path, key)
    assert Quota(again).status()["units_used"] == 2
    assert again.take("secret") and again.take("secret") is None
    again.close()


def test_invalid_database_url_does_not_select_sqlite(tmp_path):
    with pytest.raises(AppError) as exc:
        Store.from_url("mysql://user:synthetic-secret@db.test/db", Fernet.generate_key().decode())
    assert exc.value.code == "invalid_database_configuration"
    assert "synthetic-secret" not in str(exc.value)


def test_render_server_binds_platform_port_and_local_stays_loopback():
    from ytintel.server import server_options

    assert server_options({"PORT": "10000"})["host"] == "0.0.0.0"
    assert server_options({"PORT": "10000"})["port"] == 10000
    assert server_options({})["host"] == "127.0.0.1"
    with pytest.raises(ValueError):
        server_options({"PORT": "invalid"})


async def test_cloud_mcp_accepts_configured_hostname_and_rejects_other_hosts(tmp_path):
    import httpx

    from tests.fakes import FixtureProvider
    from ytintel.app import create_app

    s = settings(
        public_base_url="https://youtube-example.onrender.com", db_path=str(tmp_path / "cloud.db")
    )
    app = create_app(s, provider=FixtureProvider())
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="https://youtube-example.onrender.com"
        ) as client:
            request = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            }
            headers = {
                "Accept": "application/json, text/event-stream",
                "Origin": "https://youtube-example.onrender.com",
            }
            good = await client.post("/mcp/", headers=headers, json=request)
            assert good.status_code == 200 and "result" in good.json()
            bad = await client.post("/mcp/", headers={**headers, "Host": "evil.test"}, json=request)
            assert bad.status_code in (400, 421)


def test_empty_pooled_url_does_not_hide_configured_direct_url():
    s = settings(DATABASE_URL="postgresql://user:synthetic@db.test/db", DATABASE_URL_POOLED="")
    assert s.database_connection == "postgresql://user:synthetic@db.test/db"


def test_render_does_not_implicitly_trust_forwarded_headers():
    from ytintel.server import server_options

    options = server_options({"RENDER_EXTERNAL_URL": "https://example.onrender.com"})
    assert options["forwarded_allow_ips"] == ""
    assert options["proxy_headers"] is False


async def test_https_user_action_uses_session_csrf_and_configured_origin_behind_proxy(tmp_path):
    import httpx

    from tests.fakes import FixtureProvider
    from ytintel.app import create_app

    app = create_app(
        settings(
            public_base_url="https://cloud-example.onrender.com", db_path=str(tmp_path / "proxy.db")
        ),
        provider=FixtureProvider(),
    )
    async with app.router.lifespan_context(app):
        user = app.state.security.upsert_user("proxy-google-subject")
        cookie, csrf = app.state.security.create_session(user)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8000"
        ) as client:
            headers = {
                "Host": "cloud-example.onrender.com",
                "X-Forwarded-Proto": "http",
                "Origin": "https://cloud-example.onrender.com",
                "Cookie": "yt_session=" + cookie,
            }
            form = {"confirmation": "CREATE", "csrf": csrf}
            result = await client.post("/approve/missing", headers=headers, data=form)
            assert result.status_code == 404
            blocked = await client.post(
                "/approve/missing",
                headers={**headers, "Origin": "https://evil.test"},
                data=form,
            )
            assert blocked.status_code == 403
            wrong_csrf = await client.post(
                "/approve/missing",
                headers=headers,
                data={**form, "csrf": "wrong"},
            )
            assert wrong_csrf.status_code == 403


def test_browser_fixture_ignores_exported_production_database(monkeypatch, tmp_path):
    from tests.browser_server import create_browser_app
    from ytintel.store import Store

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:synthetic@production.invalid/db")
    monkeypatch.setenv("YT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("YT_DB_PATH", str(tmp_path / "browser.db"))
    monkeypatch.setattr(
        Store,
        "from_url",
        lambda *args, **kwargs: pytest.fail(
            "Browser fixtures must never connect to the production database"
        ),
    )
    app = create_browser_app()
    assert app.state.store.backend == "sqlite"
    app.state.store.close()
