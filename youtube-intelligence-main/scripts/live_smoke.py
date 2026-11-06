"""Opt-in official public API smoke: one videos.list call, zero searches or writes."""

import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from ytintel.errors import AppError
from ytintel.providers.google import GoogleProvider
from ytintel.quota import Quota
from ytintel.store import Store


async def main():
    key = os.getenv("LIVE_YOUTUBE_API_KEY", "")
    if not key:
        print("SKIP: LIVE_YOUTUBE_API_KEY not configured. No network calls made.")
        return 0

    async def no_account_credentials():
        raise AppError("authentication_required", "Public smoke has no account credentials", 401)

    with tempfile.TemporaryDirectory() as directory:
        store = Store(str(Path(directory) / "live.db"), Fernet.generate_key().decode())
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                provider = GoogleProvider(client, no_account_credentials, store, public_api_key=key)
                quota = Quota(store, units=1, searches=0)
                with quota.reserve(1, 0):
                    videos = await provider.videos(["rfscVS0vtbw"])
                assert isinstance(videos, list)
                assert quota.status()["units_used"] == 1
                print("PASS: official videos.list; 1 unit, 0 searches, 0 writes.")
        except AppError as exc:
            print("FAIL: public API check failed (" + exc.code + ").")
            return 1
        finally:
            store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
