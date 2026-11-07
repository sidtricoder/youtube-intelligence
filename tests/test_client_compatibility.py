import httpx

from tests.wire_helpers import login, rpc, running_server, tool


async def test_claude_origin_can_initialize_and_list_tools_after_oauth(tmp_path):
    with running_server(tmp_path) as wire:
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as browser:
            grant = await login(wire, browser, "alice")
        for message in [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "Claude", "version": "test"},
                },
            },
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]:
            response = await rpc(
                wire, message, grant["access_token"], {"Origin": "https://claude.ai"}
            )
            assert response.status_code == 200, response.text
            assert "result" in response.json()


async def test_mcp_without_trailing_slash_is_dispatched_without_redirect(tmp_path):
    with running_server(tmp_path) as wire:
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as client:
            response = await client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            )
        assert response.status_code == 200, response.text
        assert "tools" in response.json()["result"]


async def test_untrusted_origin_still_rejected(tmp_path):
    with running_server(tmp_path) as wire:
        response = await rpc(
            wire,
            tool("video_summary", {"video": "aaaaaaaaaaa"}),
            headers={"Origin": "https://attacker.invalid"},
        )
        assert response.status_code == 403
        assert wire.providers == {}


async def test_platform_head_probes_work_and_health_identifies_deployed_version(tmp_path):
    with running_server(tmp_path) as wire:
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as client:
            for path in ["/", "/health"]:
                response = await client.head(path)
                assert response.status_code == 200
                assert response.content == b""
            health = (await client.get("/health")).json()
            assert health["version"] == "2.6.2"
