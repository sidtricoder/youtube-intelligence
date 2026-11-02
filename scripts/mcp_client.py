"""Exercise the real Google-backed MCP server. Never sends the owner key."""

import asyncio
import json

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ytintel.config import Settings


async def main():
    settings = Settings()
    async with httpx.AsyncClient(
        headers={"Authorization": "Bearer " + settings.api_key}, timeout=30
    ) as client:
        async with streamable_http_client("http://localhost:8000/mcp/", http_client=client) as (
            read,
            write,
            _,
        ):
            async with ClientSession(read, write) as session:
                await session.initialize()
                print("Tools:", ", ".join(t.name for t in (await session.list_tools()).tools))
                result = await session.call_tool(
                    "propose_playlist",
                    {
                        "topic": "Python programming",
                        "total_seconds": 3600,
                        "max_seconds": 1200,
                        "language": "en",
                    },
                )
                for block in result.content:
                    if block.type == "text":
                        print(json.dumps(json.loads(block.text), indent=2))
                print(
                    "Review the draft in http://localhost:8000 with your owner key. This script does not approve writes."
                )


if __name__ == "__main__":
    asyncio.run(main())
