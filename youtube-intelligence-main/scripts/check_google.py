"""Minimal opt-in live public checks; Google enforces quota, no playlist writes."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path

from ytintel.app import create_app
from ytintel.config import Settings
from ytintel.domain import Constraints
from ytintel.errors import AppError


async def check(output: Path):
    configured = Settings()
    report = {
        "project_id": configured.google_project_id,
        "callback": configured.redirect_uri,
        "checks": [],
        "live_writes": 0,
        "quota_enforcement": "google",
    }
    with tempfile.TemporaryDirectory() as directory:
        settings = configured.model_copy(
            update={
                "db_path": str(Path(directory) / "live.db"),
                "database_url": None,
                "database_url_pooled": None,
            }
        )
        app = create_app(settings)
        context = await app.state.context_factory(None, "127.0.0.1")
        service = app.state.service_factory(context)

        async def record(name, run):
            try:
                details = await run()
                report["checks"].append({"name": name, "status": "PASS", "details": details})
            except AppError as exc:
                report["checks"].append(
                    {"name": name, "status": "FAIL", "code": exc.code, "message": exc.message}
                )
            except Exception as exc:
                # Never serialize exception strings, URLs, headers or response bodies containing secrets.
                report["checks"].append(
                    {"name": name, "status": "FAIL", "exception_type": type(exc).__name__}
                )

        async def direct_video():
            with service.quota.reserve(1, 0):
                videos = await service.provider.videos(["rfscVS0vtbw"])
            assert videos, "Known public video unavailable"
            return {"videos_returned": len(videos)}

        async def similar_video():
            rows = await service.similar_videos("rfscVS0vtbw")
            assert rows
            return {"ranked_candidates": len(rows)}

        async def similar_channel():
            rows = await service.similar_channels("@freecodecamp")
            assert rows
            return {"ranked_candidates": len(rows)}

        async def preview():
            d = await service.preview(
                Constraints(
                    topic="Python programming tutorial", total_seconds=3600, max_seconds=1200
                )
            )
            assert 0 < d["total_seconds"] <= 3600
            assert all(0 < v["seconds"] <= 1200 for v in d["videos"])
            return {
                "preview_videos": len(d["videos"]),
                "total_seconds": d["total_seconds"],
                "persisted_draft": False,
            }

        async with app.router.lifespan_context(app):
            await record("Official videos.list with supplied API key", direct_video)
            await record("FR1 live similar videos", similar_video)
            await record("FR2 live similar channels", similar_channel)
            await record("FR5 live constrained playlist preview (no write)", preview)
            report["quota"] = service.quota.status()
        report["blocked_checks"] = [
            {"name": "FR3 live personal recommendations", "reason": "User OAuth sign-in required"},
            {"name": "FR4 live personal analysis", "reason": "User OAuth sign-in required"},
            {
                "name": "Live playlist creation and insertion",
                "reason": "User OAuth sign-in and browser draft confirmation required",
            },
        ]
    report["passed"] = sum(c["status"] == "PASS" for c in report["checks"])
    report["failed"] = sum(c["status"] == "FAIL" for c in report["checks"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report["failed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/LIVE_CHECKS.json"))
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(args.output)) > 0)


if __name__ == "__main__":
    main()
