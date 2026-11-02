"""Verify fixed Google OAuth redirect readiness without completing user sign-in."""

import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet

from ytintel.auth import OAuth
from ytintel.config import Settings
from ytintel.store import Store


async def check(output: Path) -> dict:
    settings = Settings()
    with tempfile.TemporaryDirectory() as directory:
        store = Store(str(Path(directory) / "oauth.db"), Fernet.generate_key().decode())
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            oauth = OAuth(
                store,
                client,
                settings.google_client_id,
                settings.google_client_secret,
                settings.redirect_uri,
            )
            url, _, _ = oauth.start(False)
            try:
                response = await client.get(url)
                body = response.text.lower()
                target = urlparse(str(response.url))
                codes = [
                    "redirect_uri_mismatch",
                    "invalid_client",
                    "deleted_client",
                    "access_denied",
                    "org_internal",
                ]
                errors = [code for code in codes if code in body or code in str(response.url)]
                if errors or "/error" in target.path:
                    result = {
                        "status": "FAIL",
                        "http_status": response.status_code,
                        "google_error_codes": errors,
                        "final_path": target.path,
                    }
                elif (
                    response.status_code == 200
                    and target.hostname == "accounts.google.com"
                    and ("signin" in target.path.lower() or "sign in" in body)
                ):
                    result = {
                        "status": "PASS",
                        "http_status": 200,
                        "result": "Google accepted authorization request and displayed sign-in page; no redirect error",
                        "callback": settings.redirect_uri,
                        "user_consent_completed": False,
                    }
                else:
                    result = {
                        "status": "INCONCLUSIVE",
                        "http_status": response.status_code,
                        "final_host": target.hostname,
                        "final_path": target.path,
                    }
            except httpx.RequestError as exc:
                result = {
                    "status": "FAIL",
                    "error_type": type(exc).__name__,
                    "reason": "Authorization endpoint could not be reached from test environment",
                }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/OAUTH_READINESS.json"))
    args = parser.parse_args()
    result = asyncio.run(check(args.output))
    raise SystemExit(0 if result["status"] == "PASS" else 1)


if __name__ == "__main__":
    main()
