"""Complete auditable authorization map. New operations fail closed."""

from enum import StrEnum


class Tier(StrEnum):
    PUBLIC = "public"
    AUTHENTICATED = "authenticated"


TOOL_TIERS = {
    "similar_videos": Tier.PUBLIC,
    "similar_channels": Tier.PUBLIC,
    "video_summary": Tier.PUBLIC,
    "propose_playlist": Tier.PUBLIC,
    "playlist_from_request": Tier.PUBLIC,
    "video_to_playlist": Tier.PUBLIC,
    "recommendations": Tier.AUTHENTICATED,
    "engagement_analysis": Tier.AUTHENTICATED,
    "create_playlist_draft": Tier.AUTHENTICATED,
    "confirm_playlist_draft": Tier.AUTHENTICATED,
    "playlist_status": Tier.AUTHENTICATED,
    "disconnect": Tier.AUTHENTICATED,
}
RESOURCE_TIERS = {
    "ytintel://capabilities": Tier.PUBLIC,
    "ytintel://skills/video-to-playlist": Tier.PUBLIC,
    "ytintel://quota": Tier.AUTHENTICATED,
}
PUBLIC_METHODS = frozenset(
    {
        "initialize",
        "ping",
        "tools/list",
        "resources/list",
        "resources/templates/list",
        "prompts/list",
        "prompts/get",
    }
)
MCP_SCOPE = "youtube:read"


def tool_tier(name: str) -> Tier:
    return TOOL_TIERS.get(name, Tier.AUTHENTICATED)


def required_tier(message: dict) -> Tier:
    method = message["method"]
    if method in PUBLIC_METHODS or method.startswith("notifications/"):
        return Tier.PUBLIC
    params = message.get("params", {})
    if method == "tools/call":
        return tool_tier(params.get("name", ""))
    if method == "resources/read":
        return RESOURCE_TIERS.get(params.get("uri", ""), Tier.AUTHENTICATED)
    return Tier.AUTHENTICATED
