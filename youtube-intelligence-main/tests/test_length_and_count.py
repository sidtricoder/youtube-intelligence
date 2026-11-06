import pytest
from pydantic import ValidationError

from tests.test_domain import video
from tests.wire_helpers import call, mcp_session, running_server
from ytintel.domain import MAX_VIDEOS_LIMIT, Constraints, parse_request, select


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
