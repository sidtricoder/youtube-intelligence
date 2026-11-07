"""List MCP tools and, with an externally obtained OAuth token, create a playlist draft."""

import asyncio
import json
import os

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def http_status(error):
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code
    for child in getattr(error, "exceptions", ()):
        status = http_status(child)
        if status is not None:
            return status
    return None


async def main():
    url = os.getenv("MCP_URL", "http://localhost:8000/mcp/")
    token = os.getenv("MCP_ACCESS_TOKEN", "")
    headers = {"Authorization": "Bearer " + token} if token else {}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=30) as client:
            async with streamable_http_client(url, http_client=client) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    print("Tools:", ", ".join(t.name for t in (await session.list_tools()).tools))
                    if not token:
                        print(
                            "No MCP_ACCESS_TOKEN set: create_playlist_draft requires sign-in. "
                            "Sign in on /tester or connect an AI client to build a draft."
                        )
                        return 0
                    result = await session.call_tool(
                        "create_playlist_draft",
                        {
                            "topic": "Python programming",
                            "video_count": 5,
                            "max_seconds": 1200,
                            "language": "en",
                        },
                    )
                    if result.isError:
                        print("FAIL: create_playlist_draft returned an error.")
                        return 1
                    for block in result.content:
                        if block.type == "text":
                            print(json.dumps(json.loads(block.text), indent=2))
                    print("Draft created. Confirm it with confirm_playlist_draft or approval_url.")
    except Exception as exc:
        status = http_status(exc)
        if status:
            print(
                f"FAIL: MCP server returned HTTP {status}. Check the server URL and OAuth authorization."
            )
        else:
            print("FAIL: MCP connection or preview failed (" + type(exc).__name__ + ").")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
