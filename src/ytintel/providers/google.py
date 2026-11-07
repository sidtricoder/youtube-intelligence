"""Official YouTube Data API v3 adapter. No scraping, transcripts or hidden API calls."""

import hashlib
import json
import time

import httpx

from ..context import AnonymousContext
from ..domain import Video, channel_ref, duration
from ..errors import AppError
from ..observability import event
from ..quota import active_ticket
from ..tenancy import PublicStore

BASE = "https://www.googleapis.com/youtube/v3/"


class GoogleProvider:
    def __init__(
        self,
        client,
        token,
        store,
        public_api_key="",
        *,
        context=None,
        public_store=None,
        on_unauthorized=None,
    ):
        self.client, self.token, self.store = client, token, store
        self.context = context
        self.on_unauthorized = on_unauthorized
        self.public_store = public_store or (
            PublicStore(store.raw) if hasattr(store, "raw") else store
        )
        self.public_api_key = public_api_key

    async def request(self, endpoint, params=None, body=None):
        method = "POST" if body is not None else "GET"
        started = time.monotonic()
        operation = (
            endpoint
            if endpoint
            in {"search", "videos", "channels", "subscriptions", "playlists", "playlistItems"}
            else "unknown"
        )
        key = (
            "cache:"
            + hashlib.sha256(json.dumps([endpoint, params], sort_keys=True).encode()).hexdigest()
        )
        parameters = dict(params or {})
        public = method == "GET" and (
            endpoint == "search"
            or (
                endpoint in {"videos", "channels"}
                and not parameters.get("myRating")
                and not parameters.get("mine")
            )
        )
        cache_store = self.public_store if public else self.store
        if not public and isinstance(self.context, AnonymousContext):
            raise AppError("authentication_required", "Sign in to access account data", 401)
        if method == "GET":
            cached = cache_store.get(key)
            if cached is not None:
                event("youtube.cache_hit", endpoint=operation, public=public)
                return cached
        headers = {}
        if public:
            if not self.public_api_key:
                raise AppError("public_api_key_required", "Public API key is required", 503)
            headers["X-Goog-Api-Key"] = self.public_api_key
        else:
            credentials = self.context.credentials if self.context is not None else self.token
            headers["Authorization"] = "Bearer " + await credentials()
        ticket = active_ticket.get()
        if ticket is not None:
            ticket.consume(
                0 if endpoint == "search" else (50 if body is not None else 1),
                1 if endpoint == "search" else 0,
            )
        event("youtube.started", endpoint=operation, method=method, public=public)
        try:
            r = await self.client.request(
                method,
                BASE + endpoint,
                params=parameters,
                json=body,
                headers=headers,
            )
        except httpx.RequestError:
            event(
                "youtube.failed",
                warning=True,
                endpoint=operation,
                error_code="upstream_unavailable",
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            raise AppError(
                "upstream_unavailable",
                "YouTube connection failed; write outcome may be unknown",
                503,
            ) from None
        if r.status_code == 401 and not public and self.on_unauthorized is not None:
            await self.on_unauthorized()
        if r.status_code >= 400:
            try:
                errors = r.json().get("error", {}).get("errors", [])
                reason = errors[0].get("reason") if errors else ""
            except (ValueError, AttributeError, IndexError):
                reason = ""
            codes = {
                "keyInvalid": ("invalid_api_key", 403),
                "accessNotConfigured": ("api_not_enabled", 403),
                "ipRefererBlocked": ("api_key_restricted", 403),
                "quotaExceeded": ("quota_exceeded", 429),
                "dailyLimitExceeded": ("quota_exceeded", 429),
                "youtubeSignupRequired": ("channel_required", 403),
                "rateLimitExceeded": ("rate_limited", 429),
                "userRateLimitExceeded": ("rate_limited", 429),
            }
            code, status = codes.get(
                reason,
                ("reauthorization_required", 401)
                if r.status_code == 401
                else ("not_found", 404)
                if r.status_code == 404
                else ("rate_limited", 429)
                if r.status_code == 429
                else ("upstream_unavailable", 503)
                if r.status_code >= 500
                else ("forbidden", 403),
            )
            event(
                "youtube.failed",
                warning=True,
                endpoint=operation,
                status=r.status_code,
                error_code=code,
                duration_ms=round((time.monotonic() - started) * 1000, 2),
            )
            raise AppError(
                code,
                "YouTube request failed: " + code,
                status,
                details={
                    "source": "google",
                    "reason": reason if reason in codes else "unclassified",
                    "upstream_status": r.status_code,
                },
            )
        result = r.json()
        event(
            "youtube.completed",
            endpoint=operation,
            status=r.status_code,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )
        if method == "GET":
            cache_store.put(key, result, ttl=300)
        return result

    async def pages(self, endpoint, params, max_pages=2):
        items, token = [], None
        for _ in range(max_pages):
            response = await self.request(
                endpoint, {**params, **({"pageToken": token} if token else {})}
            )
            items.extend(response.get("items", []))
            token = response.get("nextPageToken")
            if not token:
                break
        return items, bool(token)

    async def videos(self, ids):
        result = []
        ids = list(dict.fromkeys(ids))
        for i in range(0, len(ids), 50):
            data = await self.request(
                "videos", {"part": "snippet,contentDetails", "id": ",".join(ids[i : i + 50])}
            )
            for v in data.get("items", []):
                s = v["snippet"]
                try:
                    seconds = duration(v["contentDetails"]["duration"])
                except (KeyError, ValueError):
                    continue
                result.append(
                    Video(
                        id=v["id"],
                        title=s["title"],
                        description=s.get("description", ""),
                        channel_id=s["channelId"],
                        channel_title=s["channelTitle"],
                        seconds=seconds,
                        language=s.get("defaultAudioLanguage", s.get("defaultLanguage")),
                        category=s.get("categoryId", "unknown"),
                        tags=s.get("tags", []),
                        published_at=s.get("publishedAt"),
                    )
                )
        return result

    @staticmethod
    def _search_params(query, language):
        params = {
            "part": "snippet",
            "type": "video",
            "q": query[:200],
            "maxResults": 50,
            "videoEmbeddable": "true",
            "safeSearch": "moderate",
        }
        if language:
            params["relevanceLanguage"] = language
        return params

    async def search(self, query, language=None):
        data = await self.request("search", self._search_params(query, language))
        return await self.videos([x["id"]["videoId"] for x in data.get("items", [])])

    async def search_deep(self, query, language=None, *, buckets=(), enough=None, max_requests=6):
        """Page through search results until enough candidates qualify.

        buckets restricts YouTube's videoDuration (short/medium/long) so a minimum or maximum
        length is applied at the source instead of discarding most of a single page. With
        enough=None one page per bucket is fetched; otherwise pages are fetched round-robin
        until enough(pool) is true, the results run out, or max_requests searches were made.
        """
        lanes = [{"videoDuration": name} for name in buckets] or [{}]
        tokens, done = [None] * len(lanes), [False] * len(lanes)
        pool, seen, made = [], set(), 0
        while made < max_requests and not all(done):
            for lane_number, lane in enumerate(lanes):
                if done[lane_number] or made >= max_requests:
                    continue
                params = self._search_params(query, language) | lane
                if tokens[lane_number]:
                    params["pageToken"] = tokens[lane_number]
                data = await self.request("search", params)
                made += 1
                tokens[lane_number] = data.get("nextPageToken")
                done[lane_number] = not tokens[lane_number]
                ids = [
                    ident
                    for item in data.get("items", [])
                    if (ident := item.get("id", {}).get("videoId")) and ident not in seen
                ]
                seen.update(ids)
                if ids:
                    pool.extend(await self.videos(ids))
            if enough is None or enough(pool):
                break
        return pool

    @staticmethod
    def channel_data(item):
        s = item["snippet"]
        return {
            "id": item["id"],
            "title": s["title"],
            "description": s.get("description", ""),
            "keywords": item.get("brandingSettings", {}).get("channel", {}).get("keywords", ""),
        }

    async def channel(self, ref):
        k, v = channel_ref(ref)
        data = await self.request("channels", {"part": "snippet,brandingSettings", k: v})
        if not data.get("items"):
            raise AppError("not_found", "Channel unavailable", 404)
        return self.channel_data(data["items"][0])

    async def search_channels(self, query):
        data = await self.request(
            "search", {"part": "snippet", "type": "channel", "q": query[:200], "maxResults": 25}
        )
        ids = [x["id"]["channelId"] for x in data.get("items", [])]
        if not ids:
            return []
        data = await self.request(
            "channels", {"part": "snippet,brandingSettings", "id": ",".join(ids)}
        )
        return [self.channel_data(x) for x in data.get("items", [])]

    async def profile(self):
        """Bounded sample: 100 likes, 100 subscriptions, 10 playlists x 100 items."""
        likes, likes_more = await self.pages(
            "videos", {"part": "snippet,contentDetails", "myRating": "like", "maxResults": 50}
        )
        # Reuse the same normalizer; no extra network for liked details.
        liked = []
        for v in likes:
            s = v["snippet"]
            try:
                liked.append(
                    Video(
                        id=v["id"],
                        title=s["title"],
                        description=s.get("description", ""),
                        channel_id=s["channelId"],
                        channel_title=s["channelTitle"],
                        seconds=duration(v["contentDetails"]["duration"]),
                        language=s.get("defaultAudioLanguage", s.get("defaultLanguage")),
                        category=s.get("categoryId", "unknown"),
                        tags=s.get("tags", []),
                    )
                )
            except (KeyError, ValueError):
                continue
        subs, subs_more = await self.pages(
            "subscriptions", {"part": "snippet", "mine": "true", "maxResults": 50}
        )
        playlists = await self.request(
            "playlists", {"part": "snippet", "mine": "true", "maxResults": 10}
        )
        entries = []
        truncated = bool(likes_more or subs_more or playlists.get("nextPageToken"))
        for p in playlists.get("items", [])[:10]:
            rows, more = await self.pages(
                "playlistItems",
                {"part": "snippet,contentDetails", "playlistId": p["id"], "maxResults": 50},
            )
            entries.extend(rows)
            truncated |= more
        ids = [x.get("contentDetails", {}).get("videoId") for x in entries]
        details = await self.videos([x for x in ids if x])
        index = {v.id: v for v in details}
        events = [{"video": v.model_dump(), "source": "liked", "at": None} for v in liked]
        events.extend(
            {
                "video": index[x["contentDetails"]["videoId"]].model_dump(),
                "source": "playlist",
                "at": x["snippet"].get("publishedAt"),
            }
            for x in entries
            if x.get("contentDetails", {}).get("videoId") in index
        )
        subscriptions = [
            {
                "id": s["snippet"]["resourceId"]["channelId"],
                "title": s["snippet"]["title"],
                "at": s["snippet"].get("publishedAt"),
            }
            for s in subs
        ]
        return {
            "events": events,
            "subscriptions": subscriptions,
            "truncated": truncated,
            "limits": {
                "likes": 100,
                "subscriptions": 100,
                "playlists": 10,
                "items_per_playlist": 100,
            },
        }

    async def create_playlist(self, title):
        data = await self.request(
            "playlists",
            {"part": "snippet,status"},
            {
                "snippet": {
                    "title": title[:150],
                    "description": "Curated with YouTube Intelligence; reviewed by owner.",
                },
                "status": {"privacyStatus": "private"},
            },
        )
        return data["id"]

    async def add_video(self, playlist_id, video_id):
        await self.request(
            "playlistItems",
            {"part": "snippet"},
            {
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            },
        )
