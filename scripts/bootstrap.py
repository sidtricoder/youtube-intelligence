"""Create local credentials once. Never print their values or overwrite existing configuration."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet


def bootstrap(path: Path = Path(".env")) -> bool:
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    values = {
        "YT_DB_PATH": "data/ytintel.db",
        "YT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        "YT_API_KEY": secrets.token_urlsafe(48),
        "YT_OWNER_KEY": secrets.token_urlsafe(48),
        "YT_YOUTUBE_API_KEY": "",
        "YT_GOOGLE_PROJECT_ID": "",
        "YT_GOOGLE_CLIENT_ID": "",
        "YT_GOOGLE_CLIENT_SECRET": "",
        "YT_REDIRECT_URI": "http://localhost:8000/oauth/callback",
        "YT_UNITS_PER_DAY": "10000",
        "YT_SEARCHES_PER_DAY": "100",
    }
    with os.fdopen(fd, "w") as stream:
        stream.write("\n".join(f"{k}={v}" for k, v in values.items()) + "\n")
    return True


if __name__ == "__main__":
    print(
        "Created .env. Open it locally to copy your owner key."
        if bootstrap()
        else ".env already exists; left unchanged."
    )
