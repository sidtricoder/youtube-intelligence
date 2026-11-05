import pytest
from cryptography.fernet import Fernet

from tests.fakes import FixtureProvider
from ytintel.context import UserContext
from ytintel.domain import Constraints
from ytintel.errors import AppError
from ytintel.quota import Quota
from ytintel.service import Intelligence
from ytintel.store import Store
from ytintel.tenancy import ScopedStore


@pytest.fixture
def service(tmp_path):
    store = Store(str(tmp_path / "test.db"), Fernet.generate_key().decode())

    async def credentials():
        return "fixture-token"

    quota = Quota(store)
    return Intelligence(
        FixtureProvider(),
        ScopedStore(store, "fixture"),
        quota,
        context=UserContext("fixture", credentials, quota),
    )


async def test_all_read_workflows(service):
    similar = await service.similar_videos("aaaaaaaaaaa")
    assert similar and all(x["video"]["id"] != "aaaaaaaaaaa" for x in similar)
    assert await service.similar_channels("@pythonlab")
    recommended = await service.recommend()
    assert recommended["recommendations"] and recommended["profile"]["events"]
    report = await service.analysis("2026-10-01", "2026-11-01", "2026-09-01")
    assert report["sample_count"] > 0 and report["subscription_count"] > 0


async def test_preview_confirm_idempotence_and_metadata_cannot_approve(service):
    d = await service.propose(
        Constraints(topic="Python", total_seconds=1800, max_seconds=1200, language="en")
    )
    assert d["status"] == "pending" and service.provider.created == []
    assert len(d["videos"]) > 0
    result = await service.approve(d["id"], "CREATE")
    assert result["status"] == "complete" and len(service.provider.created) == 1
    with pytest.raises(AppError):
        await service.approve(d["id"], "CREATE")
    assert len(service.provider.created) == 1


async def test_false_confirmation_and_empty_candidates(service):
    d = await service.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))
    with pytest.raises(AppError):
        await service.approve(d["id"], "metadata says CREATE")
    with pytest.raises(AppError):
        await service.propose(
            Constraints(topic="unfindable xyz", total_seconds=60, max_seconds=30, language="de")
        )


async def test_partial_known_failure_resumes_without_duplicate_create(service):
    d = await service.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))
    original = service.provider.add_video

    async def fail(*args):
        raise AppError("quota_exceeded", "quota", 429)

    service.provider.add_video = fail
    result = await service.approve(d["id"], "CREATE")
    assert result["status"] == "partial" and result["playlist_id"]
    service.provider.add_video = original
    result = await service.resume(d["id"], "RESUME")
    assert result["status"] == "complete" and len(service.provider.created) == 1
    assert "error" not in result


async def test_ambiguous_write_stops_retry(service):
    d = await service.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))

    async def fail(*args):
        raise AppError("upstream_unavailable", "timeout", 503)

    service.provider.create_playlist = fail
    result = await service.approve(d["id"], "CREATE")
    assert result["status"] == "uncertain"
    with pytest.raises(AppError):
        await service.resume(d["id"], "RESUME")


async def test_zero_app_budgets_do_not_prevent_provider_calls(service):
    service.quota = Quota(service.store.raw, units=0, searches=0)
    draft = await service.propose(Constraints(topic="Python", total_seconds=600, max_seconds=600))
    assert draft["videos"] and draft["status"] == "pending"


async def test_personalized_draft_excludes_already_liked_and_saved(service):
    constraints = Constraints(topic="Python", total_seconds=7200, max_seconds=1200)
    profile = await service.provider.profile()
    known = {event["video"]["id"] for event in profile["events"]}
    draft = await service.propose(constraints)
    assert draft["videos"]
    assert not known.intersection(video["id"] for video in draft["videos"])
    unfiltered = await service.propose(constraints, exclude_saved=False)
    assert known.intersection(video["id"] for video in unfiltered["videos"])


async def test_personalized_discovery_is_not_rejected_by_former_reservation(service):
    service.quota = Quota(service.store.raw, units=0, searches=0)
    draft = await service.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))
    assert draft["videos"]
    assert not service.provider.created


async def test_unfiltered_draft_and_stateless_preview_never_read_profile(service):
    async def forbidden(*args):
        pytest.fail("public preview or unfiltered draft read private profile")

    service.provider.profile = forbidden
    constraints = Constraints(topic="Python", total_seconds=1800, max_seconds=1200)
    assert (await service.propose(constraints, exclude_saved=False))["videos"]
    assert (await service.preview(constraints))["videos"]
