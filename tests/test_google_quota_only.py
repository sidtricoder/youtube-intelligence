import httpx

from tests.wire_helpers import call, csrf, login, mcp_session, rpc, running_server, tool


async def test_zero_legacy_budgets_and_rate_limits_do_not_block_any_tool_or_write(tmp_path):
    with running_server(
        tmp_path,
        units_per_day=0,
        searches_per_day=0,
        user_units_per_day=0,
        anonymous_units_per_day=0,
        max_searches_per_request=0,
        anonymous_rate_limit=0,
        user_rate_limit=0,
    ) as wire:
        for _ in range(3):
            response = await rpc(wire, tool("video_summary", {"video": "aaaaaaaaaaa"}))
            assert response.status_code == 200 and "metadata_only" in response.text
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as browser:
            grant = await login(wire, browser, "alice")
            async with mcp_session(wire, grant["access_token"]) as session:
                draft = await call(
                    session, "create_playlist_draft", {"topic": "Python", "exclude_saved": False}
                )
                page = await browser.get("/approve/" + draft["id"])
                response = await browser.post(
                    "/approve/" + draft["id"], data={"csrf": csrf(page), "confirmation": "CREATE"}
                )
                assert response.status_code == 200 and response.json()["status"] == "complete"
                assert wire.providers["alice"].created


async def test_batch_searches_are_not_rejected_by_app_cap(tmp_path):
    with running_server(tmp_path, max_searches_per_request=0) as wire:
        response = await rpc(
            wire, [tool("similar_videos", {"video": "aaaaaaaaaaa"}, ident=n) for n in range(4)]
        )
        assert response.status_code == 200 and len(response.json()) == 4


async def test_only_google_quota_error_is_exposed_with_safe_upstream_reason(tmp_path):
    import pytest
    from cryptography.fernet import Fernet

    from ytintel.errors import AppError
    from ytintel.providers.google import GoogleProvider
    from ytintel.store import Store

    calls = []

    def respond(request):
        calls.append(request.method)
        return httpx.Response(
            403,
            json={
                "error": {
                    "message": "private raw upstream text",
                    "errors": [{"reason": "quotaExceeded"}],
                }
            },
        )

    store = Store(str(tmp_path / "google.db"), Fernet.generate_key().decode())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        provider = GoogleProvider(client, None, store, public_api_key="synthetic")
        with pytest.raises(AppError) as caught:
            await provider.videos(["aaaaaaaaaaa"])
    assert calls == ["GET"]
    assert caught.value.code == "quota_exceeded"
    assert caught.value.details == {
        "source": "google",
        "reason": "quotaExceeded",
        "upstream_status": 403,
    }
    assert "private raw" not in caught.value.message
    store.close()


async def test_google_quota_details_reach_ai_client_over_real_mcp(tmp_path):
    from tests.wire_helpers import AccountProvider
    from ytintel.errors import AppError

    class GoogleRejected(AccountProvider):
        async def videos(self, ids):
            raise AppError(
                "quota_exceeded",
                "YouTube request failed: quota_exceeded",
                429,
                details={"source": "google", "reason": "quotaExceeded", "upstream_status": 403},
            )

    with running_server(tmp_path) as wire:
        wire.providers["public"] = GoogleRejected("public")
        async with mcp_session(wire) as session:
            result = await call(session, "video_summary", {"video": "aaaaaaaaaaa"})
        assert result["error"]["code"] == "quota_exceeded"
        assert result["error"]["details"] == {
            "source": "google",
            "reason": "quotaExceeded",
            "upstream_status": 403,
        }
