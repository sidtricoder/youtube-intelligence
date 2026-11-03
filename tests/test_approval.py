import time

import httpx
import pytest
from cryptography.fernet import Fernet

from tests.fakes import FixtureProvider
from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.domain import Constraints
from ytintel.identity import WRITE_SCOPE


@pytest.fixture
async def setup_app(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            db_path=str(tmp_path / "db"),
            encryption_key=Fernet.generate_key().decode(),
        ),
        provider=FixtureProvider(),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as c:
        yield app, c
    app.state.store.close()


async def test_approval_own_session_csrf_exact_confirmation_and_escape(setup_app):
    app, c = setup_app
    user = app.state.security.upsert_user("account-a")
    app.state.security.save_google(
        user, {"access_token": "synthetic", "scope": WRITE_SCOPE, "expires_at": time.time() + 3600}
    )
    context = await app.state.context_factory(
        type("Verified", (), {"user_id": user})(), "127.0.0.1"
    )
    service = app.state.service_factory(context)
    d = await service.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))
    d["videos"][0]["title"] = "<script>alert(1)</script>"
    service.save(d)
    opaque, csrf = app.state.security.create_session(user)
    c.cookies.set("yt_session", opaque)
    page = await c.get("/approve/" + d["id"])
    assert page.status_code == 200 and "&lt;script&gt;" in page.text and "<script>" not in page.text
    for form in ({"confirmation": "CREATE"}, {"csrf": csrf, "confirmation": "yes"}):
        assert (await c.post("/approve/" + d["id"], data=form)).status_code == 403
    assert not service.provider.created
    result = await c.post("/approve/" + d["id"], data={"csrf": csrf, "confirmation": "CREATE"})
    assert result.status_code == 200 and result.json()["status"] == "complete"
    assert len(service.provider.created) == 1
    assert (
        await c.post("/approve/" + d["id"], data={"csrf": csrf, "confirmation": "CREATE"})
    ).status_code == 409


async def test_other_user_cannot_infer_draft_and_bearer_cannot_approve(setup_app):
    app, c = setup_app
    a, b = [app.state.security.upsert_user(x) for x in ("a", "b")]
    for user in (a, b):
        app.state.security.save_google(
            user,
            {"access_token": "synthetic", "scope": WRITE_SCOPE, "expires_at": time.time() + 3600},
        )
    ctx = await app.state.context_factory(type("Verified", (), {"user_id": a})(), "127.0.0.1")
    d = await app.state.service_factory(ctx).propose(
        Constraints(topic="Python", total_seconds=1800, max_seconds=1200)
    )
    opaque, csrf = app.state.security.create_session(b)
    c.cookies.set("yt_session", opaque)
    r = await c.get("/approve/" + d["id"])
    missing = await c.get("/approve/missing")
    assert r.status_code == missing.status_code == 404 and r.json() == missing.json()
    assert (
        await c.post("/approve/" + d["id"], data={"csrf": csrf, "confirmation": "CREATE"})
    ).status_code == 404
    c.cookies.clear()
    assert (
        await c.post(
            "/approve/" + d["id"],
            headers={"Authorization": "Bearer fake"},
            data={"confirmation": "CREATE"},
        )
    ).status_code == 401


async def test_write_step_up_callback_cannot_restore_disconnected_account(tmp_path):
    import asyncio
    from urllib.parse import parse_qs, urlparse

    from ytintel.identity import READ_SCOPE, GoogleIdentity

    entered, release = asyncio.Event(), asyncio.Event()

    class IdP:
        def authorization_url(self, state, nonce, verifier, write=False):
            return "http://localhost:8000/fake?state=" + state

        async def exchange(self, code, verifier, nonce):
            entered.set()
            await release.wait()
            return GoogleIdentity(
                "account-a",
                {
                    "access_token": "late-write-grant",
                    "scope": WRITE_SCOPE,
                    "expires_at": time.time() + 3600,
                },
            )

    app = create_app(
        Settings(
            _env_file=None,
            encryption_key=Fernet.generate_key().decode(),
            db_path=str(tmp_path / "db"),
        ),
        provider=FixtureProvider(),
        identity_provider=IdP(),
    )
    user = app.state.security.upsert_user("account-a")
    app.state.security.save_google(
        user, {"access_token": "read", "scope": READ_SCOPE, "expires_at": time.time() + 3600}
    )
    context = await app.state.context_factory(
        type("Verified", (), {"user_id": user})(), "127.0.0.1"
    )
    draft = await app.state.service_factory(context).propose(
        Constraints(topic="Python", total_seconds=1800, max_seconds=900), exclude_saved=False
    )
    opaque, csrf = app.state.security.create_session(user)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000"
    ) as c:
        c.cookies.set("yt_session", opaque)
        begin = await c.post("/approve/" + draft["id"] + "/enable-writes", data={"csrf": csrf})
        google = await c.get(begin.headers["location"])
        state = parse_qs(urlparse(google.headers["location"]).query)["state"][0]
        callback = asyncio.create_task(
            c.get("/oauth/callback", params={"state": state, "code": "fake"})
        )
        await entered.wait()
        await app.state.credentials.disconnect(user)
        release.set()
        response = await callback
        assert response.status_code == 401
        assert app.state.security.google(user) is None
        assert app.state.security.session(opaque) is None
        assert "yt_session=" not in response.headers.get("set-cookie", "")
    app.state.store.close()


async def test_authenticated_context_cannot_create_draft_after_disconnect(setup_app):
    from ytintel.errors import AppError

    app, _ = setup_app
    user = app.state.security.upsert_user("account-a")
    app.state.security.save_google(
        user, {"access_token": "synthetic", "expires_at": time.time() + 3600}
    )
    context = await app.state.context_factory(
        type("Verified", (), {"user_id": user})(), "127.0.0.1"
    )
    await app.state.credentials.disconnect(user)
    with pytest.raises(AppError) as error:
        await app.state.service_factory(context).propose(
            Constraints(topic="Python", total_seconds=1800, max_seconds=900)
        )
    assert error.value.status == 401
    assert app.state.security.google(user) is None
    with pytest.raises(AppError):
        await app.state.context_factory(type("Verified", (), {"user_id": user})(), "127.0.0.1")
