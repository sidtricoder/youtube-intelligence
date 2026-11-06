import time

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from tests.fakes import FixtureProvider
from tests.test_domain import video
from tests.wire_helpers import call, mcp_session, running_server
from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.domain import (
    MAX_VIDEOS_LIMIT,
    Constraints,
    constraint_check,
    parse_request,
    select,
    violations,
)
from ytintel.errors import AppError
from ytintel.identity import WRITE_SCOPE


def pool():
    return [
        video("aaaaaaaaaaa", 120),
        video("bbbbbbbbbbb", 300),
        video("ccccccccccc", 600),
        video("ddddddddddd", 900),
        video("eeeeeeeeeee", 1500),
    ]


def test_max_videos_keeps_the_most_relevant_videos_up_to_the_count():
    picked = select(pool(), Constraints(topic="python", max_videos=2))
    assert len(picked) == 2
    assert len(select(pool(), Constraints(topic="python", max_videos=50))) == 5
    assert len(select(pool(), Constraints(topic="python"))) == 5


def test_min_and_max_seconds_form_a_per_video_length_range():
    picked = select(pool(), Constraints(topic="python", min_seconds=300, max_seconds=900))
    assert sorted(v.seconds for v in picked) == [300, 600, 900]


def test_count_length_and_total_bounds_combine():
    picked = select(
        pool(), Constraints(topic="python", min_seconds=300, max_videos=2, total_seconds=1000)
    )
    assert len(picked) <= 2
    assert all(v.seconds >= 300 for v in picked)
    assert sum(v.seconds for v in picked) <= 1000


@pytest.mark.parametrize(
    "fields",
    [
        {"min_seconds": 0},
        {"min_seconds": -5},
        {"min_seconds": 1.5},
        {"max_videos": 0},
        {"max_videos": -1},
        {"max_videos": MAX_VIDEOS_LIMIT + 1},
        {"max_videos": True},
        {"min_seconds": 700, "max_seconds": 600},
    ],
)
def test_invalid_count_and_length_values_are_rejected(fields):
    with pytest.raises(ValidationError):
        Constraints(topic="Python", **fields)


def test_equal_min_and_max_seconds_is_allowed():
    assert Constraints(topic="Python", min_seconds=600, max_seconds=600).min_seconds == 600


def test_natural_language_request_reads_count_and_length_range():
    c = parse_request(
        "Build a 2 hour playlist on Python, 8 videos, no video over 20 minutes, "
        "at least 5 minutes, language en"
    )
    assert c.max_videos == 8
    assert (c.min_seconds, c.max_seconds, c.total_seconds) == (300, 1200, 7200)


def test_no_video_under_is_a_minimum_not_a_maximum():
    c = parse_request("Build a playlist on Python, no video under 5 minutes")
    assert c.min_seconds == 300 and c.max_seconds is None
    c = parse_request("Build a playlist on Python, under 10 minutes")
    assert c.max_seconds == 600 and c.min_seconds is None


async def test_mcp_tools_expose_optional_count_and_length_parameters():
    from ytintel.mcp_server import build_mcp

    for tool in await build_mcp(lambda _: None).list_tools():
        if tool.name in {"propose_playlist", "video_to_playlist", "create_playlist_draft"}:
            props = tool.inputSchema["properties"]
            required = tool.inputSchema.get("required", [])
            for name in ("total_seconds", "max_seconds", "min_seconds", "max_videos"):
                assert name in props and name not in required
            assert props["max_videos"]["description"]
            assert "single video" in props["max_seconds"]["description"]
            assert "combined playlist" in props["total_seconds"]["description"]


async def test_ai_client_limits_video_count_and_length_over_real_mcp(tmp_path):
    with running_server(tmp_path) as wire:
        async with mcp_session(wire) as session:
            result = await call(
                session,
                "propose_playlist",
                {"topic": "Python", "max_videos": 3, "min_seconds": 500, "max_seconds": 1000},
            )
            assert 0 < len(result["videos"]) <= 3
            assert all(500 <= v["seconds"] <= 1000 for v in result["videos"])
            assert result["constraints"]["max_videos"] == 3
            assert result["constraints"]["min_seconds"] == 500

            short = await call(
                session,
                "propose_playlist",
                {"topic": "Python", "max_videos": 50, "max_seconds": 700},
            )
            assert len(short["videos"]) < 50
            assert "video_count_note" in short

            full = await call(session, "propose_playlist", {"topic": "Python", "max_videos": 2})
            assert len(full["videos"]) == 2 and "video_count_note" not in full

            for bad in (
                {"max_videos": 0},
                {"max_videos": 51},
                {"min_seconds": 900, "max_seconds": 600},
            ):
                error = (await call(session, "propose_playlist", {"topic": "Python", **bad}))[
                    "error"
                ]
                assert error["code"] == "invalid_input"
                assert error["fields"]


def test_thirty_video_cap_with_five_minute_floor_on_a_full_search_page():
    """The reported case: a full page of 50 candidates, many under five minutes."""
    candidates = [video(f"{i:011d}", 60 + i * 20) for i in range(50)]
    c = Constraints(topic="python", max_videos=30, min_seconds=300)
    picked = select(candidates, c)
    assert 0 < len(picked) <= 30
    assert all(v.seconds >= 300 for v in picked)
    assert violations(picked, c) == []
    assert constraint_check(picked, c)["all_satisfied"] is True


def test_violations_detects_every_kind_of_broken_limit():
    c = Constraints(topic="python", max_videos=1, min_seconds=300, max_seconds=900)
    broken = [video("aaaaaaaaaaa", 100), video("bbbbbbbbbbb", 1000)]
    text = " ".join(violations(broken, c))
    assert "max_videos" in text and "shorter than" in text and "longer than" in text
    assert constraint_check(broken, c)["all_satisfied"] is False
    assert (
        violations(select(broken, Constraints(topic="python")), Constraints(topic="python")) == []
    )


@pytest.fixture
async def app_and_service(tmp_path):
    app = create_app(
        Settings(
            _env_file=None,
            db_path=str(tmp_path / "db"),
            encryption_key=Fernet.generate_key().decode(),
        ),
        provider=FixtureProvider(),
    )
    user = app.state.security.upsert_user("account-a")
    app.state.security.save_google(
        user, {"access_token": "synthetic", "scope": WRITE_SCOPE, "expires_at": time.time() + 3600}
    )
    context = await app.state.context_factory(
        type("Verified", (), {"user_id": user})(), "127.0.0.1"
    )
    yield app.state.service_factory(context)
    app.state.store.close()


async def test_draft_carries_proof_that_limits_were_applied(app_and_service):
    draft = await app_and_service.propose(
        Constraints(topic="Python", max_videos=3, min_seconds=500), exclude_saved=False
    )
    check = draft["constraint_check"]
    assert draft["constraints"]["max_videos"] == 3 and draft["constraints"]["min_seconds"] == 500
    assert check["video_count"] == len(draft["videos"]) <= 3
    assert check["shortest_seconds"] >= 500 and check["all_satisfied"] is True


async def test_draft_that_breaks_its_limits_is_never_written_to_youtube(app_and_service):
    service = app_and_service
    draft = await service.propose(
        Constraints(topic="Python", max_videos=2, min_seconds=500), exclude_saved=False
    )
    short = {**draft["videos"][0], "id": "zzzzzzzzzzz", "seconds": 60}
    draft["videos"].append(short)
    service.save(draft)
    with pytest.raises(AppError) as caught:
        await service.approve(draft["id"], "CREATE")
    assert caught.value.code == "constraint_violation"
    assert not service.provider.created and not service.provider.inserted


async def test_unsupported_parameter_is_rejected_instead_of_silently_ignored(tmp_path):
    with running_server(tmp_path) as wire:
        async with mcp_session(wire) as session:
            for tool, extra in (
                ("propose_playlist", {"max_results": 30}),
                ("propose_playlist", {"min_minutes": 5}),
                ("create_playlist_draft", {"max_video": 30}),
            ):
                result = await call(session, tool, {"topic": "Python", **extra})
                assert result["error"]["code"] == "unknown_parameter"
                assert set(result["error"]["fields"]) == set(extra)
                assert "max_videos" in result["error"]["message"]
        assert wire.providers == {}, "a rejected call must not touch the provider"
