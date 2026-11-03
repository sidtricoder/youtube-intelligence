import time

import pytest
from cryptography.fernet import Fernet

from ytintel.credentials import Credentials
from ytintel.errors import AppError
from ytintel.security import SecurityStore
from ytintel.store import Store


async def test_refresh_revocation_is_per_user(tmp_path):
    store = SecurityStore(Store(str(tmp_path / "db"), Fernet.generate_key().decode()))
    a, b = store.upsert_user("a"), store.upsert_user("b")
    for user in (a, b):
        store.save_google(
            user,
            {"access_token": "synthetic", "refresh_token": "synthetic-refresh", "expires_at": 0},
        )

    class IdP:
        async def refresh(self, token):
            raise AppError("reauthorization_required", "Sign in again", 401)

    credentials = Credentials(store, IdP())
    session_a, _ = store.create_session(a)
    session_b, _ = store.create_session(b)
    with pytest.raises(AppError):
        await credentials.access(a)
    assert store.google(a) is None and store.session(session_a) is None
    assert store.google(b) and store.session(session_b)


async def test_refresh_preserves_scope_and_missing_refresh_token(tmp_path):
    store = SecurityStore(Store(str(tmp_path / "db"), Fernet.generate_key().decode()))
    user = store.upsert_user("a")
    store.save_google(
        user, {"refresh_token": "synthetic-refresh", "scope": "read", "expires_at": 0}
    )

    class IdP:
        async def refresh(self, token):
            return {"access_token": "new-synthetic", "expires_at": time.time() + 3600, "scope": ""}

    credentials = Credentials(store, IdP())
    assert await credentials.access(user) == "new-synthetic"
    assert store.google(user)["scope"] == "read"
    assert store.google(user)["refresh_token"] == "synthetic-refresh"


async def test_refresh_cannot_restore_disconnected_or_replaced_grant(tmp_path):
    import asyncio

    store = SecurityStore(Store(str(tmp_path / "db"), Fernet.generate_key().decode()))
    user = store.upsert_user("a")
    entered, release = asyncio.Event(), asyncio.Event()

    class IdP:
        async def refresh(self, token):
            entered.set()
            await release.wait()
            return {"access_token": "late", "expires_at": time.time() + 3600}

    for replacement in (None, {"access_token": "new-login", "expires_at": time.time() + 3600}):
        entered.clear()
        release.clear()
        store.save_google(user, {"refresh_token": "old", "expires_at": 0})
        credentials = Credentials(store, IdP())
        task = asyncio.create_task(credentials.access(user))
        await entered.wait()
        store.revoke_user(user)
        if replacement:
            store.save_google(user, replacement)
        release.set()
        with pytest.raises(AppError):
            await task
        assert store.google(user) == replacement


async def test_stale_google_error_does_not_revoke_new_login(tmp_path):
    import asyncio

    store = SecurityStore(Store(str(tmp_path / "db"), Fernet.generate_key().decode()))
    user = store.upsert_user("a")
    store.save_google(user, {"refresh_token": "old", "expires_at": 0})
    entered, release = asyncio.Event(), asyncio.Event()

    class IdP:
        async def refresh(self, token):
            entered.set()
            await release.wait()
            raise AppError("reauthorization_required", "Expired", 401)

    credentials = Credentials(store, IdP())
    task = asyncio.create_task(credentials.access(user))
    await entered.wait()
    store.save_google(user, {"access_token": "new-login", "expires_at": time.time() + 3600})
    release.set()
    with pytest.raises(AppError):
        await task
    assert store.google(user)["access_token"] == "new-login"
