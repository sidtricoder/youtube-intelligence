import pytest
from cryptography.fernet import Fernet

from tests.fakes import FixtureProvider
from ytintel.domain import Constraints
from ytintel.errors import AppError
from ytintel.quota import Quota
from ytintel.service import Intelligence
from ytintel.store import Store


@pytest.fixture
def service(tmp_path):
    store = Store(str(tmp_path / "test.db"), Fernet.generate_key().decode())
    return Intelligence(FixtureProvider(), store, Quota(store))


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


async def test_ambiguous_write_stops_retry(service):
    d = await service.propose(Constraints(topic="Python", total_seconds=1800, max_seconds=1200))

    async def fail(*args):
        raise AppError("upstream_unavailable", "timeout", 503)

    service.provider.create_playlist = fail
    result = await service.approve(d["id"], "CREATE")
    assert result["status"] == "uncertain"
    with pytest.raises(AppError):
        await service.resume(d["id"], "RESUME")


async def test_quota_rejects_before_provider_call(service):
    service.quota = Quota(service.store, units=0, searches=0)

    async def forbidden(*args):
        pytest.fail("provider must not be called")

    service.provider.search = forbidden
    with pytest.raises(AppError):
        await service.propose(Constraints(topic="Python", total_seconds=600, max_seconds=600))
