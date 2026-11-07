"""Pure validation, metadata ranking, constraints and bounded-sample analytics."""

import math
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Video(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{11}$")
    title: str
    description: str = ""
    channel_id: str
    channel_title: str
    seconds: int = Field(ge=0)
    language: str | None = None
    category: str = "unknown"
    tags: list[str] = Field(default_factory=list)
    published_at: str | None = None

    def text(self) -> str:
        return " ".join([self.title, self.description[:2000], *self.tags])


# One YouTube search page is the candidate pool, so a larger count could never be honoured.
MAX_VIDEOS_LIMIT = 50


class Constraints(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    topic: str = Field(min_length=2, max_length=200)
    total_seconds: int | None = Field(default=None, gt=0, strict=True)
    max_seconds: int | None = Field(default=None, gt=0, strict=True)
    min_seconds: int | None = Field(default=None, gt=0, strict=True)
    max_videos: int | None = Field(default=None, ge=1, le=MAX_VIDEOS_LIMIT, strict=True)
    language: str | None = Field(default=None, pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$")

    @model_validator(mode="after")
    def _length_range_is_consistent(self):
        if (
            self.min_seconds is not None
            and self.max_seconds is not None
            and self.min_seconds > self.max_seconds
        ):
            raise ValueError("min_seconds cannot exceed max_seconds")
        return self


def video_id(raw: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw
    p = urlparse(raw)
    if p.scheme != "https" or p.hostname not in {
        "youtu.be",
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
    }:
        raise ValueError("Use a video ID or an HTTPS YouTube video URL")
    if p.hostname == "youtu.be":
        candidate = p.path.strip("/")
    elif p.path == "/watch":
        candidate = parse_qs(p.query).get("v", [""])[0]
    elif re.fullmatch(r"/(shorts|embed)/[A-Za-z0-9_-]{11}", p.path):
        candidate = p.path.split("/")[-1]
    else:
        candidate = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        raise ValueError("Malformed video identifier")
    return candidate


def channel_ref(raw: str) -> tuple[str, str]:
    if raw.startswith("https://"):
        p = urlparse(raw)
        if p.hostname not in {"youtube.com", "www.youtube.com"}:
            raise ValueError("Invalid channel host")
        raw = p.path.removeprefix("/channel/").strip("/")
    if re.fullmatch(r"UC[A-Za-z0-9_-]{22}", raw):
        return "id", raw
    if re.fullmatch(r"@[\w.\-]{3,30}", raw):
        return "forHandle", raw
    raise ValueError("Use a UC channel ID, @handle or canonical channel URL")


def duration(raw: str) -> int:
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", raw)
    if not m or not any(x is not None for x in m.groups()) or raw.endswith("T"):
        raise ValueError("Invalid ISO-8601 duration")
    d, h, mn, s = (int(x or 0) for x in m.groups())
    return d * 86400 + h * 3600 + mn * 60 + s


def similarities(query: str, texts: list[str]) -> list[float]:
    docs = [Counter(re.findall(r"\w+", s.casefold())) for s in [query, *texts]]
    df = Counter(t for d in docs for t in d)
    vectors = [
        {t: (1 + math.log(n)) * (1 + math.log((1 + len(docs)) / (1 + df[t]))) for t, n in d.items()}
        for d in docs
    ]
    q = vectors[0]
    qnorm = math.sqrt(sum(v * v for v in q.values()))
    return [
        sum(q.get(t, 0) * v for t, v in d.items())
        / (qnorm * math.sqrt(sum(v * v for v in d.values())) or 1)
        for d in vectors[1:]
    ]


def rank(query: str, videos: list[Video]) -> list[dict]:
    return sorted(
        [
            {"video": v, "score": round(s, 6)}
            for v, s in zip(videos, similarities(query, [v.text() for v in videos]))
        ],
        key=lambda x: (-x["score"], x["video"].id),
    )


def _language_ok(v: Video, c: Constraints) -> bool:
    requested = (c.language or "").casefold()
    actual = (v.language or "").casefold()
    return (
        not requested
        or actual == requested
        or ("-" not in requested and actual.startswith(requested + "-"))
    )


def select(videos: list[Video], c: Constraints) -> list[Video]:
    """Greedy relevance selection; total is an upper bound, never an exact-fill promise.

    max_seconds/min_seconds bound each video; total_seconds bounds the playlist runtime;
    max_videos bounds how many videos are returned (most relevant first).
    """
    seen, result, used = set(), [], 0
    for item in rank(c.topic, videos):
        if c.max_videos is not None and len(result) >= c.max_videos:
            break
        v = item["video"]
        if (
            v.id not in seen
            and 0 < v.seconds
            and (c.min_seconds is None or v.seconds >= c.min_seconds)
            and (c.max_seconds is None or v.seconds <= c.max_seconds)
            and (c.total_seconds is None or used + v.seconds <= c.total_seconds)
            and _language_ok(v, c)
            and item["score"] > 0
        ):
            result.append(v)
            used += v.seconds
            seen.add(v.id)
    return result


def violations(videos: list[Video], c: Constraints) -> list[str]:
    """Independent re-check of a finished selection; empty means every constraint holds."""
    problems = []
    if c.max_videos is not None and len(videos) > c.max_videos:
        problems.append(f"{len(videos)} videos exceeds max_videos={c.max_videos}")
    if len({v.id for v in videos}) != len(videos):
        problems.append("duplicate videos")
    if c.total_seconds is not None and sum(v.seconds for v in videos) > c.total_seconds:
        problems.append(f"total length exceeds total_seconds={c.total_seconds}")
    for v in videos:
        if c.min_seconds is not None and v.seconds < c.min_seconds:
            problems.append(f"video {v.id} is shorter than min_seconds={c.min_seconds}")
        if c.max_seconds is not None and v.seconds > c.max_seconds:
            problems.append(f"video {v.id} is longer than max_seconds={c.max_seconds}")
        if not _language_ok(v, c):
            problems.append(f"video {v.id} does not match language={c.language}")
    return problems


def constraint_check(videos: list[Video], c: Constraints) -> dict:
    """Machine-readable proof, returned with every proposal, that the limits were applied."""
    seconds = [v.seconds for v in videos]
    return {
        "video_count": len(videos),
        "shortest_seconds": min(seconds) if seconds else None,
        "longest_seconds": max(seconds) if seconds else None,
        "total_seconds": sum(seconds),
        "all_satisfied": not violations(videos, c),
    }


_NUM = r"(\d+(?:\.\d+)?)"
_UNIT = r"(hours?|hrs?|minutes?|mins?)"
_LIMIT_PATTERNS = {
    "total_seconds": (
        rf"{_NUM}\s*{_UNIT}\s+(?:long\s+)?playlist",
        rf"playlist\s+(?:of|totall?ing|lasting|up to|under)\s+{_NUM}\s*{_UNIT}",
    ),
    "max_seconds": (
        rf"(?:(?:each|every)\s+video\s+)?(?:no video over|no longer than|at most|(?<!no video )(?:under|shorter than)"
        rf"|\bmax(?:imum)?(?:[ _]video)?(?:[ _](?:length|duration))?(?:\s+of)?)\s*[:=]?\s*{_NUM}\s*{_UNIT}",
    ),
    "min_seconds": (
        rf"(?:(?:each|every)\s+video\s+)?(?:at least|no video (?:under|shorter than)|(?<!no )longer than"
        rf"|\b(?:minimum|min(?=[ _](?:video|length|duration)))(?:[ _]video)?(?:[ _](?:length|duration))?(?:\s+of)?)"
        rf"\s*[:=]?\s*{_NUM}\s*{_UNIT}",
        rf"{_NUM}\s*{_UNIT}\s*(?:or (?:more|longer)|minimum|\+)",
        rf"{_NUM}\+\s*{_UNIT}",
    ),
    "max_videos": (
        r"(?:\b(?:up to|at most|no more than|max(?:imum)?(?: of)?|limit(?: of)?|exactly|only)\s+)?"
        r"\b(\d{1,3})[\s-]+videos?\b",
        r"\b(?:max(?:imum)?|number of|limit)[ _](?:of[ _])?videos?\s*[:=]?\s*(\d{1,3})\b",
    ),
}


def _seconds_of(match) -> int:
    return int(float(match[1]) * (3600 if match[2].lower().startswith("h") else 60))


def limits_from_text(text: str) -> tuple[dict, str]:
    """Find explicit length/count limits written in prose; return them and the text without them."""
    found, spans = {}, []
    for field, patterns in _LIMIT_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                found[field] = int(match[1]) if field == "max_videos" else _seconds_of(match)
                spans.append(match.span())
                break
    remainder = text
    for start, end in sorted(spans, reverse=True):
        remainder = remainder[:start] + remainder[end:]
    remainder = re.sub(r"(?:\s*[,;]\s*){2,}", ", ", remainder)
    remainder = re.sub(r"\s+", " ", remainder).strip(" ,;:-")
    return {f: found.get(f) for f in _LIMIT_PATTERNS}, remainder


def parse_request(text: str) -> Constraints:
    """Deliberately bounded English grammar; unrestricted language belongs to the MCP client."""
    if len(text) > 1000:
        raise ValueError("Request too long")
    limits, _ = limits_from_text(text)
    topic = re.search(r"\bon\s+(.+?)(?:,|;|$)", text, re.I)
    lang = re.search(r"\blanguage\s+([a-z]{2,3}(?:-[A-Za-z]{2,4})?)\b", text, re.I)
    if not topic or not re.search(r"\bplaylist\b", text, re.I):
        raise ValueError(
            "Use: Build a 2 hour playlist on Python, 8 videos, no video over 20 minutes, at least 5 minutes, language en; or send structured constraints"
        )
    return Constraints(
        topic=topic[1].strip(),
        language=lang[1].lower() if lang else None,
        **limits,
    )


# YouTube search can filter by duration: short < 4 min, medium 4-20 min, long > 20 min.
YOUTUBE_DURATION_BUCKETS = (("short", 1, 239), ("medium", 240, 1200), ("long", 1201, None))


def duration_buckets(c: Constraints) -> list[str]:
    """YouTube duration buckets that can hold a video allowed by c; empty means search 'any'."""
    low = c.min_seconds or 1
    names = [
        name
        for name, bucket_low, bucket_high in YOUTUBE_DURATION_BUCKETS
        if (c.max_seconds is None or bucket_low <= c.max_seconds)
        and (bucket_high is None or low <= bucket_high)
    ]
    return [] if len(names) == len(YOUTUBE_DURATION_BUCKETS) else names


def analyse(
    events: list[dict],
    start: str | None = None,
    end: str | None = None,
    previous_start: str | None = None,
) -> dict:
    channels, categories, months, sources = Counter(), Counter(), Counter(), Counter()
    lengths, dates = [], []
    for e in events:
        v = e["video"]
        channels[v["channel_title"]] += 1
        categories[v["category"]] += 1
        lengths.append(v["seconds"])
        sources[e["source"]] += 1
        if e.get("at"):
            dt = datetime.fromisoformat(e["at"].replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dates.append(dt)
            months[dt.strftime("%Y-%m")] += 1
    result = {
        "sample_count": len(events),
        "dated_count": len(dates),
        "top_channels": channels.most_common(10),
        "categories": dict(categories),
        "months": dict(sorted(months.items())),
        "sources": dict(sources),
        "mean_duration_seconds": round(sum(lengths) / len(lengths), 1) if lengths else 0,
        "duration_buckets": {
            "under_5m": sum(x < 300 for x in lengths),
            "5_to_20m": sum(300 <= x <= 1200 for x in lengths),
            "over_20m": sum(x > 1200 for x in lengths),
        },
        "caveat": "Bounded metadata sample; not watch history. Liked-video activity dates are unavailable. Playlist dates reflect additions; subscription dates reflect subscriptions.",
    }
    if any([start, end, previous_start]):
        if not all([start, end, previous_start]):
            raise ValueError("Provide start, end and previous_start together")

        def utc(value):
            parsed = datetime.fromisoformat(value)
            return (
                parsed.astimezone(timezone.utc)
                if parsed.tzinfo
                else parsed.replace(tzinfo=timezone.utc)
            )

        a, b, p = [utc(x) for x in (start, end, previous_start)]
        if not p < a < b:
            raise ValueError("Require previous_start < start < end")
        current, previous = sum(a <= d < b for d in dates), sum(p <= d < a for d in dates)
        result["period_comparison"] = {
            "current": current,
            "previous": previous,
            "delta": current - previous,
            "equal_length_periods": a - p == b - a,
        }
    return result
