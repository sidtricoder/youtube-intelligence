import httpx
import pytest
from cryptography.fernet import Fernet

from ytintel.context import UserContext
from ytintel.errors import AppError
from ytintel.identity import GoogleIdentityProvider
from ytintel.providers.google import GoogleProvider
from ytintel.quota import Quota
from ytintel.security.store import SecurityStore
from ytintel.store import Store
from ytintel.tenancy import ScopedStore


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "test.db"), Fernet.generate_key().decode())


def test_encrypted_storage_expiry_and_single_use(store):
    store.put("token", {"refresh_token": "SYNTHETIC-SECRET"}, ttl=60)
    assert store.get("token")["refresh_token"] == "SYNTHETIC-SECRET"
    assert b"SYNTHETIC-SECRET" not in open(store.path, "rb").read()
    assert store.take("token") and store.take("token") is None
    store.put("old", {"x": 1}, ttl=-1)
    assert store.get("old") is None


def test_quota_reserves_before_any_call_and_refunds_unused(store):
    q = Quota(store, units=10, searches=2)
    with q.reserve(8, 1) as ticket:
        ticket.consume(3, 1)
        with pytest.raises(AppError, match="quota"):
            with q.reserve(3, 0):
                pass
    assert q.status()["units_used"] == 3
    assert q.status()["searches_used"] == 1


@pytest.mark.parametrize(
    "reason,status,code",
    [
        ("quotaExceeded", 403, "quota_exceeded"),
        ("youtubeSignupRequired", 403, "channel_required"),
        ("rateLimitExceeded", 403, "rate_limited"),
        ("forbidden", 403, "forbidden"),
        ("notFound", 404, "not_found"),
        ("backendError", 503, "upstream_unavailable"),
    ],
)
async def test_upstream_error_mapping(store, reason, status, code):
    transport = httpx.MockTransport(
        lambda r: httpx.Response(status, json={"error": {"errors": [{"reason": reason}]}})
    )
    provider = GoogleProvider(
        httpx.AsyncClient(transport=transport),
        lambda: token(),
        store,
        public_api_key="synthetic-key",
    )
    with Quota(store).reserve(5, 1):
        with pytest.raises(AppError) as e:
            await provider.videos(["aaaaaaaaaaa"])
    assert e.value.code == code


async def token():
    return "synthetic-token"


async def test_search_batch_details_cache_and_charge(store):
    calls = []

    def handler(r):
        calls.append(r)
        if r.url.path.endswith("/search"):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "aaaaaaaaaaa"}}]})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "aaaaaaaaaaa",
                        "snippet": {
                            "title": "Python",
                            "channelId": "UC" + "a" * 22,
                            "channelTitle": "Test",
                        },
                        "contentDetails": {"duration": "PT10M"},
                    }
                ]
            },
        )

    p = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        lambda: token(),
        store,
        public_api_key="synthetic-key",
    )
    q = Quota(store)
    with q.reserve(5, 2):
        assert (await p.search("python"))[0].seconds == 600
        await p.search("python")
    assert len(calls) == 2
    assert q.status()["units_used"] == 1 and q.status()["searches_used"] == 1


async def test_expired_access_refresh_and_invalid_grant(store):
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(400, json={"error": "invalid_grant"})
        )
    )
    identity = GoogleIdentityProvider(client, "id", "secret", "https://app.test/oauth/callback")
    with pytest.raises(AppError) as error:
        await identity.refresh("synthetic-refresh")
    assert error.value.code == "reauthorization_required"


def test_oauth_state_is_bound_and_consumed(store):
    security = SecurityStore(store)
    state = security.create_login({"binding": "synthetic-browser", "nonce": "nonce"})
    assert security.get_login(state)["binding"] == "synthetic-browser"
    assert security.take_login(state)["nonce"] == "nonce"
    assert security.take_login(state) is None


async def test_profile_pagination_sample_and_missing_private_videos(store):
    calls = []

    def handler(r):
        calls.append(r)
        end = r.url.path.split("/")[-1]
        if end == "videos" and "myRating" in r.url.params:
            return httpx.Response(200, json={"items": []})
        if end == "subscriptions":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "snippet": {
                                "title": "Example",
                                "resourceId": {"channelId": "UC" + "a" * 22},
                                "publishedAt": "2026-10-01T00:00:00Z",
                            }
                        }
                    ]
                },
            )
        if end == "playlists":
            return httpx.Response(200, json={"items": [{"id": "synthetic-playlist"}]})
        if end == "playlistItems":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "contentDetails": {"videoId": "aaaaaaaaaaa"},
                            "snippet": {"publishedAt": "2026-10-01T00:00:00Z"},
                        },
                        {
                            "contentDetails": {"videoId": "zzzzzzzzzzz"},
                            "snippet": {"title": "Private video"},
                        },
                    ],
                    "nextPageToken": "another",
                },
            )
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "aaaaaaaaaaa",
                        "snippet": {
                            "title": "Python",
                            "channelId": "UC" + "a" * 22,
                            "channelTitle": "Example",
                        },
                        "contentDetails": {"duration": "PT5M"},
                    }
                ]
            },
        )

    p = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        lambda: token(),
        store,
        public_api_key="synthetic-key",
    )
    with Quota(store).reserve(45, 0):
        profile = await p.profile()
    assert profile["truncated"] is True
    assert len(profile["subscriptions"]) == 1
    assert all(e["video"]["id"] == "aaaaaaaaaaa" for e in profile["events"])
    assert len(calls) <= 45


async def test_google_credentials_and_sessions_disconnect_only_one_user(store):
    security = SecurityStore(store)
    alice, bob = security.upsert_user("google-a"), security.upsert_user("google-b")
    security.save_google(alice, {"access_token": "account-a"})
    security.save_google(bob, {"access_token": "account-b"})
    a_session, _ = security.create_session(alice)
    b_session, _ = security.create_session(bob)
    security.revoke_user(alice)
    assert security.google(alice) is None and security.session(a_session) is None
    assert security.google(bob)["access_token"] == "account-b"
    assert security.session(b_session)["user_id"] == bob


@pytest.mark.parametrize("status,code", [(401, "reauthorization_required"), (429, "rate_limited")])
async def test_http_errors(store, status, code):
    p = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, json={}))),
        lambda: token(),
        store,
        public_api_key="synthetic-key",
    )
    with Quota(store).reserve(1, 0):
        with pytest.raises(AppError) as e:
            await p.videos(["aaaaaaaaaaa"])
    assert e.value.code == code


async def test_provider_network_timeout_charged_no_retry(store):
    calls = []

    def handler(r):
        calls.append(r)
        raise httpx.ReadTimeout("synthetic timeout")

    p = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        lambda: token(),
        store,
        public_api_key="synthetic-key",
    )
    q = Quota(store)
    with q.reserve(50, 0):
        with pytest.raises(AppError):
            await p.create_playlist("Example")
    assert len(calls) == 1 and q.status()["units_used"] == 50


def test_atomic_transition_and_quota_concurrency(store):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    store.put("draft:x", {"status": "pending"})
    with ThreadPoolExecutor(4) as pool:
        results = list(
            pool.map(lambda _: store.transition("draft:x", "pending", "writing"), range(4))
        )
    assert sum(r is not None for r in results) == 1
    gate = threading.Barrier(2)
    q = Quota(store, units=1, searches=0)

    def run(_):
        gate.wait()
        try:
            with q.reserve(1, 0) as ticket:
                ticket.consume(1, 0)
            return True
        except AppError:
            return False

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, range(2)))
    assert sum(results) == 1


async def test_reauthorization_does_not_mix_account_tokens_cache_or_drafts(store):
    security = SecurityStore(store)
    alice, bob = security.upsert_user("google-a"), security.upsert_user("google-b")
    security.save_google(alice, {"access_token": "a", "refresh_token": "a-refresh"})
    security.save_google(bob, {"access_token": "b"})
    a, b = ScopedStore(store, alice), ScopedStore(store, bob)
    a.put("cache:profile", {"account": "a"})
    a.put("draft:pending", {"status": "pending", "user_id": alice})
    assert security.google(bob).get("refresh_token") is None
    assert b.get("cache:profile") is None and b.get("draft:pending") is None
    assert a.get("cache:profile")["account"] == "a"


async def test_parallel_workflows_keep_immutable_request_identity(store):
    import asyncio

    from tests.fakes import FixtureProvider
    from ytintel.domain import Constraints
    from ytintel.service import Intelligence

    entered, release = asyncio.Event(), asyncio.Event()
    provider = FixtureProvider()
    original = provider.search

    async def blocked(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    provider.search = blocked
    quota = Quota(store)
    alice = Intelligence(
        provider, ScopedStore(store, "alice"), quota, context=UserContext("alice", token, quota)
    )
    proposal = asyncio.create_task(
        alice.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=900))
    )
    await entered.wait()
    bob = Intelligence(
        FixtureProvider(),
        ScopedStore(store, "bob"),
        quota,
        context=UserContext("bob", token, quota),
    )
    bob_draft = await bob.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=900))
    release.set()
    alice_draft = await proposal
    assert alice_draft["user_id"] == "alice" and bob_draft["user_id"] == "bob"
    with pytest.raises(AppError):
        bob.draft(alice_draft["id"])


async def test_channel_lookup_ranking_adapter_and_private_write_bodies(store):
    calls = []

    def handler(r):
        calls.append(r)
        end = r.url.path.split("/")[-1]
        if r.method == "POST":
            return httpx.Response(200, json={"id": "synthetic-playlist"})
        if end == "search":
            return httpx.Response(200, json={"items": [{"id": {"channelId": "UC" + "a" * 22}}]})
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "UC" + "a" * 22,
                        "snippet": {"title": "Python", "description": "Learn Python"},
                        "brandingSettings": {"channel": {"keywords": "python"}},
                    }
                ]
            },
        )

    import json

    p = GoogleProvider(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        lambda: token(),
        store,
        public_api_key="synthetic-key",
    )
    with Quota(store).reserve(102, 1):
        assert (await p.channel("@pythonlab"))["title"] == "Python"
        assert (await p.search_channels("python"))[0]["keywords"] == "python"
        playlist = await p.create_playlist("Python")
        await p.add_video(playlist, "aaaaaaaaaaa")
    assert calls[0].url.params["forHandle"] == "@pythonlab"
    writes = [json.loads(r.content) for r in calls if r.method == "POST"]
    assert writes[0]["status"]["privacyStatus"] == "private"
    assert writes[1]["snippet"]["resourceId"]["videoId"] == "aaaaaaaaaaa"


def test_quota_day_reset_is_separate_and_zero_charge_on_reservation_failure(store):
    q = Quota(store, units=1, searches=1)
    q.day = lambda: "2026-11-01"
    with q.reserve(1, 1) as ticket:
        ticket.consume(1, 1)
    with pytest.raises(AppError):
        with q.reserve(1, 0):
            pass
    q.day = lambda: "2026-11-02"
    assert q.status()["units_used"] == 0
