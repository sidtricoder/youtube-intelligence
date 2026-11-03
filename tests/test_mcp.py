"""FR1–FR5 over real TCP and the official MCP Streamable HTTP client."""

import json

import httpx
import pytest
from sqlalchemy import func, select

from tests.wire_helpers import call, csrf, login, mcp_session, running_server, upstream
from ytintel.policy import RESOURCE_TIERS, TOOL_TIERS, Tier


@pytest.fixture
def server(tmp_path):
    with running_server(tmp_path) as wire:
        yield wire


async def test_anonymous_discovery_stateless_workflow_and_negative_errors(server):
    async with mcp_session(server) as session:
        tools = {t.name: t for t in (await session.list_tools()).tools}
        resources = {str(r.uri) for r in (await session.list_resources()).resources}
        assert set(tools) == set(TOOL_TIERS)
        templates = {
            r.uriTemplate for r in (await session.list_resource_templates()).resourceTemplates
        }
        assert resources | templates == set(RESOURCE_TIERS)
        assert (await session.list_prompts()).prompts
        assert (
            await session.get_prompt("video_to_playlist_workflow", {"video": "aaaaaaaaaaa"})
        ).messages
        for name, tier in TOOL_TIERS.items():
            if tier == Tier.AUTHENTICATED:
                assert "requires sign-in" in tools[name].description.lower()
        assert not any(name in tools for name in ("approve", "resume", "create_playlist"))
        for uri, tier in RESOURCE_TIERS.items():
            if tier == Tier.PUBLIC:
                assert (await session.read_resource(uri)).contents
        assert (await call(session, "similar_videos", {"video": "aaaaaaaaaaa"}))["results"]
        assert (await call(session, "similar_channels", {"channel": "@pythonlab"}))["results"]
        assert (await call(session, "video_summary", {"video": "aaaaaaaaaaa"}))[
            "basis"
        ] == "metadata_only"
        args = {"topic": "Python", "total_seconds": 1800, "max_seconds": 900, "language": "en"}
        preview = await call(session, "propose_playlist", args)
        assert preview["videos"] and preview["personalised"] is False
        assert not {"id", "status", "approval_url", "user_id"} & preview.keys()
        workflow = await call(session, "video_to_playlist", {"video": "aaaaaaaaaaa", **args})
        assert workflow["summary"]["basis"] == "metadata_only"
        assert workflow["similar"] and workflow["analysis"]["sample_count"] > 0
        assert "id" not in workflow["preview"] and "draft" not in workflow
        natural = await call(
            session,
            "playlist_from_request",
            {"request": "Build a 2 hour playlist on Python, no video over 20 minutes, language en"},
        )
        assert natural["constraints"]["total_seconds"] == 7200
        assert natural["constraints"]["max_seconds"] == 1200
        assert (
            await call(session, "similar_videos", {"video": "https://evil.test/?v=aaaaaaaaaaa"})
        )["error"]["code"] == "invalid_input"
        assert (await call(session, "similar_videos", {"video": "zzzzzzzzzzz"}))["error"][
            "code"
        ] == "not_found"
        assert (await call(session, "propose_playlist", {**args, "total_seconds": -1}))["error"][
            "code"
        ] == "invalid_input"
    assert not server.providers["public"].created
    raw = server.app.state.store
    with raw.tx() as db:
        for name in ("users", "user_google_tokens", "drafts", "tenant_cache"):
            table = raw.metadata.tables[name]
            assert db.execute(select(func.count()).select_from(table)).scalar_one() == 0


async def test_two_accounts_interleaved_fr1_to_fr5_and_browser_confirmation(server):
    async with (
        httpx.AsyncClient(base_url=server.origin, trust_env=False) as alice,
        httpx.AsyncClient(base_url=server.origin, trust_env=False) as bob,
    ):
        a, b = await login(server, alice, "alice"), await login(server, bob, "bob")
        async with (
            mcp_session(server, a["access_token"]) as sa,
            mcp_session(server, b["access_token"]) as sb,
        ):
            assert {str(r.uri) for r in (await sa.list_resources()).resources} | {
                r.uriTemplate for r in (await sa.list_resource_templates()).resourceTemplates
            } == set(RESOURCE_TIERS)
            drafts = []
            for session, label, other in ((sa, "alice", "bob"), (sb, "bob", "alice")):
                assert (await call(session, "similar_videos", {"video": "aaaaaaaaaaa"}))["results"]
                assert (await call(session, "similar_channels", {"channel": "@pythonlab"}))[
                    "results"
                ]
                recs = await call(session, "recommendations")
                assert recs["recommendations"]
                assert label in json.dumps(recs["profile"]) and other not in json.dumps(recs)
                analysis = await call(session, "engagement_analysis")
                assert analysis["sample_count"] == 3
                assert label in json.dumps(analysis) and other not in json.dumps(analysis)
                drafts.append(
                    await call(
                        session,
                        "create_playlist_draft",
                        {"topic": "Python " + label, "total_seconds": 1800, "max_seconds": 900},
                    )
                )
            da, db = drafts
            assert da["id"] != db["id"] and da["user_id"] != db["user_id"]
            for session, own, other in ((sa, da, db), (sb, db, da)):
                assert (await call(session, "playlist_status", {"draft_id": own["id"]}))[
                    "status"
                ] == "pending"
                cross = await call(session, "playlist_status", {"draft_id": other["id"]})
                missing = await call(session, "playlist_status", {"draft_id": "missing"})
                assert cross == missing and cross["error"]["code"] == "draft_not_found"
            b_quota = (await sb.read_resource("ytintel://quota")).contents[0].text
            await call(sa, "video_summary", {"video": "aaaaaaaaaaa"})
            assert (await sb.read_resource("ytintel://quota")).contents[0].text == b_quota
            assert set(json.loads(b_quota)) == {
                "day",
                "units_used",
                "searches_used",
                "units_limit",
                "searches_limit",
                "max_searches_per_request",
            }
            assert all(not p.created for p in server.providers.values())
            for browser, session, draft, other_browser, label in (
                (alice, sa, da, bob, "alice"),
                (bob, sb, db, alice, "bob"),
            ):
                path = "/approve/" + draft["id"]
                hidden = await other_browser.get(path)
                nonexistent = await other_browser.get("/approve/missing")
                assert hidden.status_code == nonexistent.status_code == 404
                assert hidden.json() == nonexistent.json()
                other_page = await other_browser.get(
                    "/approve/" + (db if label == "alice" else da)["id"]
                )
                cross_post = await other_browser.post(
                    path, data={"csrf": csrf(other_page), "confirmation": "CREATE"}
                )
                assert cross_post.status_code == 404 and cross_post.json() == nonexistent.json()
                async with httpx.AsyncClient(
                    base_url=server.origin, trust_env=False
                ) as bearer_only:
                    denied = await bearer_only.post(
                        path,
                        headers={
                            "Authorization": "Bearer "
                            + (a if label == "alice" else b)["access_token"]
                        },
                        data={"confirmation": "CREATE"},
                    )
                    assert denied.status_code == 401
                page = await browser.get(path)
                assert "enable-writes" in page.text
                assert (await browser.post(path + "/enable-writes", data={})).status_code == 403
                enable = await browser.post(path + "/enable-writes", data={"csrf": csrf(page)})
                assert enable.status_code == 302
                return_path = await upstream(browser, enable.headers["location"], label)
                assert return_path == path
                page = await browser.get(path)
                assert "Type CREATE" in page.text
                for form in (
                    {"confirmation": "CREATE"},
                    {"csrf": csrf(page), "confirmation": "yes"},
                ):
                    assert (await browser.post(path, data=form)).status_code == 403
                assert not server.providers[label].created
                completed = await browser.post(
                    path, data={"csrf": csrf(page), "confirmation": "CREATE"}
                )
                assert completed.status_code == 200 and completed.json()["status"] == "complete"
                status = await call(session, "playlist_status", {"draft_id": draft["id"]})
                assert status["status"] == "complete"
                assert len(server.providers[label].created) == 1
                assert len(server.providers[label].inserted) == len(draft["videos"])
                assert (
                    await browser.post(path, data={"csrf": csrf(page), "confirmation": "CREATE"})
                ).status_code == 409
            assert server.idp.exchanges == [
                ("alice", False),
                ("bob", False),
                ("alice", True),
                ("bob", True),
            ]
