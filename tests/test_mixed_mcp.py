"""HTTP authorization preflight, refresh replay and anonymous abuse boundaries."""

import httpx
import pytest

from tests.wire_helpers import call, login, mcp_session, rpc, running_server, tool
from ytintel.security.store import digest


@pytest.fixture
def server(tmp_path):
    with running_server(tmp_path) as wire:
        yield wire


@pytest.mark.parametrize(
    "name,arguments",
    [
        ("recommendations", {}),
        ("engagement_analysis", {}),
        ("create_playlist_draft", {"topic": "Python", "total_seconds": 1800, "max_seconds": 900}),
        ("playlist_status", {"draft_id": "missing"}),
    ],
)
async def test_protected_calls_are_http_challenges_before_dispatch(server, name, arguments):
    response = await rpc(server, tool(name, arguments))
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == server.challenge
    assert server.providers == {}


async def test_mixed_batch_is_preflighted_atomically(server):
    response = await rpc(
        server, [tool("similar_videos", {"video": "aaaaaaaaaaa"}), tool("recommendations", ident=2)]
    )
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == server.challenge
    assert server.providers == {}
    resource = await rpc(
        server,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "resources/read",
            "params": {"uri": "ytintel://quota"},
        },
    )
    assert resource.status_code == 401
    assert resource.headers["www-authenticate"] == server.challenge


async def test_bad_expired_revoked_wrong_audience_reject_even_public(server):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        credentials = await login(server, browser, "alice")
        token = credentials["access_token"]
        security = server.app.state.security
        original = security._get(security.access_tokens, digest(token))
        for header in ("Bearer bad", "Basic invalid"):
            result = await rpc(
                server,
                tool("video_summary", {"video": "aaaaaaaaaaa"}),
                headers={"Authorization": header},
            )
            assert (
                result.status_code == 401 and result.headers["www-authenticate"] == server.challenge
            )
        security._put(
            security.access_tokens, digest(token), original, -1, user_id=original["user_id"]
        )
        expired = await rpc(server, tool("video_summary", {"video": "aaaaaaaaaaa"}), token)
        assert (
            expired.status_code == 401 and expired.headers["www-authenticate"] == server.challenge
        )
        security._put(
            security.access_tokens,
            digest(token),
            {**original, "resource": "https://other.invalid/mcp/"},
            3600,
            user_id=original["user_id"],
        )
        wrong = await rpc(server, tool("video_summary", {"video": "aaaaaaaaaaa"}), token)
        assert wrong.status_code == 401 and wrong.headers["www-authenticate"] == server.challenge
        security._put(
            security.access_tokens, digest(token), original, 3600, user_id=original["user_id"]
        )
        security._put(
            security.token_families,
            original["family"],
            {"revoked": True},
            3600,
            user_id=original["user_id"],
        )
        result = await rpc(server, tool("video_summary", {"video": "aaaaaaaaaaa"}), token)
        assert result.status_code == 401 and result.headers["www-authenticate"] == server.challenge
        assert not server.providers


async def test_real_refresh_rotation_replay_revokes_entire_family(server):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        a = await login(server, browser, "alice")
        fields = {
            "grant_type": "refresh_token",
            "client_id": a["client_id"],
            "refresh_token": a["refresh_token"],
            "resource": server.origin + "/mcp/",
        }
        rotated = await browser.post("/token", data=fields)
        assert rotated.status_code == 200, rotated.text
        new = rotated.json()
        assert new["access_token"] != a["access_token"]
        assert new["refresh_token"] != a["refresh_token"]
        async with mcp_session(server, new["access_token"]) as session:
            assert (await call(session, "recommendations"))["profile"]
        replay = await browser.post("/token", data=fields)
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        for token in (a["access_token"], new["access_token"]):
            rejected = await rpc(server, tool("video_summary", {"video": "aaaaaaaaaaa"}), token)
            assert rejected.status_code == 401
            assert rejected.headers["www-authenticate"] == server.challenge
        latest = await browser.post(
            "/token", data={**fields, "refresh_token": new["refresh_token"]}
        )
        assert latest.status_code == 400 and latest.json()["error"] == "invalid_grant"


async def test_anonymous_calls_are_not_rate_limited_and_users_work(tmp_path):
    with running_server(tmp_path, anonymous_rate_limit=2) as wire:
        message = tool("video_summary", {"video": "aaaaaaaaaaa"})
        for ip in ("198.51.100.1", "198.51.100.2"):
            response = await rpc(wire, message, headers={"X-Forwarded-For": ip})
            assert response.status_code == 200
        denied = await rpc(wire, message, headers={"X-Forwarded-For": "198.51.100.3"})
        assert denied.status_code == 200
        assert len(wire.providers["public"].calls) == 3
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as browser:
            signed = await login(wire, browser, "alice")
            async with mcp_session(wire, signed["access_token"]) as session:
                assert (await call(session, "recommendations"))["profile"]


async def test_anonymous_daily_budget_setting_is_ignored(tmp_path):
    with running_server(tmp_path, anonymous_units_per_day=1) as wire:
        message = tool("video_summary", {"video": "aaaaaaaaaaa"})
        first = await rpc(wire, message, headers={"X-Forwarded-For": "198.51.100.1"})
        assert first.status_code == 200 and "metadata_only" in first.text
        second = await rpc(wire, message, headers={"X-Forwarded-For": "198.51.100.2"})
        assert second.status_code == 200 and "metadata_only" in second.text
        assert wire.providers["public"].calls == ["videos", "videos"]
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as browser:
            signed = await login(wire, browser, "bob")
            async with mcp_session(wire, signed["access_token"]) as session:
                assert (await call(session, "video_summary", {"video": "aaaaaaaaaaa"}))[
                    "basis"
                ] == "metadata_only"


async def test_public_client_revocation_over_http(server):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        grant = await login(server, browser, "alice")
        response = await browser.post(
            "/revoke",
            data={
                "client_id": grant["client_id"],
                "token": grant["access_token"],
                "token_type_hint": "access_token",
            },
        )
        assert response.status_code == 200, response.text
        denied = await rpc(
            server, tool("video_summary", {"video": "aaaaaaaaaaa"}), grant["access_token"]
        )
        assert denied.status_code == 401 and denied.headers["www-authenticate"] == server.challenge


async def test_insufficient_scope_and_malformed_batch_fail_before_provider(server):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        grant = await login(server, browser, "alice")
        security = server.app.state.security
        original = security._get(security.access_tokens, digest(grant["access_token"]))
        security._put(
            security.access_tokens,
            digest(grant["access_token"]),
            {**original, "scopes": []},
            3600,
            user_id=original["user_id"],
        )
        denied = await rpc(server, tool("recommendations"), grant["access_token"])
        assert denied.status_code == 403
        assert (
            denied.headers["www-authenticate"]
            == 'Bearer error="insufficient_scope", scope="youtube:read"'
        )
        for message in (
            [],
            [tool("video_summary", {"video": "aaaaaaaaaaa"}), None],
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": []},
        ):
            malformed = await rpc(server, message)
            assert malformed.status_code == 400
        assert not server.providers


async def test_authorization_requires_s256_resource_and_registered_redirect(server):
    import base64
    import hashlib

    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        registration = await browser.post(
            "/register",
            json={
                "redirect_uris": ["http://127.0.0.1:9876/client-callback"],
                "token_endpoint_auth_method": "none",
                "scope": "youtube:read",
            },
        )
        assert registration.status_code == 201
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(b"a" * 64).digest()).rstrip(b"=").decode()
        )
        valid = {
            "client_id": registration.json()["client_id"],
            "response_type": "code",
            "redirect_uri": "http://127.0.0.1:9876/client-callback",
            "scope": "youtube:read",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": server.origin + "/mcp/",
        }
        for changes in (
            {"code_challenge_method": "plain"},
            {"resource": ""},
            {"resource": "https://other.invalid/mcp/"},
            {"redirect_uri": "http://127.0.0.1:9876/unregistered"},
        ):
            denied = await browser.get("/authorize", params={**valid, **changes})
            assert denied.status_code == 400, denied.text
        assert not server.idp.pending and not server.providers


async def test_write_stepup_rejects_other_google_subject_without_replacing_tokens(server):
    from tests.wire_helpers import csrf, query

    async with (
        httpx.AsyncClient(base_url=server.origin, trust_env=False) as alice,
        httpx.AsyncClient(base_url=server.origin, trust_env=False) as bob,
    ):
        a, b = await login(server, alice, "alice"), await login(server, bob, "bob")
        security = server.app.state.security
        a_token = security._get(security.access_tokens, digest(a["access_token"]))
        b_token = security._get(security.access_tokens, digest(b["access_token"]))
        before = [security.google(t["user_id"]) for t in (a_token, b_token)]
        async with mcp_session(server, a["access_token"]) as session:
            draft = await call(
                session,
                "create_playlist_draft",
                {"topic": "Python", "total_seconds": 1800, "max_seconds": 900},
            )
            path = "/approve/" + draft["id"]
            page = await alice.get(path)
            enabled = await alice.post(path + "/enable-writes", data={"csrf": csrf(page)})
            started = await alice.get(enabled.headers["location"])
            state = query(started.headers["location"])["state"]
            rejected = await alice.get("/oauth/callback", params={"state": state, "code": "bob"})
            assert (
                rejected.status_code == 403
                and rejected.json()["error"]["code"] == "account_mismatch"
            )
            assert [security.google(t["user_id"]) for t in (a_token, b_token)] == before
            assert (await call(session, "playlist_status", {"draft_id": draft["id"]}))[
                "status"
            ] == "pending"
            assert all(not p.created for p in server.providers.values())


async def test_public_batch_uses_real_mcp_transport(server):
    response = await rpc(
        server,
        [
            tool("video_summary", {"video": "aaaaaaaaaaa"}, ident=1),
            tool("similar_channels", {"channel": "@pythonlab"}, ident=2),
        ],
    )
    assert response.status_code == 200, response.text
    rows = response.json()
    assert {r["id"] for r in rows} == {1, 2}
    assert all("result" in row for row in rows)


async def test_revoked_google_grant_challenges_and_revokes_only_that_account(server):
    import time

    from ytintel.errors import AppError

    async with (
        httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser_a,
        httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser_b,
    ):
        alice = await login(server, browser_a, "alice")
        bob = await login(server, browser_b, "bob")
        access = await server.app.state.auth.load_access_token(alice["access_token"])
        tokens = server.app.state.security.google(access.user_id)
        tokens["expires_at"] = time.time() - 1
        # Simulate expiry without a fresh login/generation replacement.
        assert server.app.state.security.save_google_if_current(
            access.user_id, server.app.state.security.google(access.user_id), tokens
        )

        async def revoked(refresh_token):
            raise AppError("reauthorization_required", "Google grant expired or revoked", 401)

        server.idp.refresh = revoked
        response = await rpc(
            server, tool("video_summary", {"video": "aaaaaaaaaaa"}), alice["access_token"]
        )
        assert (
            response.status_code == 401 and response.headers["www-authenticate"] == server.challenge
        )
        assert await server.app.state.auth.load_access_token(alice["access_token"]) is None
        assert (
            await rpc(server, tool("video_summary", {"video": "aaaaaaaaaaa"}), bob["access_token"])
        ).status_code == 200


async def test_initial_connection_requests_write_permission_and_long_draft_needs_no_step_up(server):
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        grant = await login(server, browser, "alice")
        assert server.idp.exchanges == [("alice", True)]
        async with mcp_session(server, grant["access_token"]) as session:
            await call(session, "video_summary", {"video": "aaaaaaaaaaa"})
            provider = server.providers["alice"]
            provider.items = [v.model_copy(update={"seconds": 12 * 3600}) for v in provider.items]
            draft = await call(
                session, "create_playlist_draft", {"topic": "Python", "exclude_saved": False}
            )
            assert draft["total_seconds"] > 14400
            assert draft["constraints"]["total_seconds"] is None
            page = await browser.get("/approve/" + draft["id"])
            assert (
                "Confirm playlist in my account" in page.text and "enable-writes" not in page.text
            )
            assert provider.created == []
            from tests.wire_helpers import csrf

            approved = await browser.post(
                "/approve/" + draft["id"], data={"csrf": csrf(page), "confirmation": "CREATE"}
            )
            assert approved.status_code == 200 and approved.json()["status"] == "complete"
            assert server.idp.exchanges == [("alice", True)]


async def test_user_declining_write_scope_keeps_read_access_and_can_explicitly_reauthorize(server):
    from tests.wire_helpers import csrf

    server.idp.decline_write = True
    async with httpx.AsyncClient(base_url=server.origin, trust_env=False) as browser:
        grant = await login(server, browser, "alice")
        assert server.idp.exchanges == [("alice", True)]
        async with mcp_session(server, grant["access_token"]) as session:
            assert (await call(session, "recommendations"))["recommendations"]
            draft = await call(session, "create_playlist_draft", {"topic": "Python"})
            path = "/approve/" + draft["id"]
            page = await browser.get(path)
            assert "enable-writes" in page.text
            denied = await browser.post(path, data={"csrf": csrf(page), "confirmation": "CREATE"})
            assert denied.status_code == 403
            assert server.providers["alice"].created == []
            server.idp.decline_write = False
            enable = await browser.post(path + "/enable-writes", data={"csrf": csrf(page)})
            from tests.wire_helpers import upstream

            assert await upstream(browser, enable.headers["location"], "alice") == path
            page = await browser.get(path)
            assert "enable-writes" not in page.text
            assert (
                await browser.post(path, data={"csrf": csrf(page), "confirmation": "CREATE"})
            ).json()["status"] == "complete"
