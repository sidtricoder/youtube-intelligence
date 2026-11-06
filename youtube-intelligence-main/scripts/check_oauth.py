"""Check local Google authorization request configuration without contacting Google."""

import argparse
import asyncio
import json
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from ytintel.config import Settings
from ytintel.identity import GoogleIdentityProvider


async def check(output: Path) -> dict:
    settings = Settings()
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        provider = GoogleIdentityProvider(
            client, settings.google_client_id, settings.google_client_secret, settings.redirect_uri
        )
        url = provider.authorization_url(
            secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        )
        query = parse_qs(urlsplit(url).query)
        valid = bool(settings.google_client_id and settings.google_client_secret)
        result = {
            "status": "PASS" if valid else "FAIL",
            "result": "Local authorization request configured"
            if valid
            else "Google OAuth client configuration required",
            "callback": settings.redirect_uri,
            "pkce": query["code_challenge_method"][0],
            "user_consent_completed": False,
            "google_callback_registration_verified": False,
            "network_requests": 0,
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/OAUTH_READINESS.json"))
    result = asyncio.run(check(parser.parse_args().output))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
