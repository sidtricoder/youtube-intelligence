"""Loopback-only server entry point. Use explicit uvicorn flags for other hosting."""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "ytintel.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        access_log=False,
        log_level="warning",
    )
