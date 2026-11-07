"""Video-count modes: exactly / at_least / at_most N, and never more videos than allowed.

Regression for: "I asked for a playlist of exactly 10 videos and got more."
"""

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from tests.fakes import FixtureProvider
from tests.test_domain import video
from tests.test_length_and_count import (  # noqa: F401  (deep_service is a fixture)
    DeepProvider,
    VerifyingProvider,
    deep_service,
    numbered,
)
from tests.wire_helpers import call, login, mcp_session, running_server
from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.domain import (
    Constraints,
    constraint_check,
    count_bounds,
    limits_from_text,
    select,
    violations,
)
from ytintel.errors import AppError
from ytintel.mcp_server import build_constraints, build_mcp

# --- Pure domain rules -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("count", "mode", "expected"),
    [
        (10, None, (10, 10)),  # a bare number means exactly that many
        (10, "exactly", (10, 10)),
        (10, "at_most", (None, 10)),
        (10, "at_least", (10, None)),
        (None, None, (None, None)),
    ],
)
def test_count_mode_maps_to_a_floor_and_a_ceiling(count, mode, expected):
    assert count_bounds(count, mode) == expected


@pytest.mark.parametrize(("count", "mode"), [(None, "exactly"), (None, "at_most"), (10, "roughly")])
def test_contradictory_count_arguments_are_rejected(count, mode):
    with pytest.raises(ValueError):
        count_bounds(count, mode)


def test_floor_above_ceiling_is_invalid():
    with pytest.raises(ValidationError):
        Constraints(topic="Python", min_videos=11, max_videos=10)
    assert Constraints(topic="Python", min_videos=10, max_videos=10).count_mode() == "exactly"


def test_selection_never_returns_more_than_the_requested_count():
    pool = numbered(0, 40, 600)
    for count in (1, 10, 25, 40):
        picked = select(pool, Constraints(topic="Python", min_videos=count, max_videos=count))
        assert len(picked) == count


def test_violations_flag_too_many_and_too_few_videos():
    c = Constraints(topic="Python", min_videos=3, max_videos=3)
    assert "fewer than min_videos" in " ".join(violations(numbered(0, 2, 600), c))
    assert "exceeds max_videos" in " ".join(violations(numbered(0, 4, 600), c))
    assert violations(numbered(0, 3, 600), c) == []


def test_constraint_check_reports_the_requested_count_and_whether_it_held():
    c = Constraints(topic="Python", min_videos=3, max_videos=3)
    check = constraint_check(numbered(0, 3, 600), c)
    assert check["requested_count"] == {"mode": "exactly", "min_videos": 3, "max_videos": 3}
    assert check["count_satisfied"] is True and check["all_satisfied"] is True
    assert constraint_check(numbered(0, 2, 600), c)["count_satisfied"] is False


@pytest.mark.parametrize(
    ("text", "min_videos", "max_videos", "topic"),
    [
        ("Python, exactly 10 videos", 10, 10, "Python"),
        ("exactly ten beginner python videos", 10, 10, "beginner python"),
        ("at least 10 videos on Python", 10, None, "on Python"),
        ("15 or more python videos", 15, None, "python"),
        ("python 12+ videos", 12, None, "python"),
        ("up to 8 videos about Python", None, 8, "about Python"),
        ("Python, 15 or fewer videos", None, 15, "Python"),
        ("10 python videos", None, 10, "python"),  # used to be missed -> unlimited
        ("ten videos about python", None, 10, "about python"),  # used to be missed
        ("10 short videos on python", None, 10, "short on python"),  # used to be missed
    ],
)
def test_counts_written_in_prose_are_read_with_the_right_mode(text, min_videos, max_videos, topic):
    limits, remainder = limits_from_text(text)
    assert (limits["min_videos"], limits["max_videos"]) == (min_videos, max_videos), text
    assert remainder == topic


def test_a_video_length_is_never_read_as_a_video_count():
    limits, _ = limits_from_text("python, 10 minute videos")
    assert limits["max_videos"] is None and limits["min_videos"] is None
    limits, _ = limits_from_text("at least 5 minutes, 8 videos")
    assert (limits["min_seconds"], limits["min_videos"], limits["max_videos"]) == (300, None, 8)


# --- MCP argument handling ----------------------------------------------------------------


def test_video_count_parameter_defaults_to_exactly():
    c, inferred = build_constraints("Python", None, None, None, None, video_count=10)
    assert (c.min_videos, c.max_videos, c.count_mode()) == (10, 10, "exactly") and inferred == {}


def test_structured_count_wins_over_a_count_in_the_topic_text():
    c, inferred = build_constraints(
        "Python, 30 videos", None, None, None, None, video_count=10, count_mode="exactly"
    )
    assert (c.min_videos, c.max_videos) == (10, 10) and "max_videos" not in inferred


def test_exactly_in_the_topic_text_is_applied_when_the_ai_forgets_the_parameter():
    c, inferred = build_constraints("Python, exactly 10 videos", None, None, None, None)
    assert (c.topic, c.min_videos, c.max_videos) == ("Python", 10, 10)
    assert inferred == {"min_videos": 10, "max_videos": 10}


def test_count_mode_without_a_count_is_an_invalid_input_error():
    with pytest.raises(AppError) as caught:
        build_constraints("Python", None, None, None, None, count_mode="exactly")
    assert caught.value.code == "invalid_input"


async def test_only_the_draft_tool_builds_playlists_and_it_takes_video_count():
    tools = {tool.name: tool for tool in await build_mcp(lambda _: None).list_tools()}
    assert not {"propose_playlist", "playlist_from_request", "video_to_playlist"} & set(tools)
    for tool in [tools["create_playlist_draft"]]:
        props = tool.inputSchema["properties"]
        assert "video_count" in props and "count_mode" in props
        assert "max_videos" not in props
        assert "video_count" not in tool.inputSchema.get("required", [])
        modes = [s for s in props["count_mode"]["anyOf"] if "enum" in s][0]["enum"]
        assert modes == ["exactly", "at_least", "at_most"]


# --- Service: proposals and drafts ---------------------------------------------------------


async def test_exactly_ten_returns_ten_even_when_many_more_match(deep_service):  # noqa: F811
    service = await deep_service(DeepProvider([numbered(0, 50, 600)]))
    draft = await service.propose(
        Constraints(topic="Python", min_videos=10, max_videos=10), exclude_saved=False
    )
    assert len(draft["videos"]) == 10
    assert draft["constraint_check"]["count_satisfied"] is True
    assert "video_count_note" not in draft


async def test_exactly_ten_with_only_six_matches_is_an_error_not_a_short_list(
    deep_service,  # noqa: F811
):
    service = await deep_service(DeepProvider([numbered(0, 6, 600)]))
    with pytest.raises(AppError) as caught:
        await service.propose(
            Constraints(topic="Python", min_videos=10, max_videos=10), exclude_saved=False
        )
    assert caught.value.code == "not_enough_videos"
    assert caught.value.details["found"] == 6 and caught.value.details["mode"] == "exactly"


async def test_at_least_returns_the_floor_or_more_but_never_above_the_ceiling(
    deep_service,  # noqa: F811
):
    service = await deep_service(DeepProvider([numbered(0, 30, 600)]))
    capped = await service.propose(
        Constraints(topic="Python", min_videos=5, max_videos=8), exclude_saved=False
    )
    assert len(capped["videos"]) == 8
    service = await deep_service(DeepProvider([numbered(0, 12, 600)]))
    open_ended = await service.propose(
        Constraints(topic="Python", min_videos=5), exclude_saved=False
    )
    assert len(open_ended["videos"]) == 12


async def test_at_most_allows_fewer_and_says_so(deep_service):  # noqa: F811
    service = await deep_service(DeepProvider([numbered(0, 6, 600)]))
    result = await service.propose(Constraints(topic="Python", max_videos=10), exclude_saved=False)
    assert len(result["videos"]) == 6 and "only 6 matched" in result["video_count_note"]


async def test_youtube_receives_exactly_the_requested_number_of_videos(deep_service):  # noqa: F811
    provider = FixtureProvider()
    service = await deep_service(provider)
    draft = await service.propose(
        Constraints(topic="Python", min_videos=3, max_videos=3), exclude_saved=False
    )
    done = await service.approve(draft["id"], "CREATE")
    assert done["status"] == "complete" and len(provider.inserted) == 3
    assert done["youtube_check"] == {
        "checked": True,
        "item_count": 3,
        "expected_count": 3,
        "matches_draft": True,
        "within_count_limits": True,
    }


async def test_exact_draft_is_not_written_when_a_video_drops_out_before_creation(
    deep_service,  # noqa: F811
):
    stale = [video(f"s{n:010d}", 400) for n in range(3)]
    truth = {v.id: v for v in stale}
    provider = VerifyingProvider(stale, truth)
    service = await deep_service(provider)
    draft = await service.propose(
        Constraints(topic="Python", min_videos=3, max_videos=3), exclude_saved=False
    )
    del truth[draft["videos"][0]["id"]]  # deleted on YouTube after the draft was made
    with pytest.raises(AppError) as caught:
        await service.approve(draft["id"], "CREATE")
    assert caught.value.code == "not_enough_videos"
    assert not provider.created and not provider.inserted


# --- End to end over a real MCP connection ------------------------------------------------


async def test_ai_client_gets_exactly_the_count_it_asked_for(tmp_path):
    with running_server(tmp_path) as wire:
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as browser:
            token = (await login(wire, browser, "alice"))["access_token"]
        async with mcp_session(wire, token) as session:

            async def draft(**arguments):
                return await call(
                    session,
                    "create_playlist_draft",
                    {"topic": "Python", "exclude_saved": False, **arguments},
                )

            exact = await draft(video_count=3)
            too_many = await draft(video_count=10)
            at_most = await draft(video_count=10, count_mode="at_most")
    assert len(exact["videos"]) == 3 and exact["constraint_check"]["count_satisfied"] is True
    link = wire.origin + "/approve/" + exact["id"]
    assert exact["approval_url"] == exact["confirmation_link"] == link
    assert link in exact["next_step"] and "REQUIRED" in exact["next_step"]
    assert too_many["error"]["code"] == "not_enough_videos"
    assert 1 <= len(at_most["videos"]) <= 10


# --- Local tester page ---------------------------------------------------------------------


async def test_tester_page_is_served_locally_with_a_script_nonce(tmp_path):
    with running_server(tmp_path) as wire:
        async with httpx.AsyncClient(base_url=wire.origin, trust_env=False) as client:
            page = await client.get("/tester")
    assert page.status_code == 200
    policy = page.headers["content-security-policy"]
    nonce = policy.split("'nonce-")[1].split("'")[0]
    assert f'<script nonce="{nonce}">' in page.text and "__NONCE__" not in page.text
    assert "connect-src 'self'" in policy and '"tools/list"' in page.text
    assert "console.log" in page.text
    assert "__RESOURCE__" not in page.text and f'"{wire.origin}/mcp/"' in page.text


def test_tester_page_is_off_for_a_public_deployment(tmp_path):
    from fastapi.testclient import TestClient

    settings = Settings(
        _env_file=None,
        db_path=str(tmp_path / "public.db"),
        encryption_key=Fernet.generate_key().decode(),
        public_base_url="https://ytintel.example.com",
    )
    app = create_app(settings, provider=FixtureProvider())
    try:
        assert TestClient(app).get("/tester").status_code == 404
    finally:
        app.state.store.close()


def test_ai_instructions_make_the_confirmation_link_mandatory():
    instructions = build_mcp(lambda _: None).instructions
    assert "MANDATORY" in instructions and "approval_url" in instructions
    assert "never make the user ask for it" in instructions.lower()
