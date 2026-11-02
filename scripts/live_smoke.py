"""Opt-in official API smoke. Maximum one videos.list call (1 unit), zero searches/writes."""

import asyncio
import os
import tempfile
from pathlib import Path

import httpx
from cryptography.fernet import Fernet

from ytintel.auth import OAuth
from ytintel.providers.google import GoogleProvider
from ytintel.quota import Quota
from ytintel.store import Store


async def main():
    names = ["LIVE_CLIENT_ID", "LIVE_CLIENT_SECRET", "LIVE_REFRESH_TOKEN"]
    if not all(os.getenv(n) for n in names):
        print("SKIP: live OAuth secrets not configured. No network calls made.")
        return
    with tempfile.TemporaryDirectory() as directory:
        store = Store(str(Path(directory) / "live.db"), Fernet.generate_key().decode())
        store.put(
            "oauth:tokens",
            {
                "access_token": "",
                "refresh_token": os.environ["LIVE_REFRESH_TOKEN"],
                "expires_at": 0,
            },
        )
        async with httpx.AsyncClient(timeout=20) as client:
            oauth = OAuth(
                store,
                client,
                os.environ["LIVE_CLIENT_ID"],
                os.environ["LIVE_CLIENT_SECRET"],
                "http://localhost:8000/oauth/callback",
            )
            provider = GoogleProvider(client, oauth.access_token, store)
            quota = Quota(store, units=1, searches=0)
            with quota.reserve(1, 0):
                videos = await provider.videos(["rfscVS0vtbw"])
            assert isinstance(videos, list)
            assert quota.status()["units_used"] == 1
            print(
                "PASS: official videos.list; 1 unit, 0 searches, 0 writes. No personal response data printed."
            )


if __name__ == "__main__":
    asyncio.run(main())
