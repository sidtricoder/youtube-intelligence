"""Synthetic, deterministic fixtures. Never writes to a Google account."""

from ytintel.domain import Video, channel_ref, video_id
from ytintel.errors import AppError


class FixtureProvider:
    def __init__(self):
        self.created = []
        self.inserted = []
        self.items = [
            Video(
                id=letter * 11,
                title=title,
                description="Python programming education " + title,
                channel_id="UC" + channel * 22,
                channel_title="Python Lab " + channel,
                seconds=seconds,
                language="en",
                category="27",
                tags=["python", "tutorial"],
            )
            for letter, title, seconds, channel in [
                ("a", "Python fundamentals", 600, "a"),
                ("b", "Python functions", 480, "a"),
                ("c", "Python SOLID design", 720, "b"),
                ("d", "FastAPI with Python", 900, "b"),
                ("e", "Python testing and pytest", 600, "c"),
                ("f", "Python async programming", 1200, "c"),
            ]
        ]

    async def videos(self, ids):
        for i in ids:
            video_id(i)
        result = [v for v in self.items if v.id in ids]
        return result

    async def search(self, query, language=None):
        return list(self.items)

    async def channel(self, ref):
        channel_ref(ref)
        return {
            "id": "UC" + "a" * 22,
            "title": "Python Lab a",
            "description": "Python programming education",
            "keywords": "python",
        }

    async def search_channels(self, query):
        return [
            {
                "id": "UC" + c * 22,
                "title": "Python Lab " + c,
                "description": "Python education and programming tutorials",
                "keywords": "python testing",
            }
            for c in "abc"
        ]

    async def profile(self):
        return {
            "events": [
                {"video": v.model_dump(), "source": source, "at": at}
                for v, source, at in [
                    (self.items[0], "liked", None),
                    (self.items[1], "playlist", "2026-10-10T12:00:00Z"),
                    (self.items[2], "playlist", "2026-09-10T12:00:00Z"),
                ]
            ],
            "subscriptions": [
                {"id": "UC" + "c" * 22, "title": "Python Lab c", "at": "2026-10-01T00:00:00Z"}
            ],
            "truncated": False,
            "limits": {"fixture": True},
        }

    async def create_playlist(self, title):
        playlist = "FIXTURE_PLAYLIST_" + str(len(self.created) + 1)
        self.created.append({"id": playlist, "title": title})
        return playlist

    async def playlist_video_ids(self, playlist_id):
        return [v for p, v in self.inserted if p == playlist_id]

    async def add_video(self, playlist_id, video_id):
        if not any(x["id"] == playlist_id for x in self.created):
            raise AppError("not_found", "Fixture playlist missing", 404)
        self.inserted.append((playlist_id, video_id))
