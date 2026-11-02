"""One-process ASGI launch options for loopback or platform-managed HTTP hosting."""

import os

import uvicorn


def server_options(environment=None):
    env = os.environ if environment is None else environment
    port = int(env.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be between 1 and 65535")
    hosted = bool(env.get("PORT") or env.get("RENDER_EXTERNAL_URL"))
    return {
        "host": "0.0.0.0" if hosted else "127.0.0.1",
        "port": port,
        "access_log": False,
        "log_level": "warning",
        "proxy_headers": True,
        "forwarded_allow_ips": env.get(
            "FORWARDED_ALLOW_IPS", "*" if env.get("RENDER_EXTERNAL_URL") else "127.0.0.1"
        ),
    }


def main():
    uvicorn.run("ytintel.app:create_app", factory=True, **server_options())
