"""Import a downloaded Web OAuth client and an optional API key into private .env."""

import argparse
import getpass
import json
import os
import secrets
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from dotenv import dotenv_values


def configure(credentials: Path, destination: Path = Path(".env"), api_key: str = "") -> dict:
    try:
        data = json.loads(credentials.read_text())
        web = data.get("web", {})
        if not web.get("client_id") or not web.get("client_secret"):
            raise ValueError("Expected a Google Web application OAuth JSON file")
    except (OSError, json.JSONDecodeError, AttributeError):
        raise ValueError("Could not read a valid Google OAuth client JSON file") from None
    values = {k: v for k, v in dotenv_values(destination).items() if v is not None}
    values.pop("YT_MODE", None)
    values.setdefault("YT_DB_PATH", "data/ytintel.db")
    values.setdefault("YT_ENCRYPTION_KEY", Fernet.generate_key().decode())
    values.setdefault("YT_API_KEY", secrets.token_urlsafe(48))
    values.setdefault("YT_OWNER_KEY", secrets.token_urlsafe(48))
    values.setdefault("YT_REDIRECT_URI", "http://localhost:8000/oauth/callback")
    values.setdefault("YT_UNITS_PER_DAY", "10000")
    values.setdefault("YT_SEARCHES_PER_DAY", "100")
    values.update(
        YT_GOOGLE_CLIENT_ID=web["client_id"],
        YT_GOOGLE_CLIENT_SECRET=web["client_secret"],
        YT_GOOGLE_PROJECT_ID=web.get("project_id", ""),
    )
    if api_key:
        values["YT_YOUTUBE_API_KEY"] = api_key.strip()
    else:
        values.setdefault("YT_YOUTUBE_API_KEY", "")
    # dotenv-compatible quoted values, atomic replace, owner-only POSIX permissions.
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".env-write-", dir=destination.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            for k, v in values.items():
                escaped = v.replace("\\", "\\\\").replace("'", "\\'")
                stream.write(f"{k}='{escaped}'\n")
        os.chmod(name, 0o600)
        os.replace(name, destination)
    finally:
        Path(name).unlink(missing_ok=True)
    return {
        "project_id": web.get("project_id", ""),
        "redirect_uri": values["YT_REDIRECT_URI"],
        "redirect_registered_in_download": values["YT_REDIRECT_URI"]
        in web.get("redirect_uris", []),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("credentials", type=Path)
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    args = parser.parse_args()
    key = getpass.getpass("YouTube API key (leave empty to keep current key): ")
    try:
        report = configure(args.credentials, args.env_file, key)
    except ValueError as exc:
        parser.exit(1, str(exc) + "\n")
    print("Configured Google project:", report["project_id"])
    if not report["redirect_registered_in_download"]:
        print(
            "Register this exact redirect URI in the Google OAuth client:", report["redirect_uri"]
        )
    print("Credentials saved privately; values were not printed.")


if __name__ == "__main__":
    main()
