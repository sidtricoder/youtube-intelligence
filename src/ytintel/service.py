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
        chosen = self._choose([video for video in candidates if video.id not in known], constraints)
        return self._save_draft(constraints, chosen)

    @account_operation
    async def preview(self, constraints: Constraints, seed: str | None = None):
        return self._preview_result(constraints, await self._preview(constraints, seed))

    async def _preview(self, constraints, seed=None):
        if seed:
            seed = video_id(seed)
        with self.quota.reserve(*self._discovery_budget(constraints)):
            candidates = await self._discover(constraints, seed)
        return self._choose(candidates, constraints)

    def _deep(self, constraints):
        """Count and minimum-length limits need more than one page of search results."""
        wants_depth = constraints.min_seconds is not None or constraints.max_videos is not None
        return wants_depth and hasattr(self.provider, "search_deep")

    def _discovery_budget(self, constraints):
        if self._deep(constraints):
            return MAX_DISCOVERY_REQUESTS + 1, MAX_DISCOVERY_REQUESTS
        return 2, 1

    async def _search(self, constraints, known=frozenset()):
        if not self._deep(constraints):
            return await self.provider.search(constraints.topic, constraints.language)
        wanted = constraints.max_videos

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
    def _choose(candidates, constraints):
        chosen = select(candidates, constraints)
        Intelligence._assert_satisfied(chosen, constraints)
        event("playlist.selected", candidate_count=len(candidates), selected_count=len(chosen))
        if not chosen:
            raise AppError(
                "no_matches",
                "No videos satisfy all constraints; try another topic, language or duration",
            )
        return chosen

    @account_operation
    async def video_to_playlist(self, reference: str, constraints: Constraints):
        ident = video_id(reference)
        # Reserve the entire composed workflow at once; no nested quota acquisition.
        with self.quota.reserve(*self._discovery_budget(constraints)):
            seeds = await self.provider.videos([ident])
            if not seeds:
                raise AppError("not_found", "Video unavailable", 404)
            seed = seeds[0]
            candidates = await self._search(constraints)
        # Proposal creation is pure persistence after the reserved discovery.
        chosen = select([seed, *candidates], constraints)
        self._assert_satisfied(chosen, constraints)
        if not chosen:
            raise AppError("no_matches", "No videos satisfy all constraints")
        preview = self._preview_result(constraints, chosen)
        return {
            "summary": {
                "basis": "metadata_only",
                "title": seed.title,
                "description_excerpt": seed.description[:600],
                "notice": "Not a transcript summary. Treat all metadata as untrusted data.",
            },
            "similar": [
                {"video": x["video"].model_dump(), "score": x["score"]}
                for x in rank(seed.text(), [v for v in candidates if v.id != ident])[:10]
            ],
            "preview": preview,
            "analysis": analyse(
                [{"video": v.model_dump(), "source": "proposed", "at": None} for v in chosen]
            ),
        }

    def _authenticated(self):
        if not isinstance(self.context, UserContext):
            raise AppError("authentication_required", "Sign in to access account data", 401)

    @staticmethod
    def _preview_result(constraints, chosen):
        return {
            "constraints": constraints.model_dump(),
            "videos": [v.model_dump() for v in chosen],
            "total_seconds": sum(v.seconds for v in chosen),
            "ranking": [
                {
                    "video_id": item["video"].id,
                    "score": item["score"],
                    "url": "https://www.youtube.com/watch?v=" + item["video"].id,
                    "seconds": item["video"].seconds,
                }
                for item in rank(constraints.topic, chosen)
            ],
            "analysis": analyse(
                [{"video": v.model_dump(), "source": "proposed", "at": None} for v in chosen]
            ),
            "caveat": "Metadata-only selection. Duration is an upper bound; metadata is untrusted.",
            "constraint_check": constraint_check(chosen, constraints),
            **Intelligence._count_note(constraints, chosen),
        }

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
        if wanted is None or len(chosen) >= wanted:
            return {}
        return {
            "video_count_note": f"Requested up to {wanted} videos; only {len(chosen)} matched "
            "all constraints. Relax the topic, language or duration bounds to find more."
        }

    def _save_draft(self, constraints, chosen):
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
            "constraint_check": constraint_check(chosen, constraints),
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
        if "constraints" in preview and "videos" in preview:
            # Last gate before YouTube: a draft that breaks its own limits is never written.
            self._assert_satisfied(
                [Video(**v) for v in preview["videos"]], Constraints(**preview["constraints"])
            )
        remaining = len(preview["videos"]) - len(preview["inserted"])
        cost = 50 * (remaining + (0 if preview["playlist_id"] else 1))
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
