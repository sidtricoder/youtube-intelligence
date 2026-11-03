"""Small structural boundaries implemented by production security services and test fakes."""

from typing import Protocol, runtime_checkable

from mcp.shared.auth import OAuthClientInformationFull

from .store import Clock


@runtime_checkable
class TokenStore(Protocol):
    def save_google(
        self, user_id: str, tokens: dict, expected_generation: int | None = None
    ) -> bool: ...
    def google(self, user_id: str) -> dict | None: ...
    def generation(self, user_id: str) -> int | None: ...
    def current_grant_generation(self, user_id: str) -> int | None: ...
    def save_google_if_current(
        self, user_id: str, previous: dict, tokens: dict, expected_generation: int | None = None
    ) -> bool: ...
    def revoke_user(self, user_id: str, expected_generation: int | None = None) -> bool: ...


@runtime_checkable
class ClientRegistry(Protocol):
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None: ...
    async def register_client(self, client_info: OAuthClientInformationFull) -> None: ...


@runtime_checkable
class SessionStore(Protocol):
    def create_session(
        self, user_id: str, expected_generation: int | None = None
    ) -> tuple[str, str]: ...
    def session(self, opaque: str) -> dict | None: ...
    def delete_session(self, opaque: str) -> None: ...


class QuotaPolicy(Protocol):
    def reserve(self, units: int, searches: int): ...
    def status(self) -> dict: ...


__all__ = ["ClientRegistry", "Clock", "QuotaPolicy", "SessionStore", "TokenStore"]
