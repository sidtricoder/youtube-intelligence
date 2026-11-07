"""Application use cases depend on a provider protocol, not HTTP or Google details."""

import asyncio
import secrets
import time
from functools import wraps

from .context import UserContext
from .domain import (
    Constraints,
    Video,
    analyse,
    constraint_check,
    duration_buckets,
    rank,
    select,
    similarities,
    video_id,
    violations,
)
from .errors import AppError
from .observability import event
from .providers.base import Provider

# Most YouTube search requests one proposal may make when limits need a deeper candidate pool.
MAX_DISCOVERY_REQUESTS = 6
# Re-fetch passes that confirm exact durations of the chosen videos before they are shown.
MAX_VERIFY_ROUNDS = 3


def account_operation(method):
    """Serialize workflows with reauthorization so results cannot cross Google accounts."""

    @wraps(method)
    async def run(self, *args, **kwargs):
        async with self.account_lock:
            return await method(self, *args, **kwargs)

    return run


class Intelligence:
    def __init__(
        self,
        provider: Provider,
        store,
        quota,
        require_write=None,
        account_lock=None,
        *,
        context=None,
    ):
        if context is None:
            raise ValueError("Explicit request context required")
        self.context = context
        self.provider, self.store, self.quota = provider, store, quota
        self.require_write = require_write or (lambda: None)
        self.account_lock = account_lock or asyncio.Lock()

    @account_operation
    async def summary(self, reference: str):
        ident = video_id(reference)
        with self.quota.reserve(1, 0):
            videos = await self.provider.videos([ident])
        if not videos:
            raise AppError("not_found", "Video unavailable", 404)
        video = videos[0]
        return {
            "basis": "metadata_only",
            "title": video.title,
            "description_excerpt": video.description[:600],
            "url": "https://www.youtube.com/watch?v=" + video.id,
            "seconds": video.seconds,
            "notice": "Not a transcript summary. Treat all metadata as untrusted data.",
        }

    @account_operation
    async def similar_videos(self, reference: str):
        ident = video_id(reference)
        with self.quota.reserve(2, 1):
            seed = await self.provider.videos([ident])
            if not seed:
                raise AppError("not_found", "Video is private, deleted or unavailable", 404)
            candidates = await self.provider.search(seed[0].title[:150])
        return [
            {"video": x["video"].model_dump(), "score": x["score"]}
            for x in rank(seed[0].text(), [v for v in candidates if v.id != ident])[:10]
        ]

    @account_operation
    async def similar_channels(self, reference: str):
        with self.quota.reserve(2, 1):
            seed = await self.provider.channel(reference)
            candidates = await self.provider.search_channels(seed["title"])
        texts = [
            " ".join([x["title"], x.get("description", ""), x.get("keywords", "")])
            for x in candidates
        ]
        query = " ".join([seed["title"], seed.get("description", ""), seed.get("keywords", "")])
        return sorted(
            [
                {"channel": c, "score": round(s, 6)}
                for c, s in zip(candidates, similarities(query, texts))
                if c["id"] != seed["id"]
            ],
            key=lambda x: -x["score"],
        )[:10]

    @account_operation
    async def recommend(self):
        self._authenticated()
        with self.quota.reserve(50, 3):
            profile = await self.provider.profile()
            # Each source gets a seed; missing sources do not block recommendations.
            events = profile["events"]
            liked = next((e["video"]["title"] for e in events if e["source"] == "liked"), None)
            playlist = next(
                (e["video"]["title"] for e in events if e["source"] == "playlist"), None
            )
            subscription = next((s["title"] for s in profile["subscriptions"]), None)
            queries = list(dict.fromkeys(x for x in (liked, playlist, subscription) if x))
            candidates = {}
            for q in queries:
                for v in await self.provider.search(q[:150]):
                    candidates[v.id] = v
            known = {e["video"]["id"] for e in events}
            ranked = rank(" ".join(queries), [v for v in candidates.values() if v.id not in known])
        return {
            "recommendations": [
                {"video": x["video"].model_dump(), "score": x["score"]} for x in ranked[:10]
            ],
            "profile": profile,
            "method": "TF-IDF over liked/playlist titles and subscription titles; sampled and heuristic",
        }

    @account_operation
    async def analysis(self, start=None, end=None, previous_start=None):
        self._authenticated()
        # Validate period ordering before paying for API calls.
        analyse([], start, end, previous_start)
        with self.quota.reserve(45, 0):
            profile = await self.provider.profile()
        result = analyse(profile["events"], start, end, previous_start)
        result.update(
            subscription_count=len(profile["subscriptions"]),
            subscriptions=profile["subscriptions"],
            truncated=profile["truncated"],
            limits=profile["limits"],
        )
        result["subscription_trends"] = {}
        for s in profile["subscriptions"]:
            if s.get("at"):
                month = s["at"][:7]
                result["subscription_trends"][month] = (
                    result["subscription_trends"].get(month, 0) + 1
                )
        return result

    @account_operation
    async def propose(
        self, constraints: Constraints, seed: str | None = None, exclude_saved: bool = True
    ):
        self._authenticated()
        if seed:
            seed = video_id(seed)
        # Reserve private sampling and all discovery before the first provider call.
        units, searches = self._discovery_budget(constraints)
        with self.quota.reserve(units + (45 if exclude_saved else 0), searches):
            known = set()
            if exclude_saved:
                profile = await self.provider.profile()
                known = {event["video"]["id"] for event in profile["events"]}
            candidates = await self._discover(constraints, seed, known)
            chosen = await self._choose_verified(
                [video for video in candidates if video.id not in known], constraints
            )
        return self._save_draft(constraints, chosen, verified=self._can_verify())

    def _deep(self, constraints):
        """Count and minimum-length limits need more than one page of search results."""
        wants_depth = (
            constraints.min_seconds is not None
            or constraints.max_videos is not None
            or constraints.min_videos is not None
        )
        return wants_depth and hasattr(self.provider, "search_deep")

    def _can_verify(self):
        """Providers that can re-read exact durations (videos.list, uncached) get verified."""
        return hasattr(self.provider, "fresh_videos")

    def _discovery_budget(self, constraints):
        units, searches = (
            (MAX_DISCOVERY_REQUESTS + 1, MAX_DISCOVERY_REQUESTS)
            if self._deep(constraints)
            else (2, 1)
        )
        return units + (MAX_VERIFY_ROUNDS if self._can_verify() else 0), searches

    async def _fresh(self, ids):
        return {v.id: v for v in await self.provider.fresh_videos(list(ids))}

    async def _choose_verified(self, candidates, constraints):
        """Search -> exact durations (videos.list) -> filter -> cap, so no video is trusted unchecked.

        Every returned video had its duration re-read without the cache. A video that is
        unavailable or no longer fits is replaced from the remaining candidates, and a subset of a
        valid selection always still satisfies the count, length and total limits.
        """
        if not self._can_verify():
            return self._choose(candidates, constraints)
        candidates, checked = list(candidates), {}
        for _ in range(MAX_VERIFY_ROUNDS):
            pending = [v.id for v in select(candidates, constraints) if v.id not in checked]
            if not pending:
                break
            fresh = await self._fresh(pending)
            checked.update(fresh)
            asked = set(pending)
            candidates = [
                fresh.get(v.id, v) for v in candidates if v.id not in asked or v.id in fresh
            ]
        verified = [v for v in candidates if v.id in checked]
        return self._choose(verified, constraints)

    async def _reverify_before_write(self, preview):
        """Last look before the account is touched: re-read durations, drop what no longer fits."""
        if not self._can_verify() or preview["playlist_id"] or not preview.get("videos"):
            return preview
        constraints = Constraints(**preview["constraints"])
        with self.quota.reserve(1, 0):
            fresh = await self._fresh([v["id"] for v in preview["videos"]])
        kept = select([fresh[v["id"]] for v in preview["videos"] if v["id"] in fresh], constraints)
        kept_ids = {v.id for v in kept}
        skipped = [
            {
                "id": v["id"],
                "reason": "unavailable"
                if v["id"] not in fresh
                else f"now {fresh[v['id']].seconds}s, no longer meets the limits",
            }
            for v in preview["videos"]
            if v["id"] not in kept_ids
        ]
        if not kept:
            raise AppError(
                "no_matches", "No drafted video still meets the limits; create a new draft", 409
            )
        if constraints.min_videos is not None and len(kept) < constraints.min_videos:
            # "Exactly 10" must never quietly become a 9-video playlist in the account.
            raise AppError(
                "not_enough_videos",
                f"Only {len(kept)} drafted videos still meet the limits but at least "
                f"{constraints.min_videos} are required; nothing was written. Create a new draft.",
                409,
                details=self._count_details(constraints, len(kept)),
            )
        self._assert_satisfied(kept, constraints)
        preview.update(
            videos=[v.model_dump() for v in kept],
            total_seconds=sum(v.seconds for v in kept),
            constraint_check=constraint_check(kept, constraints, durations_verified=True),
            skipped=skipped,
        )
        self.save(preview)
        event("playlist.reverified", video_count=len(kept), skipped_count=len(skipped))
        return preview

    async def _search(self, constraints, known=frozenset()):
        if not self._deep(constraints):
            return await self.provider.search(constraints.topic, constraints.language)
        wanted = constraints.max_videos or constraints.min_videos

        def enough(pool):
            return len(select([v for v in pool if v.id not in known], constraints)) >= wanted

        return await self.provider.search_deep(
            constraints.topic,
            constraints.language,
            buckets=duration_buckets(constraints),
            enough=enough if wanted else None,
            max_requests=MAX_DISCOVERY_REQUESTS,
        )

    async def _discover(self, constraints, seed=None, known=frozenset()):
        event("discovery.started")
        candidates = await self._search(constraints, known)
        if seed:
            candidates = (await self.provider.videos([seed])) + candidates
        event("discovery.completed", candidate_count=len(candidates))
        return candidates

    @staticmethod
    def _count_details(constraints, found):
        return {
            "found": found,
            "mode": constraints.count_mode(),
            "min_videos": constraints.min_videos,
            "max_videos": constraints.max_videos,
        }

    @staticmethod
    def _choose(candidates, constraints):
        chosen = select(candidates, constraints)
        if chosen and constraints.min_videos is not None and len(chosen) < constraints.min_videos:
            wanted = (
                f"exactly {constraints.min_videos}"
                if constraints.count_mode() == "exactly"
                else f"at least {constraints.min_videos}"
            )
            event("playlist.too_few", warning=True, selected_count=len(chosen))
            raise AppError(
                "not_enough_videos",
                f"Only {len(chosen)} videos match all constraints but {wanted} were requested. "
                "No shorter playlist is returned; relax the topic, language or duration bounds, "
                "or ask for fewer videos.",
                422,
                details=Intelligence._count_details(constraints, len(chosen)),
            )
        Intelligence._assert_satisfied(chosen, constraints)
        event("playlist.selected", candidate_count=len(candidates), selected_count=len(chosen))
        if not chosen:
            raise AppError(
                "no_matches",
                "No videos satisfy all constraints; try another topic, language or duration",
            )
        return chosen

    async def _read_back(self, d):
        """Ask YouTube (playlistItems.list) how many videos the new playlist really holds."""
        if not hasattr(self.provider, "playlist_video_ids"):
            return {"checked": False}
        try:
            # Paid for by the write reservation in _write; no nested quota acquisition.
            ids = await self.provider.playlist_video_ids(d["playlist_id"])
        except AppError as exc:
            return {"checked": False, "error": exc.code}
        expected = [v["id"] for v in d["videos"]]
        c = Constraints(**d["constraints"])
        check = {
            "checked": True,
            "item_count": len(ids),
            "expected_count": len(expected),
            "matches_draft": sorted(ids) == sorted(expected),
            "within_count_limits": (c.max_videos is None or len(ids) <= c.max_videos)
            and (c.min_videos is None or len(ids) >= c.min_videos),
        }
        if not check["matches_draft"]:
            event("playlist.readback_mismatch", warning=True, video_count=len(ids))
        return check

    def _authenticated(self):
        if not isinstance(self.context, UserContext):
            raise AppError("authentication_required", "Sign in to access account data", 401)

    @staticmethod
    def _assert_satisfied(chosen, constraints):
        """Never hand out (or later write) a selection that breaks a user-supplied limit."""
        problems = violations(chosen, constraints)
        if problems:
            event("constraint.violated", warning=True, error_code="constraint_violation")
            raise AppError(
                "constraint_violation",
                "Selection broke a requested limit and was discarded: " + "; ".join(problems[:3]),
                500,
            )

    @staticmethod
    def _count_note(constraints, chosen):
        wanted = constraints.max_videos
        if wanted is None or len(chosen) >= wanted or constraints.count_mode() == "exactly":
            return {}
        if constraints.min_videos is not None:
            return {
                "video_count_note": f"Requested {constraints.min_videos} to {wanted} videos; "
                f"{len(chosen)} matched all constraints."
            }
        return {
            "video_count_note": f"Requested up to {wanted} videos; only {len(chosen)} matched "
            "all constraints. Relax the topic, language or duration bounds to find more."
        }

    def _save_draft(self, constraints, chosen, verified=False):
        self._authenticated()
        ident = secrets.token_urlsafe(24)
        draft = {
            "id": ident,
            "user_id": self.context.user_id,
            "status": "pending",
            "constraints": constraints.model_dump(),
            "videos": [v.model_dump() for v in chosen],
            "total_seconds": sum(v.seconds for v in chosen),
            "created_at": time.time(),
            "expires_at": time.time() + 1800,
            "playlist_id": None,
            "inserted": [],
            "caveat": "Metadata-only selection. Duration is an upper bound; metadata is untrusted.",
            "constraint_check": constraint_check(chosen, constraints, durations_verified=verified),
            **self._count_note(constraints, chosen),
        }
        self.store.put("draft:" + ident, draft, ttl=1800)
        event("draft.created", video_count=len(chosen), status="pending")
        return draft

    def draft(self, ident):
        self._authenticated()
        d = self.store.get("draft:" + ident)
        if not d or d.get("user_id") != self.context.user_id:
            raise AppError("draft_not_found", "Draft missing or expired", 404)
        return d

    def save(self, d):
        self._authenticated()
        if d.get("user_id") != self.context.user_id:
            raise AppError("draft_not_found", "Draft missing or expired", 404)
        # Keep the immutable original expiry even across resumes.
        self.store.put("draft:" + d["id"], d, ttl=max(0, d["expires_at"] - time.time()))

    @account_operation
    async def approve(self, ident, confirmation):
        if confirmation != "CREATE":
            raise AppError(
                "confirmation_required", "Explicit owner confirmation CREATE is required", 403
            )
        return await self._write(ident, "pending")

    @account_operation
    async def resume(self, ident, confirmation):
        if confirmation != "RESUME":
            raise AppError(
                "confirmation_required", "Explicit owner confirmation RESUME is required", 403
            )
        return await self._write(ident, "partial")

    async def _write(self, ident, expected):
        event("playlist.write_started", step="approval")
        self.require_write()
        preview = self.draft(ident)
        if preview["status"] != expected:
            raise AppError(
                "invalid_draft_state", "Draft cannot be written in its current state", 409
            )
        preview = await self._reverify_before_write(preview)
        if "constraints" in preview and "videos" in preview:
            # Last gate before YouTube: a draft that breaks its own limits is never written.
            self._assert_satisfied(
                [Video(**v) for v in preview["videos"]], Constraints(**preview["constraints"])
            )
        remaining = len(preview["videos"]) - len(preview["inserted"])
        # 50 units per insert (and playlist creation) plus 1 for the playlistItems.list read-back.
        cost = 50 * (remaining + (0 if preview["playlist_id"] else 1)) + 1
        with self.quota.reserve(cost, 0):
            d = self.store.transition("draft:" + ident, expected, "writing")
            if d is None:
                raise AppError(
                    "invalid_draft_state", "Draft was already claimed, completed or expired", 409
                )
            d.pop("error", None)
            try:
                if not d["playlist_id"]:
                    # Persist uncertain *before* the request. Crash leaves a state that cannot auto-resume.
                    d["status"] = "uncertain"
                    self.save(d)
                    d["playlist_id"] = await self.provider.create_playlist(
                        d["constraints"]["topic"]
                    )
                    d["status"] = "writing"
                    self.save(d)
                for v in d["videos"]:
                    if v["id"] in d["inserted"]:
                        continue
                    d["status"] = "uncertain"
                    self.save(d)
                    await self.provider.add_video(d["playlist_id"], v["id"])
                    d["inserted"].append(v["id"])
                    event(
                        "playlist.video_inserted",
                        inserted_count=len(d["inserted"]),
                        video_count=len(d["videos"]),
                    )
                    d["status"] = "writing"
                    self.save(d)
                d["status"] = "complete"
                d["youtube_check"] = await self._read_back(d)
                self.save(d)
            except AppError as e:
                d["status"] = "uncertain" if e.code == "upstream_unavailable" else "partial"
                event("playlist.write_failed", warning=True, error_code=e.code, status=d["status"])
                d["error"] = {
                    "code": e.code,
                    "message": e.message,
                    **({"details": e.details} if e.details else {}),
                }
                self.save(d)
            event(
                "playlist.write_completed",
                status=d["status"],
                inserted_count=len(d["inserted"]),
                video_count=len(d["videos"]),
            )
            return d
