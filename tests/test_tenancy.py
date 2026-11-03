import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import func, select

from tests.fakes import FixtureProvider
from ytintel.context import AnonymousContext, UserContext
from ytintel.domain import Constraints
from ytintel.errors import AppError
from ytintel.providers.google import GoogleProvider
from ytintel.service import Intelligence
from ytintel.store import Store
from ytintel.tenancy import PublicStore, ScopedStore
from ytintel.tenant_quota import TenantQuota


@pytest.fixture
def raw(tmp_path):
    store = Store(str(tmp_path / "tenants.db"), Fernet.generate_key().decode())
    yield store
    store.close()


async def credentials():
    return "private-token"


def service(raw, user):
    quota = TenantQuota(raw, user)
    context = UserContext(user, credentials, quota)
    return Intelligence(FixtureProvider(), ScopedStore(raw, user), quota, context=context)


async def test_drafts_and_private_cache_are_isolated(raw):
    a, b = service(raw, "alice"), service(raw, "bob")
    draft = await a.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))
    assert draft["user_id"] == "alice"
    with pytest.raises(AppError, match="Draft"):
        b.draft(draft["id"])
    a.store.put("cache:profile", {"secret": True})
    assert b.store.get("cache:profile") is None
    assert raw.get("cache:profile") is None


async def test_anonymous_preview_has_no_draft_or_user_writes(raw):
    quota = TenantQuota(raw, "ip-hash", anonymous=True)
    app = Intelligence(
        FixtureProvider(), PublicStore(raw), quota, context=AnonymousContext("127.0.0.1", quota)
    )

    async def forbidden_profile():
        pytest.fail("Anonymous preview must not access a private profile")

    app.provider.profile = forbidden_profile
    result = await app.preview(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))
    assert result["videos"] and "id" not in result
    result = await app.video_to_playlist(
        "aaaaaaaaaaa", Constraints(topic="Python", total_seconds=1800, max_seconds=1200)
    )
    assert "preview" in result and "draft" not in result
    with raw.tx() as db:
        for name in ("drafts", "tenant_cache"):
            assert (
                db.execute(select(func.count()).select_from(app.store.tables[name])).scalar_one()
                == 0
            )
        assert not db.execute(
            select(quota.ledger.c.context_key).where(
                quota.ledger.c.context_key.startswith("anonymous:")
            )
        ).first()
    with pytest.raises(AppError):
        await app.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))


def test_quota_enforces_fair_share_and_global_atomically(raw):
    a = TenantQuota(raw, "alice", units=10, user_units=3)
    b = TenantQuota(raw, "bob", units=10, user_units=3)
    with a.reserve(3, 0) as ticket:
        ticket.consume(3)
    with pytest.raises(AppError):
        with a.reserve(1, 0):
            pytest.fail("over budget")
    with b.reserve(3, 0) as ticket:
        ticket.consume(3)
    assert b.status()["units_used"] == 3
    assert a.status()["units_used"] == 3


async def test_fair_quota_rejects_before_provider(raw):
    app = service(raw, "alice")
    app.quota = TenantQuota(raw, "alice", user_units=1)

    async def forbidden(*args):
        pytest.fail("provider called")

    app.provider.search = forbidden
    with pytest.raises(AppError):
        await app.propose(Constraints(topic="Python", total_seconds=600, max_seconds=600))


async def test_public_requests_never_use_bearer_and_private_cache_is_scoped(raw):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={"items": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        for user in ("alice", "bob"):
            app = service(raw, user)
            provider = GoogleProvider(
                client,
                credentials,
                app.store,
                public_api_key="public",
                context=app.context,
                public_store=PublicStore(raw),
            )
            with app.quota.reserve(2, 0):
                await provider.request("videos", {"id": "aaaaaaaaaaa"})
                await provider.request("subscriptions", {"mine": "true"})
    assert len(requests) == 3
    assert requests[0].headers["x-goog-api-key"] == "public"
    assert "authorization" not in requests[0].headers
    assert all(r.headers["authorization"] == "Bearer private-token" for r in requests[1:])


def test_request_search_cap_is_separate_from_daily_fair_share(raw):
    quota = TenantQuota(raw, "alice")
    for _ in range(2):
        with quota.reserve(0, 3) as ticket:
            ticket.consume(searches=3)
    assert quota.status()["searches_used"] == 6
    with pytest.raises(AppError):
        with quota.reserve(0, 4):
            pytest.fail("request cap must apply")


def test_anonymous_pool_cannot_exhaust_signed_in_search_budget(raw):
    anonymous = TenantQuota(raw, "ip", searches=10, anonymous=True)
    with anonymous.reserve(0, 3) as ticket:
        ticket.consume(searches=3)
    with pytest.raises(AppError, match="sign in"):
        with TenantQuota(raw, "different-ip", searches=10, anonymous=True).reserve(0, 1):
            pytest.fail("shared anonymous pool exhausted")
    signed_in = TenantQuota(raw, "alice", searches=10)
    with signed_in.reserve(0, 3) as ticket:
        ticket.consume(searches=3)
    assert signed_in.status()["searches_used"] == 3
    assert "global" not in str(signed_in.status())


def test_tenant_quota_concurrent_global_limit_and_rollback(raw):
    from concurrent.futures import ThreadPoolExecutor

    quotas = [TenantQuota(raw, name, units=1, user_units=1) for name in ("alice", "bob")]

    def reserve(quota):
        try:
            with quota.reserve(1, 0) as ticket:
                ticket.consume(1)
            return True
        except AppError:
            return False

    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(reserve, quotas)) == 1
    assert sum(quota.status()["units_used"] for quota in quotas) == 1


def test_tenant_reservation_failure_rolls_back_global_charge(raw):
    alice = TenantQuota(raw, "alice", units=2, user_units=1)
    bob = TenantQuota(raw, "bob", units=2, user_units=1)
    with alice.reserve(1, 0) as ticket:
        ticket.consume(1)
    with pytest.raises(AppError):
        with alice.reserve(1, 0):
            pytest.fail("fair share exceeded")
    with bob.reserve(1, 0) as ticket:
        ticket.consume(1)
    assert bob.status()["units_used"] == 1


async def test_private_401_invalidates_credentials_but_public_401_does_not(raw):
    app = service(raw, "alice")
    invalidations = []

    async def invalidate():
        invalidations.append("alice")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={}))
    ) as client:
        provider = GoogleProvider(
            client,
            credentials,
            app.store,
            public_api_key="key",
            context=app.context,
            on_unauthorized=invalidate,
        )
        with app.quota.reserve(2, 0):
            with pytest.raises(AppError):
                await provider.request("subscriptions", {"mine": "true"})
            with pytest.raises(AppError):
                await provider.request("videos", {"id": "aaaaaaaaaaa"})
    assert invalidations == ["alice"]


@pytest.mark.parametrize("user_id", ["", "   ", None, 17])
def test_user_context_requires_nonempty_identity(raw, user_id):
    with pytest.raises(ValueError):
        UserContext(user_id, credentials, TenantQuota(raw, "fixture"))


async def test_public_summary_and_preview_have_metadata_links(raw):
    app = service(raw, "alice")
    summary = await app.summary("aaaaaaaaaaa")
    assert summary["basis"] == "metadata_only"
    assert summary["url"] == "https://www.youtube.com/watch?v=aaaaaaaaaaa"
    result = await app.preview(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))
    assert result["ranking"][0]["url"].startswith("https://www.youtube.com/watch?v=")
    assert result["analysis"]["sample_count"] == len(result["videos"])


@pytest.mark.parametrize("operation", ["get", "put", "take", "transition", "delete_prefix"])
def test_stale_scoped_store_refuses_operations_after_revocation(raw, operation):
    from ytintel.security.store import SecurityStore

    security = SecurityStore(raw)
    user = security.upsert_user("google-alice")
    security.save_google(user, {"access_token": "synthetic-access"})
    stale = ScopedStore(raw, user)
    stale.put("draft:pending", {"status": "pending"})
    security.revoke_user(user)
    arguments = {
        "get": ("draft:pending",),
        "put": ("draft:new", {"status": "pending"}),
        "take": ("draft:pending",),
        "transition": ("draft:pending", "pending", "writing"),
        "delete_prefix": ("draft:",),
    }
    with pytest.raises(AppError) as error:
        getattr(stale, operation)(*arguments[operation])
    assert error.value.code == "reauthorization_required"
    assert error.value.status == 401


def test_scoped_store_generation_isolated_and_public_store_unaffected(raw):
    from ytintel.security.store import SecurityStore

    security = SecurityStore(raw)
    alice = security.upsert_user("google-alice")
    bob = security.upsert_user("google-bob")
    security.save_google(alice, {"access_token": "synthetic-a"})
    security.save_google(bob, {"access_token": "synthetic-b"})
    a, b, public = ScopedStore(raw, alice), ScopedStore(raw, bob), PublicStore(raw)
    b.put("cache:private", {"owner": "bob"})
    security.save_google(alice, {"access_token": "fresh-a"})
    with pytest.raises(AppError):
        a.put("cache:stale", {})
    assert b.get("cache:private") == {"owner": "bob"}
    public.put("cache:public", {"metadata": True})
    assert public.get("cache:public") == {"metadata": True}
    fresh = ScopedStore(raw, alice)
    fresh.put("draft:fresh", {"status": "pending"})
    assert fresh.get("draft:fresh")["status"] == "pending"


def test_deleted_user_invalidates_scoped_store(raw):
    from sqlalchemy import delete

    from ytintel.security.store import SecurityStore

    security = SecurityStore(raw)
    user = security.upsert_user("google-alice")
    stale = ScopedStore(raw, user)
    with raw.tx() as db:
        db.execute(delete(security.users).where(security.users.c.user_id == user))
    with pytest.raises(AppError) as error:
        stale.put("draft:forbidden", {})
    assert error.value.code == "reauthorization_required"


def test_explicit_anonymous_budget_scales_search_budget(raw):
    quota = TenantQuota(raw, "public", units=10, searches=3, anonymous_units=10, anonymous=True)
    assert quota.status()["searches_limit"] == 3
    with quota.reserve(1, 1) as ticket:
        ticket.consume(1, 1)
    assert quota.status()["searches_used"] == 1


async def test_context_snapshot_cannot_create_fresh_store_after_disconnect(raw):
    from ytintel.security.store import SecurityStore

    security = SecurityStore(raw)
    user = security.upsert_user("google-alice")
    security.save_google(user, {"access_token": "synthetic-access"})
    generation = security.generation(user)
    context = UserContext(user, credentials, TenantQuota(raw, user), generation=generation)
    security.revoke_user(user)
    stale = ScopedStore(raw, context.user_id, generation=context.generation)
    with pytest.raises(AppError) as error:
        stale.put("draft:after-disconnect", {"status": "pending"})
    assert error.value.code == "reauthorization_required"
    with pytest.raises(AppError):
        stale.get("cache:private")


def test_quota_ledger_has_explicit_user_id_for_ownership(tmp_path):
    raw = Store(str(tmp_path / "ledger.db"), Fernet.generate_key().decode())
    quota = TenantQuota(raw, "alice")
    with quota.reserve(1, 0) as ticket:
        ticket.consume(1, 0)
    assert "user_id" in quota.ledger.c
    from sqlalchemy import select

    with raw.tx() as db:
        row = (
            db.execute(select(quota.ledger).where(quota.ledger.c.context_key == "user:alice"))
            .mappings()
            .one()
        )
    assert row["user_id"] == "alice"
    raw.close()
