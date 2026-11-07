import pytest
from pydantic import ValidationError

from tests.test_domain import video
from ytintel.domain import Constraints, limits_from_text, select
from ytintel.mcp_server import build_constraints


def test_twelve_hour_courses_and_long_playlists_have_no_server_duration_ceiling():
    constraints = Constraints(topic="Python", total_seconds=200 * 3600, max_seconds=24 * 3600)
    videos = [video("aaaaaaaaaaa", 12 * 3600), video("bbbbbbbbbbb", 18 * 3600)]
    assert select(videos, constraints) == videos
    parsed, _ = limits_from_text("Build a 200 hour playlist on Python, no video over 24 hours")
    assert parsed["total_seconds"] == 200 * 3600 and parsed["max_seconds"] == 24 * 3600


def test_omitted_duration_bounds_are_unbounded():
    constraints = Constraints(topic="Python")
    videos = [video("aaaaaaaaaaa", 100 * 3600), video("bbbbbbbbbbb", 1)]
    assert set(v.id for v in select(videos, constraints)) == {v.id for v in videos}
    assert constraints.total_seconds is None and constraints.max_seconds is None


def test_only_user_supplied_bounds_are_enforced():
    videos = [video("aaaaaaaaaaa", 43200), video("bbbbbbbbbbb", 600)]
    assert [v.id for v in select(videos, Constraints(topic="Python", max_seconds=700))] == [
        "bbbbbbbbbbb"
    ]
    assert [v.id for v in select(videos, Constraints(topic="Python", total_seconds=700))] == [
        "bbbbbbbbbbb"
    ]
    assert select([video(seconds=1)], Constraints(topic="Python", total_seconds=1, max_seconds=1))


@pytest.mark.parametrize("name", ["total_seconds", "max_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5])
def test_durations_still_require_positive_integer_seconds(name, value):
    with pytest.raises(ValidationError):
        Constraints(topic="Python", **{name: value})


def test_topic_without_limits_leaves_duration_bounds_open():
    constraints, inferred = build_constraints("Python", None, None, None, None)
    assert constraints.topic == "Python" and inferred == {}
    assert constraints.total_seconds is None and constraints.max_seconds is None


async def test_mcp_schema_does_not_require_or_cap_durations():
    from ytintel.mcp_server import build_mcp

    server = build_mcp(lambda context: None)
    for tool in await server.list_tools():
        if tool.name == "create_playlist_draft":
            assert "total_seconds" not in tool.inputSchema.get("required", [])
            assert "max_seconds" not in tool.inputSchema.get("required", [])


def test_primary_language_matches_regional_metadata_but_not_other_languages():
    english = video().model_copy(update={"language": "en-US"})
    assert select([english], Constraints(topic="Python", language="en")) == [english]
    assert select([english], Constraints(topic="Python", language="fr")) == []
    assert select([english], Constraints(topic="Python", language="en-GB")) == []
