import pytest

from ytintel.domain import (
    Constraints,
    Video,
    analyse,
    duration,
    rank,
    select,
    video_id,
)


def video(i="aaaaaaaaaaa", seconds=600, language="en", title="Python functions"):
    return Video(
        id=i,
        title=title,
        description="Python programming tutorial",
        channel_id="UC" + "a" * 22,
        channel_title="Example",
        seconds=seconds,
        language=language,
        category="27",
    )


@pytest.mark.parametrize(
    "raw",
    [
        "aaaaaaaaaaa",
        "https://youtu.be/aaaaaaaaaaa?t=1",
        "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        "https://youtube.com/shorts/aaaaaaaaaaa",
    ],
)
def test_video_ids(raw):
    assert video_id(raw) == "aaaaaaaaaaa"


@pytest.mark.parametrize(
    "raw",
    ["bad", "https://evil.test/watch?v=aaaaaaaaaaa", "https://youtube.com.evil.test/aaaaaaaaaaa"],
)
def test_bad_ids(raw):
    with pytest.raises(ValueError):
        video_id(raw)


@pytest.mark.parametrize("raw,expected", [("PT1H2M3S", 3723), ("P1DT1S", 86401), ("PT0S", 0)])
def test_durations(raw, expected):
    assert duration(raw) == expected


@pytest.mark.parametrize("raw", ["123", "PT", "P", "PT-1S"])
def test_bad_duration(raw):
    with pytest.raises(ValueError):
        duration(raw)


def test_similarity_and_missing_tags():
    result = rank(
        "Python functions", [video(), video("bbbbbbbbbbb", title="Mountain biking", language="fr")]
    )
    assert result[0]["video"].id == "aaaaaaaaaaa"
    assert result[0]["score"] > result[1]["score"]


def test_selection_strict_and_deduplicated():
    c = Constraints(topic="python", total_seconds=900, max_seconds=600, language="en")
    picked = select(
        [
            video(),
            video(),
            video("bbbbbbbbbbb", 601),
            video("ccccccccccc", 300),
            video("ddddddddddd", 10, "fr"),
        ],
        c,
    )
    assert [v.id for v in picked] == ["aaaaaaaaaaa", "ccccccccccc"]
    assert sum(v.seconds for v in picked) == 900


def test_limits_written_in_the_topic_are_parsed():
    from ytintel.domain import limits_from_text

    limits, topic = limits_from_text("Python, 2 hour playlist, no video over 20 minutes")
    assert limits["total_seconds"] == 7200 and limits["max_seconds"] == 1200
    assert topic == "Python"
    assert limits_from_text("something vague") == (
        {k: None for k in limits},
        "something vague",
    )


def test_analysis_dated_activity_not_publication():
    a = analyse(
        [
            dict(video=video().model_dump(), source="liked", at="2026-10-01T00:00:00Z"),
            dict(video=video().model_dump(), source="playlist", at=None),
        ],
        "2026-10-01",
        "2026-11-01",
        "2026-09-01",
    )
    assert a["sample_count"] == 2 and a["dated_count"] == 1
    assert a["period_comparison"]["current"] == 1
    assert a["period_comparison"]["previous"] == 0


def test_equivalent_timezone_boundaries_have_equivalent_period_counts():
    events = [dict(video=video().model_dump(), source="playlist", at="2026-10-01T00:30:00Z")]
    utc = analyse(
        events,
        "2026-10-01T00:00:00+00:00",
        "2026-11-01T00:00:00+00:00",
        "2026-09-01T00:00:00+00:00",
    )
    offset = analyse(
        events,
        "2026-10-01T01:00:00+01:00",
        "2026-11-01T01:00:00+01:00",
        "2026-09-01T01:00:00+01:00",
    )
    assert utc["period_comparison"] == offset["period_comparison"]
